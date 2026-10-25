"""Ticket #32: retained-evidence retrieval command contract."""

import unittest

from domain.retrieval_contract import (
    ACK_ARTIFACT,
    ACK_FAILURE,
    ACK_METADATA,
    DEFAULT_LEASE_SECONDS,
    ERROR_ARTIFACT_CONFLICT,
    ERROR_COMMAND_TERMINAL,
    ERROR_FORBIDDEN_FIELD,
    ERROR_INVALID_ACK,
    ERROR_INVALID_COMMAND,
    ERROR_SCOPE_NOT_SUPPORTED,
    ERROR_STALE_LEASE,
    ERROR_TARGET_NOT_ALLOWED,
    ERROR_TTL_EXCEEDED,
    EvidenceRef,
    RetrievalError,
    STATUS_CLAIMED,
    STATUS_COMPLETED,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_OFFLINE,
    STATUS_PENDING,
    acknowledge,
    claim,
    issue_command,
    requester_status,
    settle_target,
    validate_command_payload,
    wire_payload,
)

SHA = "a" * 64
NOW = 1_000.0


def evidence(device_id="lab-edge-01", event_id="evt-1", request_id="req-001"):
    return EvidenceRef(device_id=device_id, event_id=event_id, request_id=request_id)


def issued(*, ttl=300.0, target="edge", scope="clip", issued_at=NOW):
    return issue_command(
        command_id="cmd-001",
        device_id="lab-edge-01",
        target=target,
        evidence=evidence(),
        issued_by="alice",
        issued_at=issued_at,
        ttl_seconds=ttl,
        retention_scope=scope,
    )


class IssueTests(unittest.TestCase):
    def test_issued_command_is_pending_and_bounded(self):
        state = issued(ttl=120)
        self.assertEqual(state.status, STATUS_PENDING)
        self.assertIsNone(state.lease_id)
        self.assertEqual(state.command.expires_at, NOW + 120)

    def test_target_and_action_are_allowlisted(self):
        with self.assertRaises(RetrievalError) as caught:
            issued(target="recorder-shell")
        self.assertEqual(caught.exception.code, ERROR_TARGET_NOT_ALLOWED)
        with self.assertRaises(RetrievalError) as caught:
            issue_command(
                command_id="cmd-2", device_id="lab-edge-01", target="edge", evidence=evidence(),
                issued_by="alice", issued_at=NOW, action="run_shell",
            )
        self.assertEqual(caught.exception.code, ERROR_INVALID_COMMAND)

    def test_ttl_must_be_positive_and_bounded(self):
        for ttl in (0, -5):
            with self.assertRaises(RetrievalError) as caught:
                issued(ttl=ttl)
            self.assertEqual(caught.exception.code, ERROR_INVALID_COMMAND)
        with self.assertRaises(RetrievalError) as caught:
            issued(ttl=4_000)
        self.assertEqual(caught.exception.code, ERROR_TTL_EXCEEDED)

    def test_evidence_device_must_match_the_command_device(self):
        with self.assertRaises(RetrievalError) as caught:
            issue_command(
                command_id="cmd-2", device_id="lab-edge-02", target="edge",
                evidence=evidence(device_id="lab-edge-01"), issued_by="alice", issued_at=NOW,
            )
        self.assertEqual(caught.exception.code, ERROR_INVALID_COMMAND)

    def test_identifiers_are_validated(self):
        with self.assertRaises(RetrievalError):
            issue_command(
                command_id="../../etc/passwd", device_id="lab-edge-01", target="edge",
                evidence=evidence(), issued_by="alice", issued_at=NOW,
            )


