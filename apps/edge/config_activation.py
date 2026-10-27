"""Local & Signed Config Activation with Durable High-Water Mark and LKG (Tickets #34, #35).

Supports four distinct activation and lifecycle paths:
  1. Local config staging & activation at session boundary: fail-fast module x camera validation
     without waiting for trust infrastructure, maintaining LKG and desired/observed versions.
  2. Signed remote bundle staging & activation: cryptographic & target verification against
     durable monotonic high-water mark, inner config validation, atomic advance of high-water mark
     and LKG on success, preserving LKG and observed version on any failure.
  3. Canary Release: stage a signed bundle for canary observation on a subset of cameras or modules,
     monitoring error rate, health status, or explicit rollback trigger while preserving baseline LKG.
  4. Authorized Rollback: restore previous LKG/target config with a fresh, higher trust sequence
     signed by authorized role (config_signer or config_rollback), strictly advancing monotonic
     high-water mark (never downgrading), and enforcing compatibility & lineage policies.

Ensures recorder isolation: recorder is never stopped or reset across failed or successful
activations, and emitted event provenance carries exact observed_version snapshot hash.
All rollback and canary state survives process reboot / crash through the SQLite WAL+FULL store.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from domain.alert_module_config import (
    ActivationState,
    AlertModuleRegistry,
    CameraModuleConfig,
    ConfigError,
    STATUS_ACTIVE,
    STATUS_DISABLED,
    STATUS_REJECTED,
)
from domain.signed_config import (
    CanarySpec,
    CompatibilityPolicy,
    ERROR_CANARY_FAILURE,
    ERROR_INCOMPATIBLE_LINEAGE,
    ERROR_INVALID_ROLLBACK,
    ROLE_CONFIG_ROLLBACK,
    ROLE_CONFIG_SIGNER,
    SignedConfigBundle,
    SignedConfigError,
    TargetSpec,
    TrustedKeyRing,
    canonical_bundle_bytes,
    canonical_bundle_hash,
    is_rollback_bundle,
    verify_signed_bundle,
)

__all__ = [
    "ACTIVATION_TYPE_CANARY",
    "ACTIVATION_TYPE_LOCAL",
    "ACTIVATION_TYPE_REMOTE",
    "ACTIVATION_TYPE_ROLLBACK",
    "ActivationResult",
    "ConfigActivationManager",
    "DurableConfigStateStore",
    "RecorderContinuityError",
    "STATUS_CANARY",
    "STATUS_FAILED",
    "STATUS_ROLLED_BACK",
]

ACTIVATION_TYPE_LOCAL: Final[str] = "local"
ACTIVATION_TYPE_REMOTE: Final[str] = "remote_signed"
ACTIVATION_TYPE_CANARY: Final[str] = "canary"
ACTIVATION_TYPE_ROLLBACK: Final[str] = "rollback"

STATUS_CANARY: Final[str] = "canary"
STATUS_ROLLED_BACK: Final[str] = "rolled_back"
STATUS_FAILED: Final[str] = "failed"

CONFIG_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {"module", "camera_id", "factory", "schema_version", "config_version", "model_lineage", "lineage"}
)


class RecorderContinuityError(RuntimeError):
    """Raised if recorder reference is improperly interrupted during config activation."""


@dataclass(frozen=True)
class ActivationResult:
    """Outcome of an activation attempt at session boundary."""

    success: bool
    status: str
    activation_type: str
    desired_version: Optional[int]
    observed_version: Optional[int]
    error: Optional[str] = None
    reason: Optional[str] = None
    trust_sequence: Optional[int] = None
    snapshot_hash: Optional[str] = None
    lkg_snapshot: Optional[dict[str, Any]] = None
    states: Tuple[ActivationState, ...] = ()


class DurableConfigStateStore:
    """Durable SQLite-backed state store for high-water mark, versions, LKG, and audit history.

    Uses WAL mode and synchronous=FULL to guarantee that power cuts or process crashes
    never roll back trust sequence (high-water mark) or corrupt the last-known-good snapshot.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            parent = os.path.dirname(os.path.abspath(self._db_path))
            if parent:
                os.makedirs(parent, exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None,  # Autocommit mode, transactions managed explicitly
        )
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=FULL;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS config_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    high_water_mark INTEGER NOT NULL DEFAULT 0,
                    desired_version INTEGER,
                    observed_version INTEGER,
                    lkg_snapshot TEXT,
                    canary_state TEXT,
                    last_rollback_sequence INTEGER,
                    last_action TEXT,
                    updated_at REAL NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS activation_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    activation_type TEXT NOT NULL,
                    desired_version INTEGER,
                    observed_version INTEGER,
                    trust_sequence INTEGER,
                    status TEXT NOT NULL,
                    reason TEXT,
                    config_hash TEXT,
                    snapshot TEXT,
                    rollback_for_sequence INTEGER,
                    canary_spec TEXT
                );
                """
            )
            # Schema migrations for existing databases
            for col, col_type in (
                ("canary_state", "TEXT"),
                ("last_rollback_sequence", "INTEGER"),
                ("last_action", "TEXT"),
            ):
                try:
                    cur.execute(f"ALTER TABLE config_state ADD COLUMN {col} {col_type};")
                except sqlite3.OperationalError:
                    pass

            for col, col_type in (
                ("rollback_for_sequence", "INTEGER"),
                ("canary_spec", "TEXT"),
            ):
                try:
                    cur.execute(f"ALTER TABLE activation_audit ADD COLUMN {col} {col_type};")
                except sqlite3.OperationalError:
                    pass

            # Ensure singleton state row exists with default HWM=0
            cur.execute(
                """
                INSERT OR IGNORE INTO config_state (id, high_water_mark, updated_at)
                VALUES (1, 0, ?);
                """,
                (time.time(),),
            )

    def get_high_water_mark(self) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT high_water_mark FROM config_state WHERE id = 1;")
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT high_water_mark, desired_version, observed_version, lkg_snapshot,
                       canary_state, last_rollback_sequence, last_action, updated_at
                FROM config_state WHERE id = 1;
                """
            )
            row = cur.fetchone()
            if not row:
                return {
                    "high_water_mark": 0,
                    "desired_version": None,
                    "observed_version": None,
                    "lkg": None,
                    "canary_state": None,
                    "last_rollback_sequence": None,
                    "last_action": None,
                    "updated_at": 0.0,
                }
            lkg = json.loads(row[3]) if row[3] else None
            canary_state = json.loads(row[4]) if row[4] else None
            return {
                "high_water_mark": row[0],
                "desired_version": row[1],
                "observed_version": row[2],
                "lkg": lkg,
                "canary_state": canary_state,
                "last_rollback_sequence": row[5],
                "last_action": row[6],
                "updated_at": row[7],
            }

    def get_lkg(self) -> Optional[dict[str, Any]]:
        state = self.get_state()
        return state.get("lkg")

    def get_canary_state(self) -> Optional[dict[str, Any]]:
        state = self.get_state()
        return state.get("canary_state")

    def get_last_rollback_sequence(self) -> Optional[int]:
        state = self.get_state()
        return state.get("last_rollback_sequence")

    def update_desired_version(self, desired_version: int) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                UPDATE config_state
                SET desired_version = ?, updated_at = ?
                WHERE id = 1;
                """,
                (desired_version, time.time()),
            )

    def commit_activation(
        self,
        *,
        desired_version: int,
        observed_version: int,
        lkg_snapshot: dict[str, Any],
        trust_sequence: Optional[int] = None,
    ) -> None:
        """Atomically advance observed state, LKG, and optionally monotonic high-water mark."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE;")
            try:
                cur.execute("SELECT high_water_mark FROM config_state WHERE id = 1;")
                row = cur.fetchone()
                current_hwm = int(row[0]) if row and row[0] is not None else 0

                if trust_sequence is not None:
                    if trust_sequence <= current_hwm:
                        raise ValueError(
                            f"trust_sequence {trust_sequence} must be > current high_water_mark {current_hwm}"
                        )
                    new_hwm = trust_sequence
                else:
                    new_hwm = current_hwm

                lkg_json = json.dumps(lkg_snapshot, sort_keys=True)
                cur.execute(
                    """
                    UPDATE config_state
                    SET high_water_mark = ?, desired_version = ?, observed_version = ?,
                        lkg_snapshot = ?, canary_state = NULL, last_action = 'normal', updated_at = ?
                    WHERE id = 1;
                    """,
                    (new_hwm, desired_version, observed_version, lkg_json, time.time()),
                )
                cur.execute("COMMIT;")
            except Exception:
                cur.execute("ROLLBACK;")
                raise

    def commit_rollback(
        self,
        *,
        desired_version: int,
        observed_version: int,
        lkg_snapshot: dict[str, Any],
        trust_sequence: int,
        rollback_for_sequence: Optional[int] = None,
    ) -> None:
        """Atomically advance monotonic high-water mark, update LKG and versions for authorized rollback."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE;")
            try:
                cur.execute("SELECT high_water_mark FROM config_state WHERE id = 1;")
                row = cur.fetchone()
                current_hwm = int(row[0]) if row and row[0] is not None else 0

                if trust_sequence <= current_hwm:
                    raise ValueError(
                        f"rollback trust_sequence {trust_sequence} must be strictly > current high_water_mark {current_hwm}"
                    )
                new_hwm = trust_sequence

                lkg_json = json.dumps(lkg_snapshot, sort_keys=True)
                cur.execute(
                    """
                    UPDATE config_state
                    SET high_water_mark = ?, desired_version = ?, observed_version = ?,
                        lkg_snapshot = ?, canary_state = NULL, last_rollback_sequence = ?,
                        last_action = 'rollback', updated_at = ?
                    WHERE id = 1;
                    """,
                    (new_hwm, desired_version, observed_version, lkg_json, trust_sequence, time.time()),
                )
                cur.execute("COMMIT;")
            except Exception:
                cur.execute("ROLLBACK;")
                raise

    def commit_canary(
        self,
        *,
        canary_state: dict[str, Any],
        trust_sequence: int,
    ) -> None:
        """Atomically advance monotonic high-water mark and record active canary state while preserving baseline LKG."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE;")
            try:
                cur.execute("SELECT high_water_mark FROM config_state WHERE id = 1;")
                row = cur.fetchone()
                current_hwm = int(row[0]) if row and row[0] is not None else 0

                if trust_sequence <= current_hwm:
                    raise ValueError(
                        f"canary trust_sequence {trust_sequence} must be strictly > current high_water_mark {current_hwm}"
                    )
                new_hwm = trust_sequence
                canary_json = json.dumps(canary_state, sort_keys=True)

                cur.execute(
                    """
                    UPDATE config_state
                    SET high_water_mark = ?, canary_state = ?, last_action = 'canary', updated_at = ?
                    WHERE id = 1;
                    """,
                    (new_hwm, canary_json, time.time()),
                )
                cur.execute("COMMIT;")
            except Exception:
                cur.execute("ROLLBACK;")
                raise

    def clear_canary_state(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                UPDATE config_state
                SET canary_state = NULL, updated_at = ?
                WHERE id = 1;
                """,
                (time.time(),),
            )

    def record_audit(
        self,
        *,
        activation_type: str,
        status: str,
        desired_version: Optional[int],
        observed_version: Optional[int],
        trust_sequence: Optional[int] = None,
        reason: Optional[str] = None,
        config_hash: Optional[str] = None,
        snapshot: Optional[dict[str, Any]] = None,
        rollback_for_sequence: Optional[int] = None,
        canary_spec: Optional[dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO activation_audit (
                    timestamp, activation_type, desired_version, observed_version,
                    trust_sequence, status, reason, config_hash, snapshot,
                    rollback_for_sequence, canary_spec
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    time.time(),
                    activation_type,
                    desired_version,
                    observed_version,
                    trust_sequence,
                    status,
                    reason,
                    config_hash,
                    json.dumps(snapshot, sort_keys=True) if snapshot else None,
                    rollback_for_sequence,
                    json.dumps(canary_spec, sort_keys=True) if canary_spec else None,
                ),
            )

    def get_audit_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, timestamp, activation_type, desired_version, observed_version,
                       trust_sequence, status, reason, config_hash, snapshot,
                       rollback_for_sequence, canary_spec
                FROM activation_audit
                ORDER BY id DESC
                LIMIT ?;
                """,
                (limit,),
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "timestamp": r[1],
                    "activation_type": r[2],
                    "desired_version": r[3],
                    "observed_version": r[4],
                    "trust_sequence": r[5],
                    "status": r[6],
                    "reason": r[7],
                    "config_hash": r[8],
                    "snapshot": json.loads(r[9]) if r[9] else None,
                    "rollback_for_sequence": r[10],
                    "canary_spec": json.loads(r[11]) if r[11] else None,
                }
                for r in rows
            ]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class ConfigActivationManager:
    """Manages local, signed remote, canary, and authorized rollback activations with durable HWM and LKG."""

    def __init__(
        self,
        store: DurableConfigStateStore,
        registry: Optional[AlertModuleRegistry] = None,
        *,
        keyring: Optional[TrustedKeyRing] = None,
        target_device_id: Optional[str] = None,
        target_site_id: Optional[str] = None,
        target_profile: Optional[str] = None,
        clock_synchronized_provider: Optional[Callable[[], bool]] = None,
        time_provider: Optional[Callable[[], float]] = None,
        recorder: Optional[Any] = None,
        compatibility_policy: Optional[CompatibilityPolicy] = None,
    ) -> None:
        self.store = store
        self.registry = registry if registry is not None else AlertModuleRegistry()
        self.keyring = keyring if keyring is not None else TrustedKeyRing()
        self.target = TargetSpec(
            device_id=target_device_id,
            site_id=target_site_id,
            profile=target_profile,
        )
        self._clock_synchronized_provider = (
            clock_synchronized_provider if clock_synchronized_provider is not None else (lambda: True)
        )
        self._time_provider = time_provider if time_provider is not None else time.time
        self.recorder = recorder
        self.compatibility_policy = compatibility_policy

        # Restore LKG and any active canary from durable store on cold start / reboot
        self._restore_lkg_if_present()

    def _apply_lkg_to_registry(self, lkg: dict[str, Any]) -> None:
        configs = lkg.get("configs", [])
        provenance = lkg.get("provenance", {})
        for cfg_dict in configs:
            if not isinstance(cfg_dict, dict):
                continue
            module = cfg_dict.get("module")
            camera_id = cfg_dict.get("camera_id")
            if not module or not camera_id:
                continue
            try:
                self.registry.definition(module)
                clean_cfg = {k: v for k, v in cfg_dict.items() if k not in CONFIG_METADATA_KEYS}
                parsed = self.registry.parse(module, camera_id, clean_cfg)
                self.registry.stage(parsed)
                prov_key = f"{module}:{camera_id}"
                prov = provenance.get(prov_key, {})
                sess_id = prov.get("session_id", "restored-session")
                self.registry.activate(parsed, session_id=sess_id)
            except Exception:
                pass

    def _restore_lkg_if_present(self) -> None:
        lkg = self.store.get_lkg()
        if not lkg or not isinstance(lkg, dict):
            return
        self._apply_lkg_to_registry(lkg)

        # Check if an active canary was in progress before restart
        canary_state = self.store.get_canary_state()
        if canary_state and isinstance(canary_state, dict):
            canary_configs = canary_state.get("canary_configs", [])
            session_id = canary_state.get("session_id", "restored-canary-session")
            for cfg_dict in canary_configs:
                if not isinstance(cfg_dict, dict):
                    continue
                module = cfg_dict.get("module")
                camera_id = cfg_dict.get("camera_id")
                if not module or not camera_id:
                    continue
                try:
                    self.registry.definition(module)
                    clean_cfg = {k: v for k, v in cfg_dict.items() if k not in CONFIG_METADATA_KEYS}
                    parsed = self.registry.parse(module, camera_id, clean_cfg)
                    self.registry.stage(parsed)
                    self.registry.activate(parsed, session_id=session_id)
                except Exception:
                    # If canary re-application fails on restart, fallback safely to LKG
                    self._apply_lkg_to_registry(lkg)
                    self.store.clear_canary_state()
                    break

    def set_recorder(self, recorder: Any) -> None:
        """Attach independent recorder reference."""
        self.recorder = recorder

    def reset_session(self, camera_id: str, session_id: str) -> Tuple[str, ...]:
        """Reset continuity for camera modules at a stream session boundary."""
        return self.registry.reset_session(camera_id, session_id)

    @staticmethod
    def _build_lkg_snapshot(
        parsed_configs: list[CameraModuleConfig],
        max_version: int,
        session_id: str,
    ) -> tuple[dict[str, Any], str]:
        config_descs = [cfg.describe() for cfg in parsed_configs]
        snapshot_hash = canonical_bundle_hash(config_descs)
        provenance = {
            f"{cfg.module}:{cfg.camera_id}": {
                "module": cfg.module,
                "camera_id": cfg.camera_id,
                "version": cfg.version,
                "config_hash": cfg.config_hash,
                "session_id": session_id,
            }
            for cfg in parsed_configs
        }
        lkg_snapshot = {
            "observed_version": max_version,
            "snapshot_hash": snapshot_hash,
            "configs": config_descs,
            "provenance": provenance,
        }
        return lkg_snapshot, snapshot_hash

    def get_high_water_mark(self) -> int:
        return self.store.get_high_water_mark()

    def get_observed_version(self) -> Optional[int]:
        return self.store.get_state().get("observed_version")

    def get_desired_version(self) -> Optional[int]:
        return self.store.get_state().get("desired_version")

    def get_lkg(self) -> Optional[dict[str, Any]]:
        return self.store.get_lkg()

    def get_canary_state(self) -> Optional[dict[str, Any]]:
        return self.store.get_canary_state()

    def stage_local_config(
        self, configs: Iterable[Mapping[str, Any] | CameraModuleConfig]
    ) -> list[ActivationState]:
        """Stage local configurations for upcoming session boundary activation."""
        staged_states: list[ActivationState] = []
        max_desired = self.get_desired_version() or 0
        for item in configs:
            if isinstance(item, CameraModuleConfig):
                cfg = item
            else:
                module = item.get("module")
                camera_id = item.get("camera_id")
                if not module or not camera_id:
                    raise ConfigError("invalid_config", "config requires module and camera_id")
                clean_item = {k: v for k, v in item.items() if k not in CONFIG_METADATA_KEYS}
                cfg = self.registry.parse(str(module), str(camera_id), clean_item)
            state = self.registry.stage(cfg)
            staged_states.append(state)
            if cfg.version > max_desired:
                max_desired = cfg.version

        self.store.update_desired_version(max_desired)
        return staged_states

    def activate_local(
        self,
        configs: Sequence[Mapping[str, Any] | CameraModuleConfig],
        *,
        session_id: str,
    ) -> ActivationResult:
        """Local config activation at session boundary.

        Does NOT wait for a signed bundle or trust infrastructure.
        Validates module x camera configs fail-fast.
        On invalid local config, rejects activation while keeping previous LKG intact.
        Ensures recorder isolation (recorder is never stopped or reset).
        """
        # Step 1: Fail-fast validation of all module x camera configs
        parsed_configs: list[CameraModuleConfig] = []
        max_version = 0
        try:
            for item in configs:
                if isinstance(item, CameraModuleConfig):
                    self.registry.definition(item.module)
                    parsed_cfg = item
                elif isinstance(item, Mapping):
                    module = item.get("module")
                    camera_id = item.get("camera_id")
                    if not module or not camera_id:
                        raise ConfigError("invalid_config", "config requires module and camera_id")
                    clean_item = {k: v for k, v in item.items() if k not in CONFIG_METADATA_KEYS}
                    parsed_cfg = self.registry.parse(str(module), str(camera_id), clean_item)
                else:
                    raise ConfigError("invalid_config", "expected CameraModuleConfig or Mapping")

                parsed_configs.append(parsed_cfg)
                if parsed_cfg.version > max_version:
                    max_version = parsed_cfg.version
        except Exception as err:
            err_code = getattr(err, "code", "validation_failed")
            err_msg = str(err)
            current_state = self.store.get_state()
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_LOCAL,
                status=STATUS_REJECTED,
                desired_version=max_version if max_version > 0 else current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                reason=err_msg,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_LOCAL,
                desired_version=max_version if max_version > 0 else current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                error=err_msg,
                reason=err_code,
                lkg_snapshot=self.store.get_lkg(),
            )

        # Step 2: Session boundary activation in registry
        states: list[ActivationState] = []
        for cfg in parsed_configs:
            self.registry.stage(cfg)
            state = self.registry.activate(cfg, session_id=session_id)
            states.append(state)

        # Check if any activation was rejected by registry (e.g. stale config version)
        rejected = [s for s in states if s.status == STATUS_REJECTED]
        if rejected:
            current_state = self.store.get_state()
            reason = rejected[0].reason or "stale_config_version"
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_LOCAL,
                status=STATUS_REJECTED,
                desired_version=max_version,
                observed_version=current_state.get("observed_version"),
                reason=reason,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_LOCAL,
                desired_version=max_version,
                observed_version=current_state.get("observed_version"),
                error=reason,
                reason=reason,
                lkg_snapshot=self.store.get_lkg(),
                states=tuple(states),
            )

        # Step 3: Build LKG snapshot and provenance
        lkg_snapshot, snapshot_hash = self._build_lkg_snapshot(parsed_configs, max_version, session_id)

        # Step 4: Atomically persist activation in SQLite store
        self.store.commit_activation(
            desired_version=max_version,
            observed_version=max_version,
            lkg_snapshot=lkg_snapshot,
        )
        self.store.record_audit(
            activation_type=ACTIVATION_TYPE_LOCAL,
            status=STATUS_ACTIVE,
            desired_version=max_version,
            observed_version=max_version,
            config_hash=snapshot_hash,
            snapshot=lkg_snapshot,
        )

        return ActivationResult(
            success=True,
            status=STATUS_ACTIVE,
            activation_type=ACTIVATION_TYPE_LOCAL,
            desired_version=max_version,
            observed_version=max_version,
            snapshot_hash=snapshot_hash,
            lkg_snapshot=lkg_snapshot,
            states=tuple(states),
        )

    def activate_signed_bundle(
        self,
        bundle: SignedConfigBundle | Mapping[str, Any],
        *,
        session_id: str,
        clock_synchronized: Optional[bool] = None,
    ) -> ActivationResult:
        """Signed remote bundle staging and activation at session boundary.

        Dispatches to authorized rollback or canary activation if bundle indicates such action.
        Verifies bundle cryptography, target constraints, monotonic sequence > durable HWM,
        and clock certainty. Validates inner module x camera config before committing.
        On success, atomically advances high-water mark and LKG.
        On failure, preserves previous LKG and observed version.
        Recorder is never interrupted.
        """
        # Inspect payload to dispatch to rollback or canary if indicated
        payload = getattr(bundle, "payload", bundle.get("payload") if isinstance(bundle, Mapping) else None)
        if isinstance(payload, Mapping):
            if is_rollback_bundle(payload):
                return self.activate_signed_rollback(
                    bundle,
                    session_id=session_id,
                    clock_synchronized=clock_synchronized,
                )
            if "canary" in payload and isinstance(payload["canary"], Mapping):
                return self.activate_canary(
                    bundle,
                    session_id=session_id,
                    clock_synchronized=clock_synchronized,
                )

        clock_sync = (
            self._clock_synchronized_provider()
            if clock_synchronized is None
            else clock_synchronized
        )
        current_time = self._time_provider()
        current_state = self.store.get_state()
        hwm = self.store.get_high_water_mark()

        # Step 1: Verify signed bundle envelope
        try:
            verified = verify_signed_bundle(
                bundle,
                keyring=self.keyring,
                high_water_mark=hwm,
                expected_target=self.target,
                current_time=current_time,
                clock_synchronized=clock_sync,
                required_role=ROLE_CONFIG_SIGNER,
                compatibility_policy=self.compatibility_policy,
                current_lkg=self.store.get_lkg(),
            )
        except SignedConfigError as err:
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_REMOTE,
                status=STATUS_REJECTED,
                desired_version=current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                trust_sequence=getattr(bundle, "trust_sequence", None)
                if isinstance(bundle, SignedConfigBundle)
                else (bundle.get("trust_sequence") if isinstance(bundle, Mapping) else None),
                reason=err.message,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_REMOTE,
                desired_version=current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                error=err.message,
                reason=err.code,
                lkg_snapshot=self.store.get_lkg(),
            )

        # Step 2: Extract and validate inner module x camera configs fail-fast
        verified_payload = verified.payload
        raw_configs: list[Any] = []
        if "configs" in verified_payload and isinstance(verified_payload["configs"], (list, tuple)):
            raw_configs = list(verified_payload["configs"])
        elif "modules" in verified_payload and isinstance(verified_payload["modules"], (list, tuple)):
            raw_configs = list(verified_payload["modules"])
        elif "module" in verified_payload and "camera_id" in verified_payload:
            raw_configs = [verified_payload]
        else:
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_REMOTE,
                status=STATUS_REJECTED,
                desired_version=current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                trust_sequence=verified.trust_sequence,
                reason="payload contains no recognizable module configurations",
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_REMOTE,
                desired_version=current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                error="payload contains no recognizable module configurations",
                reason="invalid_payload_structure",
                trust_sequence=verified.trust_sequence,
                lkg_snapshot=self.store.get_lkg(),
            )

        parsed_configs: list[CameraModuleConfig] = []
        max_version = 0
        try:
            for item in raw_configs:
                if not isinstance(item, Mapping):
                    raise ConfigError("invalid_config", "each bundle config must be a mapping")
                module = item.get("module")
                camera_id = item.get("camera_id")
                if not module or not camera_id:
                    raise ConfigError("invalid_config", "config requires module and camera_id")
                clean_item = {k: v for k, v in item.items() if k not in CONFIG_METADATA_KEYS}
                parsed_cfg = self.registry.parse(str(module), str(camera_id), clean_item)
                parsed_configs.append(parsed_cfg)
                if parsed_cfg.version > max_version:
                    max_version = parsed_cfg.version
        except Exception as err:
            err_code = getattr(err, "code", "inner_config_validation_failed")
            err_msg = str(err)
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_REMOTE,
                status=STATUS_REJECTED,
                desired_version=max_version if max_version > 0 else current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                trust_sequence=verified.trust_sequence,
                reason=err_msg,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_REMOTE,
                desired_version=max_version if max_version > 0 else current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                error=err_msg,
                reason=err_code,
                trust_sequence=verified.trust_sequence,
                lkg_snapshot=self.store.get_lkg(),
            )

        # Step 3: Session boundary activation in registry
        states: list[ActivationState] = []
        for cfg in parsed_configs:
            self.registry.stage(cfg)
            state = self.registry.activate(cfg, session_id=session_id)
            states.append(state)

        rejected = [s for s in states if s.status == STATUS_REJECTED]
        if rejected:
            reason = rejected[0].reason or "stale_config_version"
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_REMOTE,
                status=STATUS_REJECTED,
                desired_version=max_version,
                observed_version=current_state.get("observed_version"),
                trust_sequence=verified.trust_sequence,
                reason=reason,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_REMOTE,
                desired_version=max_version,
                observed_version=current_state.get("observed_version"),
                error=reason,
                reason=reason,
                trust_sequence=verified.trust_sequence,
                lkg_snapshot=self.store.get_lkg(),
                states=tuple(states),
            )

        # Step 4: Build new LKG snapshot and provenance
        lkg_snapshot, snapshot_hash = self._build_lkg_snapshot(parsed_configs, max_version, session_id)
        if "model_lineage" in verified_payload:
            lkg_snapshot["model_lineage"] = verified_payload["model_lineage"]
        if "schema_version" in verified_payload:
            lkg_snapshot["schema_version"] = verified_payload["schema_version"]

        # Step 5: Atomically advance high-water mark and persist LKG in SQLite store
        self.store.commit_activation(
            desired_version=max_version,
            observed_version=max_version,
            lkg_snapshot=lkg_snapshot,
            trust_sequence=verified.trust_sequence,
        )
        self.store.record_audit(
            activation_type=ACTIVATION_TYPE_REMOTE,
            status=STATUS_ACTIVE,
            desired_version=max_version,
            observed_version=max_version,
            trust_sequence=verified.trust_sequence,
            config_hash=snapshot_hash,
            snapshot=lkg_snapshot,
        )

        return ActivationResult(
            success=True,
            status=STATUS_ACTIVE,
            activation_type=ACTIVATION_TYPE_REMOTE,
            desired_version=max_version,
            observed_version=max_version,
            trust_sequence=verified.trust_sequence,
            snapshot_hash=snapshot_hash,
            lkg_snapshot=lkg_snapshot,
            states=tuple(states),
        )

    def activate_signed_rollback(
        self,
        bundle: SignedConfigBundle | Mapping[str, Any],
        *,
        session_id: str,
        clock_synchronized: Optional[bool] = None,
    ) -> ActivationResult:
        """Authorized rollback with a fresh, higher trust sequence signed by authorized role.

        Per spec:
          - Rollback NEVER downgrades the durable monotonic high_water_mark.
          - Requires fresh trust_sequence > current HWM.
          - Requires key authorized with role config_signer or config_rollback.
          - Payload carries target LKG/rollback configuration and action="rollback" or rollback_for_sequence.
          - Validates lineage & compatibility policy to prevent silent mixing of incompatible lineages.
          - Validates inner module x camera configs fail-fast.
          - On failure, preserves previous LKG intact and records audit status="rejected".
          - On success, atomically advances high-water mark, restores target LKG, and records audit.
          - Recorder reference is never interrupted.
        """
        clock_sync = (
            self._clock_synchronized_provider()
            if clock_synchronized is None
            else clock_synchronized
        )
        current_time = self._time_provider()
        current_state = self.store.get_state()
        hwm = self.store.get_high_water_mark()

        # Step 1: Verify envelope cryptography, target matching, clock certainty, and sequence > HWM.
        # Key must have ROLE_CONFIG_SIGNER or ROLE_CONFIG_ROLLBACK.
        try:
            verified = verify_signed_bundle(
                bundle,
                keyring=self.keyring,
                high_water_mark=hwm,
                expected_target=self.target,
                current_time=current_time,
                clock_synchronized=clock_sync,
                required_role=(ROLE_CONFIG_SIGNER, ROLE_CONFIG_ROLLBACK),
                compatibility_policy=self.compatibility_policy,
                current_lkg=self.store.get_lkg(),
            )
        except SignedConfigError as err:
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_ROLLBACK,
                status=STATUS_REJECTED,
                desired_version=current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                trust_sequence=getattr(bundle, "trust_sequence", None)
                if isinstance(bundle, SignedConfigBundle)
                else (bundle.get("trust_sequence") if isinstance(bundle, Mapping) else None),
                reason=err.message,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_ROLLBACK,
                desired_version=current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                error=err.message,
                reason=err.code,
                lkg_snapshot=self.store.get_lkg(),
            )

        payload = verified.payload
        rollback_for_sequence = payload.get("rollback_for_sequence")

        # Step 2: Extract and validate target rollback configs
        raw_configs: list[Any] = []
        if "configs" in payload and isinstance(payload["configs"], (list, tuple)):
            raw_configs = list(payload["configs"])
        elif "target_lkg" in payload and isinstance(payload["target_lkg"], Mapping):
            tl = payload["target_lkg"]
            if "configs" in tl and isinstance(tl["configs"], (list, tuple)):
                raw_configs = list(tl["configs"])
        elif "modules" in payload and isinstance(payload["modules"], (list, tuple)):
            raw_configs = list(payload["modules"])
        elif "module" in payload and "camera_id" in payload:
            raw_configs = [payload]
        else:
            reason = "rollback payload contains no recognizable module configurations"
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_ROLLBACK,
                status=STATUS_REJECTED,
                desired_version=current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                trust_sequence=verified.trust_sequence,
                rollback_for_sequence=rollback_for_sequence,
                reason=reason,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_ROLLBACK,
                desired_version=current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                error=reason,
                reason=ERROR_INVALID_ROLLBACK,
                trust_sequence=verified.trust_sequence,
                lkg_snapshot=self.store.get_lkg(),
            )

        parsed_configs: list[CameraModuleConfig] = []
        max_version = 0
        try:
            for item in raw_configs:
                if not isinstance(item, Mapping):
                    raise ConfigError("invalid_config", "each rollback config must be a mapping")
                module = item.get("module")
                camera_id = item.get("camera_id")
                if not module or not camera_id:
                    raise ConfigError("invalid_config", "config requires module and camera_id")
                clean_item = {k: v for k, v in item.items() if k not in CONFIG_METADATA_KEYS}
                parsed_cfg = self.registry.parse(str(module), str(camera_id), clean_item)
                parsed_configs.append(parsed_cfg)
                if parsed_cfg.version > max_version:
                    max_version = parsed_cfg.version
        except Exception as err:
            err_code = getattr(err, "code", "inner_config_validation_failed")
            err_msg = str(err)
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_ROLLBACK,
                status=STATUS_REJECTED,
                desired_version=max_version if max_version > 0 else current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                trust_sequence=verified.trust_sequence,
                rollback_for_sequence=rollback_for_sequence,
                reason=err_msg,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_ROLLBACK,
                desired_version=max_version if max_version > 0 else current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                error=err_msg,
                reason=err_code,
                trust_sequence=verified.trust_sequence,
                lkg_snapshot=self.store.get_lkg(),
            )

        # Step 3: Session boundary activation in registry
        states: list[ActivationState] = []
        for cfg in parsed_configs:
            self.registry.stage(cfg)
            state = self.registry.activate(cfg, session_id=session_id)
            states.append(state)

        rejected = [s for s in states if s.status == STATUS_REJECTED]
        if rejected:
            reason = rejected[0].reason or "stale_config_version"
            # Revert registry to previous LKG if any was partially changed
            cur_lkg = self.store.get_lkg()
            if cur_lkg:
                self._apply_lkg_to_registry(cur_lkg)
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_ROLLBACK,
                status=STATUS_REJECTED,
                desired_version=max_version,
                observed_version=current_state.get("observed_version"),
                trust_sequence=verified.trust_sequence,
                rollback_for_sequence=rollback_for_sequence,
                reason=reason,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_ROLLBACK,
                desired_version=max_version,
                observed_version=current_state.get("observed_version"),
                error=reason,
                reason=reason,
                trust_sequence=verified.trust_sequence,
                lkg_snapshot=self.store.get_lkg(),
                states=tuple(states),
            )

        # Step 4: Build restored LKG snapshot and provenance
        lkg_snapshot, snapshot_hash = self._build_lkg_snapshot(parsed_configs, max_version, session_id)
        if "model_lineage" in payload:
            lkg_snapshot["model_lineage"] = payload["model_lineage"]
        if "schema_version" in payload:
            lkg_snapshot["schema_version"] = payload["schema_version"]

        # Step 5: Atomically advance HWM to new sequence, update LKG, and persist in SQLite
        self.store.commit_rollback(
            desired_version=max_version,
            observed_version=max_version,
            lkg_snapshot=lkg_snapshot,
            trust_sequence=verified.trust_sequence,
            rollback_for_sequence=rollback_for_sequence,
        )
        self.store.record_audit(
            activation_type=ACTIVATION_TYPE_ROLLBACK,
            status=STATUS_ACTIVE,
            desired_version=max_version,
            observed_version=max_version,
            trust_sequence=verified.trust_sequence,
            rollback_for_sequence=rollback_for_sequence,
            config_hash=snapshot_hash,
            snapshot=lkg_snapshot,
            reason=f"authorized_rollback_to_sequence_{rollback_for_sequence}" if rollback_for_sequence else "authorized_rollback",
        )

        return ActivationResult(
            success=True,
            status=STATUS_ACTIVE,
            activation_type=ACTIVATION_TYPE_ROLLBACK,
            desired_version=max_version,
            observed_version=max_version,
            trust_sequence=verified.trust_sequence,
            snapshot_hash=snapshot_hash,
            lkg_snapshot=lkg_snapshot,
            states=tuple(states),
        )

    def activate_canary(
        self,
        bundle: SignedConfigBundle | Mapping[str, Any],
        *,
        session_id: str,
        canary_cameras: Optional[Sequence[str]] = None,
        canary_modules: Optional[Sequence[str]] = None,
        clock_synchronized: Optional[bool] = None,
    ) -> ActivationResult:
        """Stage a signed bundle for canary observation on a subset of cameras or modules.

        Monitors error rate and health status while preserving baseline LKG intact.
        High-water mark is advanced to prevent bundle replay.
        """
        clock_sync = (
            self._clock_synchronized_provider()
            if clock_synchronized is None
            else clock_synchronized
        )
        current_time = self._time_provider()
        current_state = self.store.get_state()
        hwm = self.store.get_high_water_mark()

        # Step 1: Verify signed bundle envelope (role config_signer required)
        try:
            verified = verify_signed_bundle(
                bundle,
                keyring=self.keyring,
                high_water_mark=hwm,
                expected_target=self.target,
                current_time=current_time,
                clock_synchronized=clock_sync,
                required_role=ROLE_CONFIG_SIGNER,
                compatibility_policy=self.compatibility_policy,
                current_lkg=self.store.get_lkg(),
            )
        except SignedConfigError as err:
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_CANARY,
                status=STATUS_REJECTED,
                desired_version=current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                trust_sequence=getattr(bundle, "trust_sequence", None)
                if isinstance(bundle, SignedConfigBundle)
                else (bundle.get("trust_sequence") if isinstance(bundle, Mapping) else None),
                reason=err.message,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_CANARY,
                desired_version=current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                error=err.message,
                reason=err.code,
                lkg_snapshot=self.store.get_lkg(),
            )

        payload = verified.payload

        # Step 2: Extract and validate all configs
        raw_configs: list[Any] = []
        if "configs" in payload and isinstance(payload["configs"], (list, tuple)):
            raw_configs = list(payload["configs"])
        elif "modules" in payload and isinstance(payload["modules"], (list, tuple)):
            raw_configs = list(payload["modules"])
        elif "module" in payload and "camera_id" in payload:
            raw_configs = [payload]
        else:
            reason = "canary payload contains no recognizable module configurations"
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_CANARY,
                status=STATUS_REJECTED,
                desired_version=current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                trust_sequence=verified.trust_sequence,
                reason=reason,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_CANARY,
                desired_version=current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                error=reason,
                reason="invalid_payload_structure",
                trust_sequence=verified.trust_sequence,
                lkg_snapshot=self.store.get_lkg(),
            )

        parsed_configs: list[CameraModuleConfig] = []
        max_version = 0
        try:
            for item in raw_configs:
                if not isinstance(item, Mapping):
                    raise ConfigError("invalid_config", "each bundle config must be a mapping")
                module = item.get("module")
                camera_id = item.get("camera_id")
                if not module or not camera_id:
                    raise ConfigError("invalid_config", "config requires module and camera_id")
                clean_item = {k: v for k, v in item.items() if k not in CONFIG_METADATA_KEYS}
                parsed_cfg = self.registry.parse(str(module), str(camera_id), clean_item)
                parsed_configs.append(parsed_cfg)
                if parsed_cfg.version > max_version:
                    max_version = parsed_cfg.version
        except Exception as err:
            err_code = getattr(err, "code", "inner_config_validation_failed")
            err_msg = str(err)
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_CANARY,
                status=STATUS_REJECTED,
                desired_version=max_version if max_version > 0 else current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                trust_sequence=verified.trust_sequence,
                reason=err_msg,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_CANARY,
                desired_version=max_version if max_version > 0 else current_state.get("desired_version"),
                observed_version=current_state.get("observed_version"),
                error=err_msg,
                reason=err_code,
                trust_sequence=verified.trust_sequence,
                lkg_snapshot=self.store.get_lkg(),
            )

        # Step 3: Determine canary target scope (cameras / modules)
        canary_val = payload.get("canary")
        canary_spec_data: Mapping[str, Any] = canary_val if isinstance(canary_val, Mapping) else {}
        target_cameras = (
            tuple(canary_cameras)
            if canary_cameras is not None
            else tuple(canary_spec_data.get("cameras", ()))
        )
        target_modules = (
            tuple(canary_modules)
            if canary_modules is not None
            else tuple(canary_spec_data.get("modules", ()))
        )
        max_error_rate = float(canary_spec_data.get("max_error_rate", 0.05))
        observation_period = float(canary_spec_data.get("observation_period_seconds", 60.0))

        # Filter configs that match canary target
        canary_configs: list[CameraModuleConfig] = []
        for cfg in parsed_configs:
            is_match = True
            if target_cameras and cfg.camera_id not in target_cameras:
                is_match = False
            if target_modules and cfg.module not in target_modules:
                is_match = False
            if is_match:
                canary_configs.append(cfg)

        if not canary_configs:
            canary_configs = [parsed_configs[0]]
            target_cameras = (parsed_configs[0].camera_id,)

        # Step 4: Stage and activate ONLY canary configs in registry
        states: list[ActivationState] = []
        for cfg in canary_configs:
            self.registry.stage(cfg)
            state = self.registry.activate(cfg, session_id=session_id)
            states.append(state)

        rejected = [s for s in states if s.status == STATUS_REJECTED]
        if rejected:
            reason = rejected[0].reason or "stale_config_version"
            # Revert registry to previous LKG
            cur_lkg = self.store.get_lkg()
            if cur_lkg:
                self._apply_lkg_to_registry(cur_lkg)
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_CANARY,
                status=STATUS_REJECTED,
                desired_version=max_version,
                observed_version=current_state.get("observed_version"),
                trust_sequence=verified.trust_sequence,
                reason=reason,
            )
            return ActivationResult(
                success=False,
                status=STATUS_REJECTED,
                activation_type=ACTIVATION_TYPE_CANARY,
                desired_version=max_version,
                observed_version=current_state.get("observed_version"),
                error=reason,
                reason=reason,
                trust_sequence=verified.trust_sequence,
                lkg_snapshot=self.store.get_lkg(),
                states=tuple(states),
            )

        # Baseline LKG is preserved in store; canary state is recorded
        baseline_lkg = self.store.get_lkg()
        canary_state_record = {
            "bundle": verified.describe(),
            "canary_cameras": list(target_cameras),
            "canary_modules": list(target_modules),
            "canary_configs": [cfg.describe() for cfg in canary_configs],
            "all_configs": [cfg.describe() for cfg in parsed_configs],
            "max_error_rate": max_error_rate,
            "observation_period_seconds": observation_period,
            "max_version": max_version,
            "session_id": session_id,
            "started_at": current_time,
            "trust_sequence": verified.trust_sequence,
            "baseline_lkg": baseline_lkg,
        }

        self.store.commit_canary(
            canary_state=canary_state_record,
            trust_sequence=verified.trust_sequence,
        )
        self.store.record_audit(
            activation_type=ACTIVATION_TYPE_CANARY,
            status=STATUS_CANARY,
            desired_version=max_version,
            observed_version=current_state.get("observed_version"),
            trust_sequence=verified.trust_sequence,
            canary_spec=canary_state_record,
            reason="canary_staged",
        )

        return ActivationResult(
            success=True,
            status=STATUS_CANARY,
            activation_type=ACTIVATION_TYPE_CANARY,
            desired_version=max_version,
            observed_version=current_state.get("observed_version"),
            trust_sequence=verified.trust_sequence,
            lkg_snapshot=baseline_lkg,
            states=tuple(states),
        )

    def record_canary_observation(
        self,
        *,
        error_rate: float = 0.0,
        is_healthy: bool = True,
        reason: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ActivationResult:
        """Monitor error rate and health status during canary observation.

        If error rate exceeds threshold or health check fails, automatically aborts
        canary and cleanly restores baseline LKG.
        """
        canary_state = self.store.get_canary_state()
        if not canary_state:
            raise ValueError("no active canary deployment to observe")

        max_allowed_error = float(canary_state.get("max_error_rate", 0.05))
        baseline_lkg = canary_state.get("baseline_lkg")
        trust_seq = canary_state.get("trust_sequence")

        if error_rate > max_allowed_error or not is_healthy:
            # Canary health failure: abort canary and restore baseline LKG
            fail_reason = (
                f"error_rate_{error_rate:.3f}_exceeds_threshold_{max_allowed_error:.3f}"
                if error_rate > max_allowed_error
                else (reason or "health_check_failed")
            )
            if baseline_lkg:
                self._apply_lkg_to_registry(baseline_lkg)
            self.store.clear_canary_state()
            self.store.record_audit(
                activation_type=ACTIVATION_TYPE_CANARY,
                status=STATUS_FAILED,
                desired_version=self.get_desired_version(),
                observed_version=self.get_observed_version(),
                trust_sequence=trust_seq,
                reason=f"canary_health_failure: {fail_reason}",
            )
            return ActivationResult(
                success=False,
                status=STATUS_FAILED,
                activation_type=ACTIVATION_TYPE_CANARY,
                desired_version=self.get_desired_version(),
                observed_version=self.get_observed_version(),
                error=fail_reason,
                reason=ERROR_CANARY_FAILURE,
                trust_sequence=trust_seq,
                lkg_snapshot=self.store.get_lkg(),
            )

        # Healthy observation
        return ActivationResult(
            success=True,
            status=STATUS_CANARY,
            activation_type=ACTIVATION_TYPE_CANARY,
            desired_version=self.get_desired_version(),
            observed_version=self.get_observed_version(),
            trust_sequence=trust_seq,
            lkg_snapshot=self.store.get_lkg(),
        )

    def abort_canary(
        self,
        *,
        reason: str = "operator_aborted",
        session_id: Optional[str] = None,
    ) -> ActivationResult:
        """Explicitly abort active canary and restore baseline LKG intact."""
        canary_state = self.store.get_canary_state()
        if not canary_state:
            return ActivationResult(
                success=False,
                status=STATUS_FAILED,
                activation_type=ACTIVATION_TYPE_CANARY,
                desired_version=self.get_desired_version(),
                observed_version=self.get_observed_version(),
                error="no active canary deployment to abort",
                reason="no_active_canary",
                lkg_snapshot=self.store.get_lkg(),
            )

        baseline_lkg = canary_state.get("baseline_lkg")
        trust_seq = canary_state.get("trust_sequence")
        if baseline_lkg:
            self._apply_lkg_to_registry(baseline_lkg)
        self.store.clear_canary_state()
        self.store.record_audit(
            activation_type=ACTIVATION_TYPE_CANARY,
            status=STATUS_FAILED,
            desired_version=self.get_desired_version(),
            observed_version=self.get_observed_version(),
            trust_sequence=trust_seq,
            reason=f"canary_aborted: {reason}",
        )
        return ActivationResult(
            success=True,
            status=STATUS_ROLLED_BACK,
            activation_type=ACTIVATION_TYPE_CANARY,
            desired_version=self.get_desired_version(),
            observed_version=self.get_observed_version(),
            reason=reason,
            trust_sequence=trust_seq,
            lkg_snapshot=self.store.get_lkg(),
        )

    def promote_canary(
        self,
        *,
        session_id: str,
    ) -> ActivationResult:
        """Promote observed canary bundle to full production across all cameras/modules."""
        canary_state = self.store.get_canary_state()
        if not canary_state:
            raise ValueError("no active canary deployment to promote")

        all_raw_configs = canary_state.get("all_configs", [])
        parsed_configs: list[CameraModuleConfig] = []
        max_version = 0
        for item in all_raw_configs:
            clean_item = {k: v for k, v in item.items() if k not in CONFIG_METADATA_KEYS}
            parsed = self.registry.parse(str(item["module"]), str(item["camera_id"]), clean_item)
            parsed_configs.append(parsed)
            if parsed.version > max_version:
                max_version = parsed.version

        states: list[ActivationState] = []
        for cfg in parsed_configs:
            self.registry.stage(cfg)
            state = self.registry.activate(cfg, session_id=session_id)
            states.append(state)

        # Build full LKG snapshot
        full_lkg, snapshot_hash = self._build_lkg_snapshot(parsed_configs, max_version, session_id)
        trust_seq = canary_state.get("trust_sequence")

        # Commit full activation into store and clear canary state
        self.store.commit_activation(
            desired_version=max_version,
            observed_version=max_version,
            lkg_snapshot=full_lkg,
        )
        self.store.clear_canary_state()
        self.store.record_audit(
            activation_type=ACTIVATION_TYPE_CANARY,
            status=STATUS_ACTIVE,
            desired_version=max_version,
            observed_version=max_version,
            trust_sequence=trust_seq,
            config_hash=snapshot_hash,
            snapshot=full_lkg,
            reason="canary_promoted_to_production",
        )

        return ActivationResult(
            success=True,
            status=STATUS_ACTIVE,
            activation_type=ACTIVATION_TYPE_CANARY,
            desired_version=max_version,
            observed_version=max_version,
            trust_sequence=trust_seq,
            snapshot_hash=snapshot_hash,
            lkg_snapshot=full_lkg,
            states=tuple(states),
        )

    def get_event_provenance(self, module: str, camera_id: str) -> dict[str, Any]:
        """Obtain exact event provenance matching currently observed configuration."""
        state = self.registry.state(module, camera_id)
        cfg = self.registry.config(module, camera_id)
        lkg = self.store.get_lkg()
        snapshot_hash = lkg.get("snapshot_hash") if lkg else None
        observed_version = self.store.get_state().get("observed_version")

        return {
            "module": module,
            "camera_id": camera_id,
            "session_id": state.session_id if state else None,
            "observed_version": observed_version,
            "module_version": cfg.version if cfg else None,
            "config_hash": cfg.config_hash if cfg else None,
            "snapshot_hash": snapshot_hash,
        }

    def close(self) -> None:
        self.store.close()
