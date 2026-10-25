"""Ticket #32: edge retrieval worker, executor and transport."""

import io
import json
import unittest
from urllib.error import HTTPError

from apps.edge.retrieval import (
    EvidenceUnavailable,
    RecorderClipRetainer,
    RetrievalTransport,
    RetrievalTransportError,
    RetrievalWorker,
)
from domain.retrieval_contract import (
    ACK_ARTIFACT,
    ACK_FAILURE,
    ACK_METADATA,
    EvidenceRef,
    STATUS_COMPLETED,
    acknowledge,
    claim,
    issue_command,
    wire_payload,
)

SHA = "a" * 64
NOW = 1_000.0


def command_payload(*, ttl=300.0, device_id="lab-edge-01", command_id="cmd-001", now=NOW):
    state = issue_command(
        command_id=command_id,
        device_id=device_id,
        target="edge",
        evidence=EvidenceRef(device_id=device_id, event_id="evt-1", request_id="req-001"),
        issued_by="alice",
        issued_at=NOW,
        ttl_seconds=ttl,
    )
    return wire_payload(claim(state, now=now), now=now)


class FakeTransport:
    def __init__(self, commands):
        self.commands = list(commands)
        self.polls = []
        self.acks = []

    def poll(self, device_id, *, wait_seconds=0.0):
        self.polls.append((device_id, wait_seconds))
        return self.commands

    def acknowledge(self, device_id, command_id, payload):
        self.acks.append((device_id, command_id, dict(payload)))
        return {"command_id": command_id, "status": "completed" if payload["kind"] == ACK_ARTIFACT else "claimed"}


class WorkerTests(unittest.TestCase):
    def worker(self, commands, executor, *, now=NOW):
        self.transport = FakeTransport(commands)
        return RetrievalWorker(self.transport, executor, device_id="lab-edge-01", now=lambda: now)

    def test_happy_path_records_metadata_then_completes_with_the_artifact(self):
        calls = []

        def executor(command):
            calls.append(command["command_id"])
            return {"sha256": SHA, "size_bytes": 4321}

        outcome = self.worker([command_payload()], executor).poll_once()
        self.assertEqual(calls, ["cmd-001"])
        self.assertEqual([ack[2]["kind"] for ack in self.transport.acks], [ACK_METADATA, ACK_ARTIFACT])
        self.assertEqual(self.transport.acks[0][2], {"lease_id": self.transport.acks[0][2]["lease_id"], "kind": ACK_METADATA})
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(outcome["artifact"], {"sha256": SHA, "size_bytes": 4321})

    def test_completed_command_is_never_executed_again(self):
        leased = claim(
            issue_command(
                command_id="cmd-001", device_id="lab-edge-01", target="edge",
                evidence=EvidenceRef(device_id="lab-edge-01", event_id="evt-1", request_id="req-001"),
                issued_by="alice", issued_at=NOW,
            ),
            now=NOW,
        )
        completed = acknowledge(leased, now=NOW + 1, lease_id=leased.lease_id,
                                ack={"kind": ACK_ARTIFACT, "sha256": SHA, "size_bytes": 10})
        executed = []
        outcome = self.worker([wire_payload(completed, now=NOW + 2)], lambda command: executed.append(1)).poll_once()
        self.assertEqual(executed, [])
        self.assertEqual(self.transport.acks, [])
        self.assertEqual(outcome, {"command_id": "cmd-001", "skipped": "already_completed"})
        self.assertEqual(wire_payload(completed)["status"], STATUS_COMPLETED)

    def test_shell_shaped_payload_is_refused_before_any_acknowledgement(self):
        payload = command_payload()
        payload["argv"] = ["ffmpeg", "-i", "x"]
        from domain.retrieval_contract import RetrievalError
        with self.assertRaises(RetrievalError):
            self.worker([payload], lambda command: {"sha256": SHA, "size_bytes": 1}).poll_once()
        self.assertEqual(self.transport.acks, [])

    def test_command_for_another_device_is_refused(self):
        from domain.retrieval_contract import RetrievalError
        with self.assertRaises(RetrievalError):
            self.worker([command_payload(device_id="lab-edge-02")], lambda command: {}).poll_once()
        self.assertEqual(self.transport.acks, [])

    def test_missing_clip_fails_with_evidence_unavailable(self):
        def executor(command):
            raise EvidenceUnavailable("gone")

        outcome = self.worker([command_payload()], executor).poll_once()
        self.assertEqual(outcome["reason"], "evidence_unavailable")
        self.assertEqual(self.transport.acks[-1][2]["kind"], ACK_FAILURE)
        self.assertEqual(self.transport.acks[-1][2]["reason"], "evidence_unavailable")

    def test_executor_crash_fails_with_an_allowlisted_reason(self):
        def executor(command):
            raise RuntimeError("ffmpeg died")

        outcome = self.worker([command_payload()], executor).poll_once()
        self.assertEqual(outcome["reason"], "recorder_unavailable")
        self.assertEqual(self.transport.acks[-1][2]["reason"], "recorder_unavailable")

    def test_expired_command_is_not_executed(self):
        executed = []
        outcome = self.worker([command_payload(ttl=10)], lambda command: executed.append(1), now=NOW + 11).poll_once()
        self.assertEqual((executed, self.transport.acks), ([], []))
        self.assertEqual(outcome, {"command_id": "cmd-001", "skipped": "expired"})

    def test_unleased_command_is_not_executed(self):
        payload = command_payload()
        payload.update({"status": "pending", "lease_id": None})
        outcome = self.worker([payload], lambda command: {}).poll_once()
        self.assertEqual(outcome, {"command_id": "cmd-001", "skipped": "not_leased"})
        self.assertEqual(self.transport.acks, [])

    def _payload(self, **overrides):
        payload = command_payload()
        payload.update(overrides)
        return payload

    def test_a_non_edge_target_is_refused_without_running_the_executor(self):
        executed = []
        outcome = self.worker([self._payload(target="server")], lambda command: executed.append(1)).poll_once()
        self.assertEqual(executed, [])
        self.assertEqual(outcome, {"command_id": "cmd-001", "status": "failed", "reason": "unsupported_target"})
        self.assertEqual(self.transport.acks[-1][2]["kind"], ACK_FAILURE)
        self.assertEqual(self.transport.acks[-1][2]["reason"], "unsupported_target")

    def test_an_unimplemented_retention_scope_is_refused_without_running_the_executor(self):
        executed = []
        outcome = self.worker([self._payload(retention_scope="metadata")], lambda command: executed.append(1)).poll_once()
        self.assertEqual(executed, [])
        self.assertEqual(
            outcome, {"command_id": "cmd-001", "status": "failed", "reason": "retention_scope_unsupported"}
        )
        self.assertEqual(self.transport.acks[-1][2]["reason"], "retention_scope_unsupported")

    def test_empty_poll_returns_nothing(self):
        self.assertIsNone(self.worker([], lambda command: {}).poll_once())
        self.assertEqual(self.transport.polls, [("lab-edge-01", 0.0)])


