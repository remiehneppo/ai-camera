"""Canonical signed configuration bundle contract (Tickets #34, #35).

Pure domain module: pure Python stdlib, no I/O, no SQLite, no external crypto packages.
Deterministic canonical JSON serialization, HMAC-SHA256 signature verification with
pluggable custom signature verifier hook, trusted keyring with role authorization,
target matching, monotonic high-water mark sequence enforcement, canary deployment,
and authorized rollback verification.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, replace
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    Optional,
    Pattern,
    Sequence,
    Tuple,
)

__all__ = [
    "CANONICAL_ENCODING",
    "CanarySpec",
    "CompatibilityPolicy",
    "ERROR_CANARY_FAILURE",
    "ERROR_EXPIRED_BUNDLE",
    "ERROR_HASH_MISMATCH",
    "ERROR_INCOMPATIBLE_LINEAGE",
    "ERROR_INVALID_BUNDLE",
    "ERROR_INVALID_KEY",
    "ERROR_INVALID_ROLLBACK",
    "ERROR_INVALID_SIGNATURE",
    "ERROR_LENGTH_MISMATCH",
    "ERROR_REVOKED_KEY",
    "ERROR_SECRET_FIELD",
    "ERROR_STALE_SEQUENCE",
    "ERROR_TARGET_MISMATCH",
    "ERROR_UNCERTAIN_CLOCK",
    "ERROR_UNKNOWN_KEY",
    "ERROR_UNAUTHORIZED_ROLE",
    "ROLE_CONFIG_ROLLBACK",
    "ROLE_CONFIG_SIGNER",
    "SignedConfigBundle",
    "SignedConfigError",
    "TargetSpec",
    "TrustedKey",
    "TrustedKeyRing",
    "canonical_bundle_bytes",
    "canonical_bundle_hash",
    "create_canary_bundle",
    "create_rollback_bundle",
    "is_rollback_bundle",
    "verify_signed_bundle",
]

CANONICAL_ENCODING: Final[str] = "canonical-json-python-v1"
ROLE_CONFIG_SIGNER: Final[str] = "config_signer"
ROLE_CONFIG_ROLLBACK: Final[str] = "config_rollback"

ERROR_INVALID_BUNDLE: Final[str] = "invalid_bundle"
ERROR_INVALID_KEY: Final[str] = "invalid_key"
ERROR_LENGTH_MISMATCH: Final[str] = "length_mismatch"
ERROR_HASH_MISMATCH: Final[str] = "hash_mismatch"
ERROR_TARGET_MISMATCH: Final[str] = "target_mismatch"
ERROR_UNKNOWN_KEY: Final[str] = "unknown_key"
ERROR_REVOKED_KEY: Final[str] = "revoked_key"
ERROR_UNAUTHORIZED_ROLE: Final[str] = "unauthorized_role"
ERROR_INVALID_SIGNATURE: Final[str] = "invalid_signature"
ERROR_STALE_SEQUENCE: Final[str] = "stale_trust_sequence"
ERROR_EXPIRED_BUNDLE: Final[str] = "expired_bundle"
ERROR_UNCERTAIN_CLOCK: Final[str] = "uncertain_clock"
ERROR_SECRET_FIELD: Final[str] = "secret_field_not_allowed"
ERROR_INVALID_ROLLBACK: Final[str] = "invalid_rollback"
ERROR_INCOMPATIBLE_LINEAGE: Final[str] = "incompatible_lineage"
ERROR_CANARY_FAILURE: Final[str] = "canary_failure"

_IDENTIFIER: Final[Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_SECRET_KEY: Final[Pattern[str]] = re.compile(
    r"secret|token|passw|credential|api[_-]?key|private[_-]?key|bearer|signature",
    re.IGNORECASE,
)


class SignedConfigError(ValueError):
    """Typed error for signed config verification and canonicalization failures.

    Never echoes secret values: messages name offending fields or codes without value exposure.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: Optional[str] = None,
        key_id: Optional[str] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.field = field
        self.key_id = key_id
        context = ", ".join(
            f"{name}={val}"
            for name, val in (("field", field), ("key_id", key_id))
            if val is not None
        )
        super().__init__(f"{code}: {message}" + (f" [{context}]" if context else ""))

    def describe(self) -> dict[str, Optional[str]]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "key_id": self.key_id,
        }