class WirePayloadTests(unittest.TestCase):
    def test_wire_payload_is_a_closed_field_set(self):
        payload = wire_payload(claim(issued(), now=NOW), now=NOW)
        self.assertEqual(
            set(payload),
            {"command_id", "device_id", "target", "action", "evidence", "issued_at", "expires_at",
             "retention_scope", "status", "lease_id", "expires_in_seconds"},
        )
        self.assertEqual(payload["evidence"], {"device_id": "lab-edge-01", "event_id": "evt-1", "request_id": "req-001"})
        self.assertEqual(payload["expires_in_seconds"], 300.0)
        self.assertEqual(validate_command_payload(payload)["command_id"], "cmd-001")

    def test_shell_and_executable_shaped_fields_are_refused(self):
        for field in ("argv", "shell", "script", "callback_url", "exec", "endpoint", "binary", "stdin"):
            payload = wire_payload(issued(), now=NOW)
            payload[field] = "rm -rf /"
            with self.assertRaises(RetrievalError) as caught:
                validate_command_payload(payload)
            self.assertEqual(caught.exception.code, ERROR_FORBIDDEN_FIELD, field)

    def test_unknown_fields_and_extra_evidence_keys_are_refused(self):
        payload = wire_payload(issued(), now=NOW)
        payload["note"] = "free text"
        with self.assertRaises(RetrievalError) as caught:
            validate_command_payload(payload)
        self.assertEqual(caught.exception.code, ERROR_INVALID_COMMAND)
        payload = wire_payload(issued(), now=NOW)
        payload["evidence"] = {**payload["evidence"], "path": "/etc/shadow"}
        with self.assertRaises(RetrievalError) as caught:
            validate_command_payload(payload)
        self.assertEqual(caught.exception.code, ERROR_INVALID_COMMAND)

    def test_payload_status_and_target_are_revalidated(self):
        payload = wire_payload(issued(), now=NOW)
        payload["status"] = "running"
        with self.assertRaises(RetrievalError):
            validate_command_payload(payload)
        payload = wire_payload(issued(), now=NOW)
        payload["target"] = "s3"
        with self.assertRaises(RetrievalError) as caught:
            validate_command_payload(payload)
        self.assertEqual(caught.exception.code, ERROR_TARGET_NOT_ALLOWED)


class ClaimTests(unittest.TestCase):
    def test_claim_leases_once_and_is_idempotent_while_the_lease_is_alive(self):
        first = claim(issued(), now=NOW)
        self.assertEqual(first.status, STATUS_CLAIMED)
        self.assertEqual(first.attempts, 1)
        again = claim(first, now=NOW + 1)
        self.assertEqual(again.lease_id, first.lease_id)
        self.assertEqual(again.attempts, 1)

    def test_expired_lease_grants_a_new_attempt(self):
        first = claim(issued(), now=NOW)
        retried = claim(first, now=NOW + DEFAULT_LEASE_SECONDS + 1)
        self.assertEqual(retried.status, STATUS_CLAIMED)
        self.assertEqual(retried.attempts, 2)
        self.assertNotEqual(retried.lease_id, first.lease_id)

    def test_claim_after_expiry_marks_the_command_expired(self):
        state = claim(issued(ttl=10), now=NOW + 11)
        self.assertEqual((state.status, state.lease_id, state.reason), (STATUS_EXPIRED, None, "expired"))

    def test_claim_never_reissues_a_completed_command(self):
        leased = claim(issued(), now=NOW)
        completed = acknowledge(leased, now=NOW + 1, lease_id=leased.lease_id,
                                ack={"kind": ACK_ARTIFACT, "sha256": SHA, "size_bytes": 10})
        self.assertEqual(claim(completed, now=NOW + 2), completed)


