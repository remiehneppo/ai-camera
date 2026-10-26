"""Local & Signed Config Activation with Durable High-Water Mark and LKG (Ticket #34).

Supports two distinct activation paths:
  1. Local config staging & activation at session boundary: fail-fast module x camera validation
     without waiting for trust infrastructure, maintaining LKG and desired/observed versions.
  2. Signed remote bundle staging & activation: cryptographic & target verification against
     durable monotonic high-water mark, inner config validation, atomic advance of high-water mark
     and LKG on success, preserving LKG and observed version on any failure.

Ensures recorder isolation: recorder is never stopped or reset across failed or successful
activations, and emitted event provenance carries exact observed_version snapshot hash.
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
    ROLE_CONFIG_SIGNER,
    SignedConfigBundle,
    SignedConfigError,
    TargetSpec,
    TrustedKeyRing,
    canonical_bundle_bytes,
    canonical_bundle_hash,
    verify_signed_bundle,
)

__all__ = [
    "ActivationResult",
    "ConfigActivationManager",
    "DurableConfigStateStore",
    "RecorderContinuityError",
]

ACTIVATION_TYPE_LOCAL: Final[str] = "local"
ACTIVATION_TYPE_REMOTE: Final[str] = "remote_signed"


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
                    snapshot TEXT
                );
                """
            )
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
                SELECT high_water_mark, desired_version, observed_version, lkg_snapshot, updated_at
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
                    "updated_at": 0.0,
                }
            lkg = json.loads(row[3]) if row[3] else None
            return {
                "high_water_mark": row[0],
                "desired_version": row[1],
                "observed_version": row[2],
                "lkg": lkg,
                "updated_at": row[4],
            }

    def get_lkg(self) -> Optional[dict[str, Any]]:
        state = self.get_state()
        return state.get("lkg")

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
                    SET high_water_mark = ?, desired_version = ?, observed_version = ?, lkg_snapshot = ?, updated_at = ?
                    WHERE id = 1;
                    """,
                    (new_hwm, desired_version, observed_version, lkg_json, time.time()),
                )
                cur.execute("COMMIT;")
            except Exception:
                cur.execute("ROLLBACK;")
                raise

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
    ) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO activation_audit (
                    timestamp, activation_type, desired_version, observed_version,
                    trust_sequence, status, reason, config_hash, snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                ),
            )

    def get_audit_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, timestamp, activation_type, desired_version, observed_version,
                       trust_sequence, status, reason, config_hash, snapshot
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
                }
                for r in rows
            ]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class ConfigActivationManager:
    """Manages local and signed remote config activation with durable HWM, LKG, and recorder isolation."""

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

        # Restore LKG from durable store into registry on cold start / reboot
        self._restore_lkg_if_present()

    def _restore_lkg_if_present(self) -> None:
        lkg = self.store.get_lkg()
        if not lkg or not isinstance(lkg, dict):
            return
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
                # Check if module is registered in our registry
                self.registry.definition(module)
                clean_cfg = {k: v for k, v in cfg_dict.items() if k not in ("module", "camera_id")}
                parsed = self.registry.parse(module, camera_id, clean_cfg)
                self.registry.stage(parsed)
                prov_key = f"{module}:{camera_id}"
                prov = provenance.get(prov_key, {})
                sess_id = prov.get("session_id", "restored-session")
                self.registry.activate(parsed, session_id=sess_id)
            except Exception:
                # If definition is not yet registered or parse fails during restore, ignore
                pass

    def set_recorder(self, recorder: Any) -> None:
        """Attach independent recorder reference."""
        self.recorder = recorder

    def get_high_water_mark(self) -> int:
        return self.store.get_high_water_mark()

    def get_observed_version(self) -> Optional[int]:
        return self.store.get_state().get("observed_version")

    def get_desired_version(self) -> Optional[int]:
        return self.store.get_state().get("desired_version")

    def get_lkg(self) -> Optional[dict[str, Any]]:
        return self.store.get_lkg()

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
                clean_item = {k: v for k, v in item.items() if k not in ("module", "camera_id")}
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
                    clean_item = {k: v for k, v in item.items() if k not in ("module", "camera_id")}
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

        Verifies bundle cryptography, target constraints, monotonic sequence > durable HWM,
        and clock certainty. Validates inner module x camera config before committing.
        On success, atomically advances high-water mark and LKG.
        On failure, preserves previous LKG and observed version.
        Recorder is never interrupted.
        """
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
        payload = verified.payload
        raw_configs: list[Any] = []
        if "configs" in payload and isinstance(payload["configs"], (list, tuple)):
            raw_configs = list(payload["configs"])
        elif "modules" in payload and isinstance(payload["modules"], (list, tuple)):
            raw_configs = list(payload["modules"])
        elif "module" in payload and "camera_id" in payload:
            raw_configs = [payload]
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
                clean_item = {k: v for k, v in item.items() if k not in ("module", "camera_id")}
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