def _secret_keys(payload: Any) -> Tuple[str, ...]:
    found: list[str] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_str = str(key)
            # 'signature' at bundle metadata level is allowed, but secret fields in config payloads are forbidden
            if _SECRET_KEY.search(key_str):
                found.append(key_str)
            elif isinstance(value, (Mapping, list, tuple)):
                found.extend(_secret_keys(value))
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            found.extend(_secret_keys(item))
    return tuple(sorted(set(found)))


def canonical_bundle_bytes(payload: Any) -> bytes:
    """Deterministic canonical JSON serialization for config bundles.

    UTF-8, sorted keys, compact separators (',', ':'), no NaN/Infinity.
    """
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as err:
        raise SignedConfigError(
            ERROR_INVALID_BUNDLE, f"cannot serialize canonical bundle payload: {err}"
        ) from err


def canonical_bundle_hash(payload: Any) -> str:
    """Hex SHA-256 digest of canonical bundle payload bytes."""
    return hashlib.sha256(canonical_bundle_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class CanarySpec:
    """Specification for canary rollout and observation on a subset of cameras or modules."""

    cameras: Tuple[str, ...] = ()
    modules: Tuple[str, ...] = ()
    max_error_rate: float = 0.05
    observation_period_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not isinstance(self.cameras, (tuple, list)):
            raise SignedConfigError(ERROR_INVALID_BUNDLE, "canary cameras must be a list or tuple of strings")
        if not isinstance(self.modules, (tuple, list)):
            raise SignedConfigError(ERROR_INVALID_BUNDLE, "canary modules must be a list or tuple of strings")
        if type(self.max_error_rate) not in (int, float) or not (0.0 <= self.max_error_rate <= 1.0):
            raise SignedConfigError(ERROR_INVALID_BUNDLE, "canary max_error_rate must be between 0.0 and 1.0")
        if type(self.observation_period_seconds) not in (int, float) or self.observation_period_seconds < 0.0:
            raise SignedConfigError(ERROR_INVALID_BUNDLE, "canary observation_period_seconds must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cameras": list(self.cameras),
            "modules": list(self.modules),
            "max_error_rate": self.max_error_rate,
            "observation_period_seconds": self.observation_period_seconds,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CanarySpec:
        return cls(
            cameras=tuple(str(c) for c in data.get("cameras", ())),
            modules=tuple(str(m) for m in data.get("modules", ())),
            max_error_rate=float(data.get("max_error_rate", 0.05)),
            observation_period_seconds=float(data.get("observation_period_seconds", 60.0)),
        )


@dataclass(frozen=True)
class CompatibilityPolicy:
    """Compatibility and lineage rules for safe activations and rollbacks.

    Ensures no silent mixing of incompatible schema versions, unapproved factories,
    or incompatible model/config lineages across rollbacks and deployments.
    """

    allowed_schema_versions: Tuple[str, ...] = ()
    allowed_factories: Tuple[str, ...] = ()
    allowed_lineages: Tuple[str, ...] = ()
    lineage_compatibility_matrix: Optional[Mapping[str, Tuple[str, ...]]] = None

    def validate_bundle(
        self,
        payload: Mapping[str, Any],
        *,
        current_lkg: Optional[Mapping[str, Any]] = None,
        is_rollback: bool = False,
    ) -> None:
        """Validate payload against schema versions, factory allowlist, and lineage continuity."""
        # 1. Payload-level schema version check
        payload_schema = payload.get("schema_version")
        if payload_schema is not None and self.allowed_schema_versions:
            if str(payload_schema) not in self.allowed_schema_versions:
                raise SignedConfigError(
                    ERROR_INCOMPATIBLE_LINEAGE,
                    f"payload schema_version '{payload_schema}' not in allowed schema versions: {self.allowed_schema_versions}",
                    field="schema_version",
                )

        # 2. Payload-level model lineage check
        payload_lineage = payload.get("model_lineage") or payload.get("lineage")
        if payload_lineage is not None and self.allowed_lineages:
            if str(payload_lineage) not in self.allowed_lineages:
                raise SignedConfigError(
                    ERROR_INCOMPATIBLE_LINEAGE,
                    f"payload lineage '{payload_lineage}' not in allowed lineages: {self.allowed_lineages}",
                    field="model_lineage",
                )

        # 3. Extract config items
        configs: list[Any] = []
        if "configs" in payload and isinstance(payload["configs"], (list, tuple)):
            configs = list(payload["configs"])
        elif "target_lkg" in payload and isinstance(payload["target_lkg"], Mapping):
            tl = payload["target_lkg"]
            if "configs" in tl and isinstance(tl["configs"], (list, tuple)):
                configs = list(tl["configs"])
        elif "modules" in payload and isinstance(payload["modules"], (list, tuple)):
            configs = list(payload["modules"])
        elif "module" in payload and "camera_id" in payload:
            configs = [payload]

        lineages_in_bundle: set[str] = set()
        if payload_lineage is not None:
            lineages_in_bundle.add(str(payload_lineage))

        for cfg in configs:
            if not isinstance(cfg, Mapping):
                continue
            # Check config-level schema version
            cfg_schema = cfg.get("schema_version") or cfg.get("config_version")
            if cfg_schema is not None and self.allowed_schema_versions:
                if str(cfg_schema) not in self.allowed_schema_versions:
                    raise SignedConfigError(
                        ERROR_INCOMPATIBLE_LINEAGE,
                        f"config schema_version '{cfg_schema}' for module '{cfg.get('module')}' not in allowed schema versions: {self.allowed_schema_versions}",
                        field="schema_version",
                    )
            # Check factory allowlist
            factory = cfg.get("factory")
            if factory is not None and self.allowed_factories:
                if str(factory) not in self.allowed_factories:
                    raise SignedConfigError(
                        ERROR_INCOMPATIBLE_LINEAGE,
                        f"factory '{factory}' for module '{cfg.get('module')}' not in factory allowlist: {self.allowed_factories}",
                        field="factory",
                    )
            # Check config lineage
            cfg_lineage = cfg.get("model_lineage") or cfg.get("lineage")
            if cfg_lineage is not None:
                str_lin = str(cfg_lineage)
                lineages_in_bundle.add(str_lin)
                if self.allowed_lineages and str_lin not in self.allowed_lineages:
                    raise SignedConfigError(
                        ERROR_INCOMPATIBLE_LINEAGE,
                        f"config lineage '{str_lin}' for module '{cfg.get('module')}' not in allowed lineages: {self.allowed_lineages}",
                        field="model_lineage",
                    )

        # 4. Prevent silent mixing of incompatible lineages within the same bundle
        if len(lineages_in_bundle) > 1 and self.lineage_compatibility_matrix:
            for l1 in lineages_in_bundle:
                allowed_compat = self.lineage_compatibility_matrix.get(l1, (l1,))
                for l2 in lineages_in_bundle:
                    if l2 not in allowed_compat:
                        raise SignedConfigError(
                            ERROR_INCOMPATIBLE_LINEAGE,
                            f"conflicting model lineages in bundle: '{l1}' and '{l2}' are incompatible",
                            field="model_lineage",
                        )

        # 5. On rollback: verify lineage transition compatibility against current LKG
        if is_rollback and current_lkg and self.lineage_compatibility_matrix:
            current_lineage = current_lkg.get("model_lineage") or current_lkg.get("lineage")
            if not current_lineage and "provenance" in current_lkg and isinstance(current_lkg["provenance"], Mapping):
                for prov in current_lkg["provenance"].values():
                    if isinstance(prov, Mapping) and "model_lineage" in prov:
                        current_lineage = prov["model_lineage"]
                        break
            if current_lineage:
                str_cur = str(current_lineage)
                compat_targets = self.lineage_compatibility_matrix.get(str_cur, (str_cur,))
                for target_lin in lineages_in_bundle:
                    if target_lin not in compat_targets:
                        raise SignedConfigError(
                            ERROR_INCOMPATIBLE_LINEAGE,
                            f"cannot rollback from lineage '{str_cur}' to incompatible target lineage '{target_lin}'",
                            field="model_lineage",
                        )


def is_rollback_bundle(payload: Mapping[str, Any]) -> bool:
    """Check if a bundle payload represents an authorized rollback."""
    return (
        payload.get("action") == "rollback"
        or "rollback_for_sequence" in payload
        or "target_lkg" in payload
    )


@dataclass(frozen=True)
class TargetSpec:
    """Target eligibility specification for signed config bundle deployment."""

    device_id: Optional[str] = None
    site_id: Optional[str] = None
    profile: Optional[str] = None

    def matches(self, expected: TargetSpec) -> Tuple[bool, Optional[str]]:
        """Verify whether this target specification matches the expected host environment.

        If a target field is specified on the bundle, the host must match it.
        """
        if self.device_id is not None:
            if expected.device_id is None or self.device_id != expected.device_id:
                return (
                    False,
                    f"target_device_id mismatch: bundle requires '{self.device_id}', host is '{expected.device_id}'",
                )
        if self.site_id is not None:
            if expected.site_id is None or self.site_id != expected.site_id:
                return (
                    False,
                    f"target_site_id mismatch: bundle requires '{self.site_id}', host is '{expected.site_id}'",
                )
        if self.profile is not None:
            if expected.profile is None or self.profile != expected.profile:
                return (
                    False,
                    f"target_profile mismatch: bundle requires '{self.profile}', host is '{expected.profile}'",
                )
        return True, None


@dataclass(frozen=True)
class TrustedKey:
    """Cryptographic signing key with role allowlisting, rotation/revocation, and verification."""

    key_id: str
    role: str
    secret: bytes | str
    revoked: bool = False
    expires_at: Optional[float] = None
    custom_verifier: Optional[Callable[[bytes, str, TrustedKey], bool]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.key_id, str) or not _IDENTIFIER.match(self.key_id):
            raise SignedConfigError(
                ERROR_INVALID_KEY, "key_id must be a safe non-empty identifier", key_id=str(self.key_id)
            )
        if not isinstance(self.role, str) or not self.role.strip():
            raise SignedConfigError(
                ERROR_INVALID_KEY, "key role must be a non-empty string", key_id=self.key_id
            )
        if not isinstance(self.secret, (bytes, str)) or not self.secret:
            raise SignedConfigError(
                ERROR_INVALID_KEY, "key secret must be non-empty bytes or string", key_id=self.key_id
            )

    @property
    def secret_bytes(self) -> bytes:
        if isinstance(self.secret, bytes):
            return self.secret
        return self.secret.encode("utf-8")

    def sign(self, payload_bytes: bytes) -> str:
        """Create HMAC-SHA256 signature for given payload bytes."""
        return hmac.new(self.secret_bytes, payload_bytes, hashlib.sha256).hexdigest()

    def verify_signature(self, payload_bytes: bytes, signature: str) -> bool:
        """Verify signature using custom verifier hook if configured, or stdlib HMAC-SHA256."""
        if self.custom_verifier is not None:
            return self.custom_verifier(payload_bytes, signature, self)
        expected = self.sign(payload_bytes)
        return hmac.compare_digest(expected, signature)


class TrustedKeyRing:
    """Keyring managing active, rotated, and revoked signing keys with role authorization."""

    def __init__(self, keys: Optional[Iterable[TrustedKey]] = None) -> None:
        self._keys: dict[str, TrustedKey] = {}
        if keys:
            for k in keys:
                self.add_key(k)

    def add_key(self, key: TrustedKey) -> None:
        self._keys[key.key_id] = key

    def get_key(self, key_id: str) -> Optional[TrustedKey]:
        return self._keys.get(key_id)

    def revoke_key(self, key_id: str) -> None:
        if key_id not in self._keys:
            raise SignedConfigError(ERROR_UNKNOWN_KEY, f"key '{key_id}' not found in keyring", key_id=key_id)
        self._keys[key_id] = replace(self._keys[key_id], revoked=True)

    def verify(
        self,
        key_id: str,
        required_role: str | Iterable[str],
        payload_bytes: bytes,
        signature: str,
        current_time: Optional[float] = None,
    ) -> TrustedKey:
        """Validate key presence, revocation status, role allowlist, and cryptographic signature."""
        key = self.get_key(key_id)
        if key is None:
            raise SignedConfigError(ERROR_UNKNOWN_KEY, f"unknown trusted key id '{key_id}'", key_id=key_id)
        if key.revoked:
            raise SignedConfigError(ERROR_REVOKED_KEY, f"key '{key_id}' has been revoked", key_id=key_id)
        if key.expires_at is not None and current_time is not None and current_time > key.expires_at:
            raise SignedConfigError(
                ERROR_REVOKED_KEY, f"key '{key_id}' expired at {key.expires_at}", key_id=key_id
            )

        allowed_roles: Tuple[str, ...]
        if isinstance(required_role, str):
            allowed_roles = (required_role,)
        else:
            allowed_roles = tuple(required_role)

        if key.role not in allowed_roles:
            role_desc = f"'{required_role}'" if isinstance(required_role, str) else ", ".join(f"'{r}'" for r in allowed_roles)
            raise SignedConfigError(
                ERROR_UNAUTHORIZED_ROLE,
                f"key '{key_id}' role '{key.role}' is not authorized for {role_desc}",
                key_id=key_id,
            )
        if not key.verify_signature(payload_bytes, signature):
            raise SignedConfigError(
                ERROR_INVALID_SIGNATURE, "cryptographic signature verification failed", key_id=key_id
            )
        return key


@dataclass(frozen=True)
class SignedConfigBundle:
    """Cryptographically signed configuration bundle with target constraints and trust sequence."""

    payload: Mapping[str, Any]
    length: int
    sha256: str
    key_id: str
    signature: str
    trust_sequence: int
    expires_at: float
    target_device_id: Optional[str] = None
    target_site_id: Optional[str] = None
    target_profile: Optional[str] = None
    bundle_id: Optional[str] = None
    canary_spec: Optional[CanarySpec] = None

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise SignedConfigError(ERROR_INVALID_BUNDLE, "bundle payload must be a mapping")
        if type(self.length) is not int or self.length <= 0:
            raise SignedConfigError(ERROR_INVALID_BUNDLE, "bundle length must be a positive integer")
        if not isinstance(self.sha256, str) or len(self.sha256) != 64:
            raise SignedConfigError(ERROR_INVALID_BUNDLE, "bundle sha256 must be a 64-char hex string")
        if not isinstance(self.key_id, str) or not self.key_id:
            raise SignedConfigError(ERROR_INVALID_BUNDLE, "bundle key_id must be a non-empty string")
        if not isinstance(self.signature, str) or not self.signature:
            raise SignedConfigError(ERROR_INVALID_BUNDLE, "bundle signature must be a non-empty string")
        if type(self.trust_sequence) is not int or self.trust_sequence <= 0:
            raise SignedConfigError(ERROR_INVALID_BUNDLE, "trust_sequence must be a positive integer")
        if type(self.expires_at) not in (int, float) or self.expires_at <= 0:
            raise SignedConfigError(ERROR_INVALID_BUNDLE, "expires_at must be a positive timestamp")

    @classmethod
    def create(
        cls,
        payload: Mapping[str, Any],
        key: TrustedKey,
        trust_sequence: int,
        expires_at: float,
        *,
        target_device_id: Optional[str] = None,
        target_site_id: Optional[str] = None,
        target_profile: Optional[str] = None,
        bundle_id: Optional[str] = None,
        canary_spec: Optional[CanarySpec] = None,
    ) -> SignedConfigBundle:
        """Create and sign a SignedConfigBundle from raw payload mapping."""
        # Auto-detect canary_spec if not explicitly passed
        if canary_spec is None and "canary" in payload and isinstance(payload["canary"], Mapping):
            canary_spec = CanarySpec.from_dict(payload["canary"])

        canonical = canonical_bundle_bytes(payload)
        length = len(canonical)
        digest = hashlib.sha256(canonical).hexdigest()
        sig = key.sign(canonical)
        return cls(
            payload=payload,
            length=length,
            sha256=digest,
            key_id=key.key_id,
            signature=sig,
            trust_sequence=trust_sequence,
            expires_at=float(expires_at),
            target_device_id=target_device_id,
            target_site_id=target_site_id,
            target_profile=target_profile,
            bundle_id=bundle_id,
            canary_spec=canary_spec,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "payload": dict(self.payload),
            "length": self.length,
            "sha256": self.sha256,
            "key_id": self.key_id,
            "signature": self.signature,
            "trust_sequence": self.trust_sequence,
            "expires_at": self.expires_at,
            "target_device_id": self.target_device_id,
            "target_site_id": self.target_site_id,
            "target_profile": self.target_profile,
            "bundle_id": self.bundle_id,
            "canary_spec": self.canary_spec.to_dict() if self.canary_spec else None,
        }


def create_rollback_bundle(
    *,
    configs: Sequence[Mapping[str, Any]],
    key: TrustedKey,
    trust_sequence: int,
    expires_at: float,
    rollback_for_sequence: Optional[int] = None,
    target_device_id: Optional[str] = None,
    target_site_id: Optional[str] = None,
    target_profile: Optional[str] = None,
    bundle_id: Optional[str] = None,
    schema_version: Optional[str] = None,
    model_lineage: Optional[str] = None,
    extra_payload: Optional[Mapping[str, Any]] = None,
) -> SignedConfigBundle:
    """Create a signed bundle specifically formatted for authorized rollback."""
    payload: dict[str, Any] = {
        "action": "rollback",
        "configs": list(configs),
    }
    if rollback_for_sequence is not None:
        payload["rollback_for_sequence"] = rollback_for_sequence
    if schema_version is not None:
        payload["schema_version"] = schema_version
    if model_lineage is not None:
        payload["model_lineage"] = model_lineage
    if extra_payload:
        for k, v in extra_payload.items():
            if k not in payload:
                payload[k] = v

    return SignedConfigBundle.create(
        payload=payload,
        key=key,
        trust_sequence=trust_sequence,
        expires_at=expires_at,
        target_device_id=target_device_id,
        target_site_id=target_site_id,
        target_profile=target_profile,
        bundle_id=bundle_id,
    )


def create_canary_bundle(
    *,
    configs: Sequence[Mapping[str, Any]],
    key: TrustedKey,
    trust_sequence: int,
    expires_at: float,
    canary_cameras: Sequence[str] = (),
    canary_modules: Sequence[str] = (),
    max_error_rate: float = 0.05,
    observation_period_seconds: float = 60.0,
    target_device_id: Optional[str] = None,
    target_site_id: Optional[str] = None,
    target_profile: Optional[str] = None,
    bundle_id: Optional[str] = None,
    schema_version: Optional[str] = None,
    model_lineage: Optional[str] = None,
    extra_payload: Optional[Mapping[str, Any]] = None,
) -> SignedConfigBundle:
    """Create a signed bundle configured for canary deployment."""
    canary_dict = {
        "cameras": list(canary_cameras),
        "modules": list(canary_modules),
        "max_error_rate": max_error_rate,
        "observation_period_seconds": observation_period_seconds,
    }
    payload: dict[str, Any] = {
        "canary": canary_dict,
        "configs": list(configs),
    }
    if schema_version is not None:
        payload["schema_version"] = schema_version
    if model_lineage is not None:
        payload["model_lineage"] = model_lineage
    if extra_payload:
        for k, v in extra_payload.items():
            if k not in payload:
                payload[k] = v

    return SignedConfigBundle.create(
        payload=payload,
        key=key,
        trust_sequence=trust_sequence,
        expires_at=expires_at,
        target_device_id=target_device_id,
        target_site_id=target_site_id,
        target_profile=target_profile,
        bundle_id=bundle_id,
    )


def verify_signed_bundle(
    bundle: SignedConfigBundle | Mapping[str, Any],
    *,
    keyring: TrustedKeyRing,
    high_water_mark: int,
    expected_target: Optional[TargetSpec] = None,
    current_time: Optional[float] = None,
    clock_synchronized: bool = True,
    required_role: str | Iterable[str] = ROLE_CONFIG_SIGNER,
    compatibility_policy: Optional[CompatibilityPolicy] = None,
    current_lkg: Optional[Mapping[str, Any]] = None,
) -> SignedConfigBundle:
    """Verify signed config bundle against target, crypto, high-water mark, and clock certainty.

    Steps:
      1. Canonical bytes length and SHA-256 of payload.
      2. Target matching against host target.
      3. Trusted key lookup, role authorization, and cryptographic signature.
      4. Monotonic sequence > durable high-water mark.
      5. Clock certainty and expiry check.
      6. Compatibility policy verification (if configured).
    """
    if isinstance(bundle, Mapping):
        try:
            canary_spec = None
            if "canary_spec" in bundle and isinstance(bundle["canary_spec"], Mapping):
                canary_spec = CanarySpec.from_dict(bundle["canary_spec"])
            elif "payload" in bundle and isinstance(bundle["payload"], Mapping) and "canary" in bundle["payload"] and isinstance(bundle["payload"]["canary"], Mapping):
                canary_spec = CanarySpec.from_dict(bundle["payload"]["canary"])

            parsed_bundle = SignedConfigBundle(
                payload=bundle["payload"],
                length=bundle["length"],
                sha256=bundle["sha256"],
                key_id=bundle["key_id"],
                signature=bundle["signature"],
                trust_sequence=bundle["trust_sequence"],
                expires_at=bundle["expires_at"],
                target_device_id=bundle.get("target_device_id"),
                target_site_id=bundle.get("target_site_id"),
                target_profile=bundle.get("target_profile"),
                bundle_id=bundle.get("bundle_id"),
                canary_spec=canary_spec,
            )
        except (KeyError, TypeError) as err:
            raise SignedConfigError(ERROR_INVALID_BUNDLE, f"missing required bundle field: {err}") from err
    elif isinstance(bundle, SignedConfigBundle):
        parsed_bundle = bundle
    else:
        raise SignedConfigError(ERROR_INVALID_BUNDLE, "bundle must be SignedConfigBundle or Mapping")

    # Step 1: Canonical payload bytes length and SHA-256
    canonical = canonical_bundle_bytes(parsed_bundle.payload)
    if len(canonical) != parsed_bundle.length:
        raise SignedConfigError(
            ERROR_LENGTH_MISMATCH,
            f"declared length {parsed_bundle.length} does not match canonical payload length {len(canonical)}",
        )
    computed_digest = hashlib.sha256(canonical).hexdigest()
    if not hmac.compare_digest(computed_digest.lower(), parsed_bundle.sha256.lower()):
        raise SignedConfigError(
            ERROR_HASH_MISMATCH,
            f"declared sha256 {parsed_bundle.sha256} does not match computed sha256 {computed_digest}",
        )

    # Payload secret check: never echo secret values
    forbidden_secrets = _secret_keys(parsed_bundle.payload)
    if forbidden_secrets:
        raise SignedConfigError(
            ERROR_SECRET_FIELD,
            "configuration payload must not carry secret material",
            field=forbidden_secrets[0],
        )

    # Step 2: Target matching
    if expected_target is not None:
        bundle_target = TargetSpec(
            device_id=parsed_bundle.target_device_id,
            site_id=parsed_bundle.target_site_id,
            profile=parsed_bundle.target_profile,
        )
        ok, reason = bundle_target.matches(expected_target)
        if not ok:
            raise SignedConfigError(ERROR_TARGET_MISMATCH, reason or "target mismatch")

    # Step 3: Key ID, role authorization, and signature
    keyring.verify(
        key_id=parsed_bundle.key_id,
        required_role=required_role,
        payload_bytes=canonical,
        signature=parsed_bundle.signature,
        current_time=current_time if clock_synchronized else None,
    )

    # Step 4: Monotonic sequence > durable high-water mark
    if parsed_bundle.trust_sequence <= high_water_mark:
        raise SignedConfigError(
            ERROR_STALE_SEQUENCE,
            f"bundle trust sequence {parsed_bundle.trust_sequence} <= high water mark {high_water_mark}",
        )

    # Step 5: Clock certainty and expiry check
    if not clock_synchronized:
        raise SignedConfigError(
            ERROR_UNCERTAIN_CLOCK,
            "clock is not synchronized; remote signed activation rejected",
        )
    if current_time is not None and current_time > parsed_bundle.expires_at:
        raise SignedConfigError(
            ERROR_EXPIRED_BUNDLE,
            f"bundle expired at {parsed_bundle.expires_at}, current time is {current_time}",
        )

    # Step 6: Compatibility and Lineage Policy validation
    if compatibility_policy is not None:
        compatibility_policy.validate_bundle(
            parsed_bundle.payload,
            current_lkg=current_lkg,
            is_rollback=is_rollback_bundle(parsed_bundle.payload),
        )

    return parsed_bundle