class AcknowledgeTests(unittest.TestCase):
    def claimed(self, **kwargs):
        return claim(issued(**kwargs), now=NOW)

    def test_metadata_acknowledgement_records_receipt_without_releasing_the_clip(self):
        state = self.claimed()
        acked = acknowledge(state, now=NOW + 1, lease_id=state.lease_id, ack={"kind": ACK_METADATA})
        self.assertTrue(acked.metadata_acknowledged)
        self.assertEqual(acked.status, STATUS_CLAIMED)
        self.assertIsNone(acked.artifact)
        self.assertEqual(requester_status(acked, now=NOW + 2, device_last_seen=NOW), STATUS_PENDING)
        self.assertEqual(acknowledge(acked, now=NOW + 3, lease_id=state.lease_id, ack={"kind": ACK_METADATA}), acked)

    def test_unimplemented_retention_scope_is_refused_instead_of_faked(self):
        with self.assertRaises(RetrievalError) as caught:
            issued(scope="metadata")
        self.assertEqual(caught.exception.code, ERROR_SCOPE_NOT_SUPPORTED)
        # A device may still receive a well-formed metadata command from an older server: the
        # payload stays parseable so the worker can refuse it with a typed failure.
        payload = wire_payload(issued(), now=NOW)
        payload["retention_scope"] = "metadata"
        self.assertEqual(validate_command_payload(payload)["retention_scope"], "metadata")

    def test_artifact_acknowledgement_completes_and_is_idempotent(self):
        state = self.claimed()
        ack = {"kind": ACK_ARTIFACT, "sha256": SHA, "size_bytes": 1234, "actual_ranges": [{"start": 90.0, "end": 120.0}]}
        done = acknowledge(state, now=NOW + 1, lease_id=state.lease_id, ack=ack)
        self.assertEqual(done.status, STATUS_COMPLETED)
        self.assertEqual(done.artifact["size_bytes"], 1234)
        self.assertEqual(done.artifact["actual_ranges"], [{"start": 90.0, "end": 120.0}])
        self.assertIsNone(done.lease_id)
        self.assertEqual(acknowledge(done, now=NOW + 2, lease_id=state.lease_id, ack=ack), done)
        conflicting = {**ack, "sha256": "b" * 64}
        with self.assertRaises(RetrievalError) as caught:
            acknowledge(done, now=NOW + 3, lease_id=state.lease_id, ack=conflicting)
        self.assertEqual(caught.exception.code, ERROR_ARTIFACT_CONFLICT)

    def test_artifact_acknowledgement_needs_a_valid_hash_and_size(self):
        state = self.claimed()
        for ack in (
            {"kind": ACK_ARTIFACT, "sha256": "short", "size_bytes": 1},
            {"kind": ACK_ARTIFACT, "sha256": SHA, "size_bytes": -1},
            {"kind": ACK_ARTIFACT, "sha256": SHA},
            {"kind": ACK_ARTIFACT, "sha256": SHA, "size_bytes": 1, "actual_ranges": "90-120"},
        ):
            with self.assertRaises(RetrievalError) as caught:
                acknowledge(state, now=NOW + 1, lease_id=state.lease_id, ack=ack)
            self.assertEqual(caught.exception.code, ERROR_INVALID_ACK, ack)

    def test_stale_or_foreign_leases_are_refused(self):
        state = self.claimed()
        for lease in (None, "", "not-the-lease"):
            with self.assertRaises(RetrievalError) as caught:
                acknowledge(state, now=NOW + 1, lease_id=lease, ack={"kind": ACK_METADATA})
            self.assertEqual(caught.exception.code, ERROR_STALE_LEASE)
        with self.assertRaises(RetrievalError) as caught:
            acknowledge(issued(), now=NOW + 1, lease_id="x", ack={"kind": ACK_METADATA})
        self.assertEqual(caught.exception.code, ERROR_STALE_LEASE)

    def test_failure_acknowledgement_uses_an_allowlisted_reason(self):
        state = self.claimed()
        failed = acknowledge(state, now=NOW + 1, lease_id=state.lease_id,
                             ack={"kind": ACK_FAILURE, "reason": "evidence_unavailable"})
        self.assertEqual((failed.status, failed.reason), (STATUS_FAILED, "evidence_unavailable"))
        with self.assertRaises(RetrievalError) as caught:
            acknowledge(state, now=NOW + 1, lease_id=state.lease_id, ack={"kind": ACK_FAILURE, "reason": "because"})
        self.assertEqual(caught.exception.code, ERROR_INVALID_ACK)
        with self.assertRaises(RetrievalError) as caught:
            acknowledge(failed, now=NOW + 2, lease_id=state.lease_id, ack={"kind": ACK_METADATA})
        self.assertEqual(caught.exception.code, ERROR_COMMAND_TERMINAL)

    def test_a_late_acknowledgement_cannot_complete_an_expired_command(self):
        state = claim(issued(ttl=10), now=NOW)
        late = acknowledge(state, now=NOW + 11, lease_id=state.lease_id,
                           ack={"kind": ACK_ARTIFACT, "sha256": SHA, "size_bytes": 5})
        self.assertEqual((late.status, late.reason, late.artifact), (STATUS_EXPIRED, "expired", None))

    def test_unknown_acknowledgement_kinds_are_refused(self):
        state = self.claimed()
        for ack in ({"kind": "execute"}, {}, {"kind": "metadata", "argv": ["ls"]}):
            with self.assertRaises(RetrievalError) as caught:
                acknowledge(state, now=NOW + 1, lease_id=state.lease_id, ack=ack)
            self.assertEqual(caught.exception.code, ERROR_INVALID_ACK if ack.get("kind") == "metadata" else "unknown_ack_kind")


