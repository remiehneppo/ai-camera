"""Create one synthetic event and send pending edge outbox entries."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID, uuid4
from typing import Any

from apps.edge.outbox import EventOutbox
from domain.event_contract import validate_event


def make_event(device_id: str, camera_id: str, event_id: UUID | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "message_id": str(uuid4()),
        "event_id": str(event_id or uuid4()),
        "revision": 1,
        "device_id": device_id,
        "camera_id": camera_id,
        "stream_session_id": str(uuid4()),
        "pipeline_id": "synthetic-fixture",
        "pipeline_version": "1",
        "origin": "synthetic",
        "event_time": now,
        "produced_at": now,
        "config_version": "synthetic-fixture-v1",
        "model_lineage": [{"role": "synthetic_fixture", "version": "1"}],
        "model_artifact_hash": "unknown_artifact",
        "calibration_version": "uncalibrated",
        "quality_state": "unknown",
        "payload": {"taxonomy": "synthetic_demo", "lifecycle": "candidate", "severity": "low", "score": 0.0},
    }


def _api_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (local_http and os.getenv("ALLOW_INSECURE_LAB") == "1"):
        raise ValueError("API_URL must use HTTPS; loopback HTTP requires ALLOW_INSECURE_LAB=1")
    if not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("API_URL must be an origin without credentials, path, query, or fragment")
    return base_url.rstrip("/") + "/v1/events"


def _validate_receipt(receipt: object, item: dict[str, Any]) -> dict[str, object]:
    event = item["event"]
    expected = {
        "device_id": event["device_id"],
        "event_id": event["event_id"],
        "revision": event["revision"],
        "message_id": item["message_id"],
        "event_hash": item["event_hash"],
        "accepted": True,
        "canonicalization": "canonical-json-python-v1",
    }
    if not isinstance(receipt, dict) or any(receipt.get(key) != value for key, value in expected.items()) or not isinstance(receipt.get("accepted_at"), str):
        raise ValueError("server receipt does not match the pending event")
    return receipt


def deliver_pending(outbox: EventOutbox, base_url: str, token: str) -> int:
    endpoint = _api_url(base_url)
    delivered = 0
    for item in outbox.pending():
        body = json.dumps(item["event"], ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        request = Request(endpoint, data=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Idempotency-Key": item["message_id"]}, method="POST")
        try:
            with urlopen(request, timeout=5, context=ssl.create_default_context()) as response:
                receipt = _validate_receipt(json.load(response), item)
            outbox.record_attempt(item["message_id"])
            outbox.mark_delivered(item["message_id"], receipt)
            delivered += 1
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            outbox.record_attempt(item["message_id"], type(exc).__name__)
            raise
    return delivered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.getenv("EDGE_DB", "data/edge-events.sqlite3"))
    parser.add_argument("--event-id", type=UUID, help="reuse an event UUID for an idempotency demonstration")
    parser.add_argument("--no-send", action="store_true", help="persist the fixture without attempting delivery")
    parser.add_argument("--record-file", help="record a cleared synthetic replay source and finalize its evidence")
    parser.add_argument("--anchor-time", type=float, help="declared source-event-time anchor, not trigger time")
    parser.add_argument("--recorder-root", default="data/recorder")
    args = parser.parse_args()
    if bool(args.record_file) != (args.anchor_time is not None):
        parser.error("--record-file and --anchor-time must be supplied together")
    outbox = EventOutbox(args.db)
    device_id = os.environ["DEVICE_ID"]
    should_enqueue = (
        args.event_id is not None and not outbox.has_revision(device_id, str(args.event_id))
    ) or (args.event_id is None and (args.no_send or not outbox.pending()))
    if should_enqueue:
        event = make_event(device_id, os.getenv("CAMERA_ID", "lab-camera-01"), args.event_id)
        if args.record_file:
            from domain.evidence_contract import make_evidence_request
            event["payload"]["evidence_requests"] = [make_evidence_request(
                str(uuid4()), event["stream_session_id"], "synthetic", args.anchor_time)]
        outbox.enqueue(event)
        print(f"queued event_id={event['event_id']}")
    if args.record_file:
        from apps.edge.evidence import EvidenceLifecycle
        from apps.edge.recorder import FileRecorder
        recorder = FileRecorder(args.recorder_root)
        sessions = {item["session_id"] for item in outbox.evidence_requests()
                    if item["state"] in {"requested", "collecting"}}
        # Pin before writing/pruning; restart retries the same durable intent.
        EvidenceLifecycle(outbox, recorder).reconcile()
        for session in sessions:
            if not recorder.segments(session):
                recorder.record_file(args.record_file, session)
        count = EvidenceLifecycle(outbox, recorder).reconcile( finish_sessions=sessions)
        print(f"evidence_finalized={count['recovered_fulfilled']}")
    if args.no_send:
        print(f"pending={len(outbox.pending())}")
        return 0
    token = os.environ["DEVICE_TOKEN"]
    base_url = os.environ.get("API_URL", "https://localhost:8000")
    try:
        count = deliver_pending(outbox, base_url, token)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"delivery failed: {type(exc).__name__}")
        return 1
    print(f"delivered={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
