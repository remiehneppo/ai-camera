"""Edge retrieval-command worker (Ticket #32).

The worker is the device side of the retained-evidence retrieval channel. It receives only
closed, validated command payloads (see `domain.retrieval_contract`), records a metadata
acknowledgement before doing any work, and closes the command with an artifact receipt or an
allowlisted failure. A command that is already completed is never executed again, so a
replayed poll cannot duplicate work.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, FrozenSet, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from apps.edge.uploader import validate_server_url
from domain.retrieval_contract import (
    ACK_ARTIFACT,
    ACK_FAILURE,
    ACK_METADATA,
    ERROR_INVALID_COMMAND,
    STATUS_CLAIMED,
    STATUS_COMPLETED,
    SUPPORTED_RETENTION_SCOPES,
    RetrievalError,
    validate_command_payload,
)

logger = logging.getLogger(__name__)

MAX_ACK_ARTIFACT_BYTES = 100 * 1024 * 1024


class EvidenceUnavailable(Exception):
    """The requested clip is not retained (cleaned, released, or never finalized)."""


class RetrievalTransportError(Exception):
    """The retrieval channel could not be reached; the command stays open for the next poll."""


class RetrievalTransport:
    """HTTP device channel: long-poll for commands and acknowledge them."""

    def __init__(
        self,
        server_url: str,
        device_token: str,
        *,
        timeout_seconds: float = 10.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.server_url = validate_server_url(server_url)
        self.device_token = device_token
        self.timeout_seconds = float(timeout_seconds)
        self._opener = opener

    def _request(self, method: str, path: str, payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        url = self.server_url + path
        data = None
        headers = {"Authorization": "Bearer " + self.device_token, "Accept": "application/json"}
        if payload is not None:
            data = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                body = response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            raise RetrievalTransportError("retrieval channel unavailable") from error
        try:
            decoded = json.loads(body) if body else {}
        except ValueError as error:
            raise RetrievalTransportError("retrieval channel returned non-JSON") from error
        if not isinstance(decoded, dict):
            raise RetrievalTransportError("retrieval channel returned an unexpected document")
        return decoded

    def poll(self, device_id: str, *, wait_seconds: float = 0.0) -> list[dict[str, Any]]:
        query = urlencode({"wait": max(0.0, float(wait_seconds))})
        document = self._request("GET", f"/v1/devices/{device_id}/commands?{query}")
        commands = document.get("commands", [])
        if not isinstance(commands, list):
            raise RetrievalTransportError("retrieval channel returned malformed commands")
        return commands

    def acknowledge(self, device_id: str, command_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/v1/devices/{device_id}/commands/{command_id}/ack", payload)


class RetrievalWorker:
    """Execute at most one leased command per poll, exactly once per lease."""

    #: Targets this worker can fulfil. A server may address other targets; this one refuses
    #: them with an allowlisted failure instead of running the wrong executor.
    SUPPORTED_TARGETS: FrozenSet[str] = frozenset({"edge"})

    def __init__(
        self,
        transport: RetrievalTransport,
        executor: Callable[[dict[str, Any]], Mapping[str, Any]],
        *,
        device_id: str,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.transport = transport
        self.executor = executor
        self.device_id = device_id
        self._now = now

    def poll_once(self, *, wait_seconds: float = 0.0) -> Optional[dict[str, Any]]:
        commands = self.transport.poll(self.device_id, wait_seconds=wait_seconds)
        for raw in commands:
            outcome = self._handle(raw)
            if outcome is not None:
                return outcome
        return None

    def _refusal(self, command: Mapping[str, Any]) -> Optional[str]:
        if command["target"] not in self.SUPPORTED_TARGETS:
            return "unsupported_target"
        if command["retention_scope"] not in SUPPORTED_RETENTION_SCOPES:
            return "retention_scope_unsupported"
        return None

    def _handle(self, raw: Any) -> Optional[dict[str, Any]]:
        command = validate_command_payload(raw)
        command_id = command["command_id"]
        if command["device_id"] != self.device_id:
            raise RetrievalError(ERROR_INVALID_COMMAND, "command targets another device")
        if command["status"] == STATUS_COMPLETED:
            return {"command_id": command_id, "skipped": "already_completed"}
        if command["status"] != STATUS_CLAIMED or not command.get("lease_id"):
            return {"command_id": command_id, "skipped": "not_leased"}
        if self._now() >= command["expires_at"]:
            return {"command_id": command_id, "skipped": "expired"}
        lease = {"lease_id": command["lease_id"]}

        refusal = self._refusal(command)
        if refusal is not None:
            self.transport.acknowledge(self.device_id, command_id, {**lease, "kind": ACK_FAILURE, "reason": refusal})
            return {"command_id": command_id, "status": "failed", "reason": refusal}

        self.transport.acknowledge(self.device_id, command_id, {**lease, "kind": ACK_METADATA})
        try:
            artifact = dict(self.executor(command))
        except EvidenceUnavailable:
            self.transport.acknowledge(
                self.device_id, command_id, {**lease, "kind": ACK_FAILURE, "reason": "evidence_unavailable"}
            )
            return {"command_id": command_id, "status": "failed", "reason": "evidence_unavailable"}
        except Exception:
            logger.exception("retrieval executor failed for command %s", command_id)
            self.transport.acknowledge(
                self.device_id, command_id, {**lease, "kind": ACK_FAILURE, "reason": "recorder_unavailable"}
            )
            return {"command_id": command_id, "status": "failed", "reason": "recorder_unavailable"}
        view = self.transport.acknowledge(self.device_id, command_id, {**lease, "kind": ACK_ARTIFACT, **artifact})
        return {"command_id": command_id, "status": "completed", "artifact": artifact, "view": view}


class RecorderClipRetainer:
    """Edge-target executor over the independent recorder's pinned clip.

    `finalize_pin` is idempotent per request id, so a retried lease reconciles the same
    artifact instead of producing a second one.
    """

    def __init__(self, recorder: Any) -> None:
        self.recorder = recorder

    def __call__(self, command: Mapping[str, Any]) -> dict[str, Any]:
        request_id = str(command["evidence"]["request_id"])
        try:
            receipt = self.recorder.finalize_pin(request_id)
        except (KeyError, ValueError) as error:
            # A missing or released pin means the clip is not retained any more.
            raise EvidenceUnavailable("pinned clip is not available") from error
        artifact = dict((receipt or {}).get("artifact") or {})
        sha256 = artifact.get("sha256")
        size_bytes = artifact.get("size_bytes")
        if not isinstance(sha256, str) or len(sha256) != 64 or not isinstance(size_bytes, int):
            raise EvidenceUnavailable("finalized clip has no verifiable artifact")
        if size_bytes > MAX_ACK_ARTIFACT_BYTES:
            raise EvidenceUnavailable("finalized clip exceeds the acknowledged size bound")
        receipt_ranges = (receipt or {}).get("actual_ranges")
        result: dict[str, Any] = {"sha256": sha256.lower(), "size_bytes": size_bytes}
        if isinstance(receipt_ranges, list):
            result["actual_ranges"] = receipt_ranges
        return result
