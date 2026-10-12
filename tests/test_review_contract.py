from __future__ import annotations

import unittest

from domain.review_contract import ReviewTransitionError, ReviewValidationError, meaningful_content_hash, next_decision, validate_review_request


def review_request() -> dict[str, object]:
    return {
        "action": "confirm",
        "expected_review_version": 0,
        "viewed_event_revision": 1,
        "viewed_event_hash": "a" * 64,
        "viewed_evidence_versions": {},
        "reason": "Reviewed fixture",
    }


class ReviewContractTests(unittest.TestCase):
    def test_review_request_validates_and_returns_normalized_snapshot(self) -> None:
        request = validate_review_request(review_request())
        self.assertEqual(request["action"], "confirm")
        self.assertEqual(request["expected_review_version"], 0)
        self.assertEqual(request["viewed_evidence_versions"], {})

    def test_review_request_rejects_bool_versions_and_unknown_fields(self) -> None:
        request = review_request()
        request["expected_review_version"] = True
        with self.assertRaisesRegex(ReviewValidationError, "expected_review_version"):
            validate_review_request(request)
        request = review_request()
        request["token"] = "must-not-be-accepted"
        with self.assertRaisesRegex(ReviewValidationError, "unknown fields"):
            validate_review_request(request)
        request = review_request()
        request["action"] = {}
        with self.assertRaisesRegex(ReviewValidationError, "action"):
            validate_review_request(request)

    def test_hash_tracks_only_review_meaningful_content(self) -> None:
        first = {"payload": {"taxonomy": "person_fall", "severity": "high"}}
        harmless_revision = {"payload": {"taxonomy": "person_fall", "severity": "high"}, "produced_at": "later"}
        changed_severity = {"payload": {"taxonomy": "person_fall", "severity": "critical"}}
        changed_evidence = {"payload": {"taxonomy": "person_fall", "severity": "high", "evidence_versions": {"clip": 2}}}

        self.assertEqual(meaningful_content_hash(first), meaningful_content_hash(harmless_revision))
        self.assertNotEqual(meaningful_content_hash(first), meaningful_content_hash(changed_severity))
        self.assertNotEqual(meaningful_content_hash(first), meaningful_content_hash(changed_evidence))

    def test_review_transitions_require_explicit_reopen_for_correction(self) -> None:
        self.assertEqual(next_decision("unreviewed", "confirm"), "confirmed")
        self.assertEqual(next_decision("confirmed", "resolve"), "resolved")
        self.assertEqual(next_decision("false_positive", "reopen"), "unreviewed")
        with self.assertRaisesRegex(ReviewTransitionError, "explicit reopen"):
            next_decision("confirmed", "resolve", needs_re_review=True)
        self.assertEqual(next_decision("confirmed", "reopen", needs_re_review=True), "unreviewed")
        with self.assertRaises(ReviewTransitionError):
            next_decision("confirmed", "false_positive")


if __name__ == "__main__":
    unittest.main()
