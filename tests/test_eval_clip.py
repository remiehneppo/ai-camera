"""tools/eval_clip event extraction: outbox rows carry a parsed snapshot, not raw JSON."""

from pathlib import Path
import tempfile
import unittest

from apps.edge.outbox import EventOutbox
from tests.test_server_evidence import sample_event
from tools.eval_clip import events_from_outbox


class EventsFromOutboxTests(unittest.TestCase):
    def test_persisted_incidents_are_summarised_without_touching_raw_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = EventOutbox(Path(tmp) / "events.sqlite3")
            event = sample_event()
            event["payload"]["taxonomy"] = "person_lying_persistent"
            event["payload"]["severity"] = "critical"
            outbox.enqueue(event)
            records = events_from_outbox(outbox)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["taxonomy"], "person_lying_persistent")
        self.assertEqual(records[0]["severity"], "critical")
        self.assertEqual(records[0]["origin"], "synthetic")
        self.assertIsNone(records[0]["pose_status"], "no pose outcome recorded on this fixture")
        self.assertEqual(records[0]["revision"], 1)

    def test_an_empty_outbox_yields_no_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(events_from_outbox(EventOutbox(Path(tmp) / "events.sqlite3")), [])


if __name__ == "__main__":
    unittest.main()