class RequesterViewTests(unittest.TestCase):
    def test_pending_offline_and_expired_are_delivery_states(self):
        state = issued(ttl=60)
        self.assertEqual(requester_status(state, now=NOW + 1, device_last_seen=NOW), STATUS_PENDING)
        self.assertEqual(requester_status(state, now=NOW + 1, device_last_seen=NOW - 500), STATUS_OFFLINE)
        self.assertEqual(requester_status(state, now=NOW + 1, device_last_seen=None), STATUS_OFFLINE)
        self.assertEqual(requester_status(state, now=NOW + 61, device_last_seen=NOW), STATUS_EXPIRED)

    def test_terminal_states_are_reported_as_themselves(self):
        state = claim(issued(), now=NOW)
        done = acknowledge(state, now=NOW + 1, lease_id=state.lease_id,
                           ack={"kind": ACK_ARTIFACT, "sha256": SHA, "size_bytes": 5})
        self.assertEqual(requester_status(done, now=NOW + 2, device_last_seen=None), STATUS_COMPLETED)
        leased = claim(issued(), now=NOW)
        failed = acknowledge(leased, now=NOW + 1, lease_id=leased.lease_id,
                             ack={"kind": ACK_FAILURE, "reason": "recorder_unavailable"})
        self.assertEqual(requester_status(failed, now=NOW + 2, device_last_seen=None), STATUS_FAILED)

    def test_server_target_settles_on_availability(self):
        completed = settle_target(issued(target="server"), now=NOW + 1, available=True,
                                  artifact={"sha256": SHA, "size_bytes": 42})
        self.assertEqual((completed.status, completed.artifact["size_bytes"]), (STATUS_COMPLETED, 42))
        missing = settle_target(issued(target="server"), now=NOW + 1, available=False)
        self.assertEqual((missing.status, missing.reason), (STATUS_FAILED, "evidence_unavailable"))
        self.assertEqual(settle_target(missing, now=NOW + 2, available=True, artifact={"sha256": SHA, "size_bytes": 1}), missing)
        expired = settle_target(issued(target="server", ttl=10), now=NOW + 11, available=True,
                                artifact={"sha256": SHA, "size_bytes": 1})
        self.assertEqual(expired.status, STATUS_EXPIRED)
        with self.assertRaises(RetrievalError):
            settle_target(issued(target="server"), now=NOW + 1, available=True)

    def test_claimed_command_still_reads_as_pending_for_the_requester(self):
        state = claim(issued(), now=NOW)
        self.assertEqual(requester_status(state, now=NOW + 1, device_last_seen=NOW), STATUS_PENDING)


if __name__ == "__main__":
    unittest.main()
