"""Edge evidence uploader client and outbox reconciliation."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import ssl
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from apps.edge.outbox import EventOutbox
from apps.edge.recorder import FileRecorder

logger = logging.getLogger(__name__)


def _validate_server_url(server_url: str) -> str:
    parsed = urlparse(server_url)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not local_http:
        raise ValueError("server_url must use HTTPS; loopback HTTP is allowed for testing")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("server_url must be an origin without credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("server_url must not contain a path component")
    return server_url.rstrip("/")


def _validate_receipt(server_receipt: Any, artifact: dict[str, Any], request_id: str) -> dict[str, Any]:
    if not isinstance(server_receipt, dict):
        raise ValueError("server evidence receipt must be an object")
    expected = {
        "request_id": request_id,
        "sha256": artifact["sha256"],
        "size_bytes": artifact["size_bytes"],
    }
    for key, value in expected.items():
        if server_receipt.get(key) != value:
            raise ValueError(f"receipt field {key}={server_receipt.get(key)!r} does not match expected {value!r}")
    location = server_receipt.get("location")
    if not isinstance(location, str) or not location:
        raise ValueError("receipt location must be a non-empty string")
    return server_receipt


def _calculate_file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reconcile_and_cleanup(outbox, recorder):
    from apps.edge.evidence import EvidenceLifecycle
    return EvidenceLifecycle(outbox, recorder).reconcile()


class UploadPayloadTooLarge(ValueError):
    """Server/proxy answered HTTP 413; retrying the same artifact cannot succeed."""


class EdgeUploader:
    """Client for uploading finalized edge evidence clips to the server."""

    def __init__(
        self,
        outbox: EventOutbox | str | Path,
        recorder: FileRecorder | str | Path,
        server_url: str,
        device_token: str,
        *,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        sleep_fn: Any = None,
    ) -> None:
        self.outbox = outbox if isinstance(outbox, EventOutbox) else EventOutbox(outbox)
        self.recorder = recorder if isinstance(recorder, FileRecorder) else FileRecorder(recorder)
        self.server_url = _validate_server_url(server_url)
        if not device_token or not isinstance(device_token, str):
            raise ValueError("device_token must be a non-empty string")
        self.device_token = device_token
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._sleep = sleep_fn if sleep_fn is not None else time.sleep
        self._ssl_context = ssl.create_default_context()

    def transfer(self, endpoint, artifact, headers):
        artifact_path = Path(artifact["path"])
        request_id = endpoint.rsplit("/", 1)[-1]
        # Upload with retry logic
        last_error_str = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0 and self.backoff_base > 0:
                delay = self.backoff_base * (2 ** (attempt - 1))
                self._sleep(delay)

            try:
                with artifact_path.open("rb") as stream:
                    request = Request(endpoint, data=stream, headers=headers, method="PUT")
                    with urlopen(request, timeout=self.timeout_seconds, context=self._ssl_context) as response:
                        response_body = response.read()
                        raw_receipt = json.loads(response_body.decode("utf-8"))
                        server_receipt = _validate_receipt(raw_receipt, artifact, request_id)

                return server_receipt

            except HTTPError as exc:
                last_error_str = f"HTTP {exc.code}: {exc.reason}"
                logger.warning("evidence upload HTTPError %s on attempt %d: %s", request_id, attempt, last_error_str)
                if exc.code == 413:
                    raise UploadPayloadTooLarge(f"upload_413_payload_too_large: {last_error_str}")
                # Retry on 503 Service Unavailable or 429 Too Many Requests or 5xx
                if exc.code in {503, 429, 502, 504} and attempt < self.max_retries:
                    continue
                # Non-retryable error or retries exhausted
                raise ValueError(last_error_str)

            except (URLError, TimeoutError, OSError) as exc:
                last_error_str = f"{type(exc).__name__}: {exc}"
                logger.warning("evidence upload network error %s on attempt %d: %s", request_id, attempt, last_error_str)
                if attempt < self.max_retries:
                    continue
                raise ValueError(last_error_str)

            except ValueError as exc:
                # Receipt verification failed
                last_error_str = f"receipt validation error: {exc}"
                logger.warning("evidence receipt verification failed for %s: %s", request_id, last_error_str)
                raise ValueError(last_error_str)

        if last_error_str:
            raise ValueError(last_error_str)
        return None

    def upload_single_request(self, request_id):
        from apps.edge.evidence import EvidenceLifecycle
        return EvidenceLifecycle(self.outbox, self.recorder, self).upload_single_request(request_id)

    def reconcile_and_cleanup(self):
        return reconcile_and_cleanup(self.outbox, self.recorder)

    def upload_pending(self, batch_size=10, reconcile=False):
        from apps.edge.evidence import EvidenceLifecycle
        return EvidenceLifecycle(self.outbox, self.recorder, self).upload_pending(batch_size, reconcile=reconcile)