class RecorderExecutorTests(unittest.TestCase):
    class Recorder:
        def __init__(self, receipt):
            self.receipt = receipt
            self.calls = 0

        def finalize_pin(self, request_id):
            self.calls += 1
            if isinstance(self.receipt, Exception):
                raise self.receipt
            return self.receipt

    def test_artifact_is_read_from_the_finalized_receipt(self):
        recorder = self.Recorder({"artifact": {"path": "/tmp/x", "sha256": SHA.upper(), "size_bytes": 12},
                                  "actual_ranges": [[90.0, 120.0]]})
        artifact = RecorderClipRetainer(recorder)({"evidence": {"request_id": "req-001"}})
        self.assertEqual(artifact, {"sha256": SHA, "size_bytes": 12, "actual_ranges": [[90.0, 120.0]]})

    def test_missing_released_or_corrupt_clip_is_unavailable(self):
        for receipt in (KeyError("req-001"), ValueError("cannot finalize a released pin"),
                        {"artifact": {"sha256": "short", "size_bytes": 1}}, {"artifact": {}}, {}):
            with self.assertRaises(EvidenceUnavailable):
                RecorderClipRetainer(self.Recorder(receipt))({"evidence": {"request_id": "req-001"}})

    def test_oversized_clip_is_not_acknowledged_as_an_artifact(self):
        recorder = self.Recorder({"artifact": {"sha256": SHA, "size_bytes": 200 * 1024 * 1024}})
        with self.assertRaises(EvidenceUnavailable):
            RecorderClipRetainer(recorder)({"evidence": {"request_id": "req-001"}})


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class TransportTests(unittest.TestCase):
    def transport(self, body, *, capture):
        def opener(request, timeout=None):
            capture.append((request, timeout))
            return FakeResponse(json.dumps(body).encode())

        return RetrievalTransport("http://127.0.0.1:9000", "token-edge-1", opener=opener)

    def test_poll_and_acknowledge_build_device_requests(self):
        calls = []
        transport = self.transport({"commands": []}, capture=calls)
        self.assertEqual(transport.poll("lab-edge-01", wait_seconds=1.5), [])
        request, timeout = calls[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "http://127.0.0.1:9000/v1/devices/lab-edge-01/commands?wait=1.5")
        self.assertEqual(request.get_header("Authorization"), "Bearer token-edge-1")

        transport = self.transport({"command_id": "cmd-001", "status": "completed"}, capture=calls)
        transport.acknowledge("lab-edge-01", "cmd-001", {"lease_id": "abc", "kind": "metadata"})
        request, _ = calls[-1]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "http://127.0.0.1:9000/v1/devices/lab-edge-01/commands/cmd-001/ack")
        self.assertEqual(json.loads(request.data.decode()), {"lease_id": "abc", "kind": "metadata"})

    def test_transport_failures_are_typed(self):
        def refused(request, timeout=None):
            raise HTTPError(request.full_url, 503, "unavailable", {}, None)

        transport = RetrievalTransport("http://127.0.0.1:9000", "token-edge-1", opener=refused)
        with self.assertRaises(RetrievalTransportError):
            transport.poll("lab-edge-01")

    def test_non_loopback_http_is_refused(self):
        with self.assertRaises(ValueError):
            RetrievalTransport("http://cameras.example.com", "token")


if __name__ == "__main__":
    unittest.main()
