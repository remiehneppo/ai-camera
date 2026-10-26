"""Canonical signed configuration bundle contract (Ticket #34).

Pure domain module: pure Python stdlib, no I/O, no SQLite, no external crypto packages.
Deterministic canonical JSON serialization, HMAC-SHA256 signature verification with
pluggable custom signature verifier hook, trusted keyring with role authorization,
target matching, and monotonic high-water mark sequence enforcement.
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
    Tuple,
)

__all__ = [
    "CANONICAL_ENCODING",
    "ERROR_EXPIRED_BUNDLE",
    "ERROR_HASH_MISMATCH",
    "ERROR_INVALID_BUNDLE",
    "ERROR_INVALID_KEY",
    "ERROR_INVALID_SIGNATURE",
    "ERROR_LENGTH_MISMATCH",
    "ERROR_REVOKED_KEY",
    "ERROR_SECRET_FIELD",
    "ERROR_STALE_SEQUENCE",
    "ERROR_TARGET_MISMATCH",
    "ERROR_UNCERTAIN_CLOCK",
    "ERROR_UNKNOWN_KEY",
    "ERROR_UNAUTHORIZED_ROLE",
    "ROLE_CONFIG_SIGNER",
    "SignedConfigBundle",
    "SignedConfigError",
    "TargetSpec",
    "TrustedKey",
    "TrustedKeyRing",
    "canonical_bundle_bytes",
    "canonical_bundle_hash",
    "verify_signed_bundle",
]

CANONICAL_ENCODING: Final[str] = "canonical-json-python-v1"
ROLE_CONFIG_SIGNER: Final[str] = "config_signer"

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
        required_role: str,
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
        if key.role != required_role:
            raise SignedConfigError(
                ERROR_UNAUTHORIZED_ROLE,
                f"key '{key_id}' role '{key.role}' is not authorized for '{required_role}'",
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
    ) -> SignedConfigBundle:
        """Create and sign a SignedConfigBundle from raw payload mapping."""
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
        }


def verify_signed_bundle(
    bundle: SignedConfigBundle | Mapping[str, Any],
    *,
    keyring: TrustedKeyRing,
    high_water_mark: int,
    expected_target: Optional[TargetSpec] = None,
    current_time: Optional[float] = None,
    clock_synchronized: bool = True,
    required_role: str = ROLE_CONFIG_SIGNER,
) -> SignedConfigBundle:
    """Verify signed config bundle against target, crypto, high-water mark, and clock certainty.

    Steps:
      1. Canonical bytes length and SHA-256 of payload.
      2. Target matching against host target.
      3. Trusted key lookup, role authorization, and cryptographic signature.
      4. Monotonic sequence > durable high-water mark.
      5. Clock certainty and expiry check.
    """
    if isinstance(bundle, Mapping):
        try:
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

    return parsed_bundle
