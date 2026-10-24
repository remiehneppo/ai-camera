"""Ticket #03 delta slice: doctor reports real per camera module capability."""

import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from apps.edge.config import load_edge_config
from apps.edge.doctor import load_module_registry, main, module_capabilities, preflight
from apps.edge.runtime import EdgeRuntime
from domain.alert_module_config import (
    AlertModuleDefinition,
    AlertModuleRegistry,
    ERROR_FACTORY_NOT_ALLOWED,
    ERROR_MISSING_REQUIRED_FIELD,
    ERROR_SECRET_FIELD,
    ConfigError,
)

DOCUMENT = {
    "modules": [
        {
            "module": "person_down",
            "config_version": "person-down-v1",
            "factory": "person_down",
            "required_fields": ["roi"],
            "thresholds": ["min_score"],
            "cameras": {
                "cam-01": {
                    "version": 1,
                    "enabled": True,
                    "roi": [[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]],
                    "thresholds": {"min_score": 0.4},
                },
                "cam-02": {"version": 1, "enabled": False, "disabled_reason": "capability not cleared for site"},
            },
        }
    ]
}


def activated_document(session="lab-session-1"):
    document = json.loads(json.dumps(DOCUMENT))
    document["session"] = session
    return document


class ModuleDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def write(self, payload, name="modules.json"):
        path = self.dir / name
        path.write_text(json.dumps(payload))
        return path

    def test_valid_document_reports_each_camera_independently(self):
        path = self.write(DOCUMENT)
        report = module_capabilities([path])
        self.assertEqual(report["status"], "ok")
        entry = report["documents"][0]
        self.assertEqual(entry["modules"][0]["factory"], "person_down")
        cameras = entry["modules"][0]["cameras"]
        self.assertEqual([camera["camera_id"] for camera in cameras], ["cam-01", "cam-02"])
        self.assertEqual(cameras[0]["capability"], "not_activated")
        self.assertEqual((cameras[1]["capability"], cameras[1]["reason"]), ("disabled", "capability not cleared for site"))
        self.assertNotIn("effective", entry)
        self.assertNotIn("session", entry)

    def test_declared_session_activates_and_reports_enabled_capability(self):
        path = self.write(activated_document())
        entry = module_capabilities([path])["documents"][0]
        cameras = entry["modules"][0]["cameras"]
        self.assertEqual(cameras[0]["capability"], "enabled")
        self.assertEqual(cameras[1]["capability"], "disabled")
        self.assertEqual(entry["session"], "lab-session-1")
        self.assertTrue(entry["effective"]["cam-01"]["analytics_enabled"])
        self.assertEqual(entry["effective"]["cam-01"]["roi_polygon"], [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]])
        self.assertFalse(entry["effective"]["cam-02"]["analytics_enabled"])

    def test_perception_groups_are_reported_for_sharing(self):
        document = json.loads(json.dumps(activated_document()))
        document["modules"].append(
            {
                "module": "danger_zone",
                "config_version": "danger-v1",
                "factory": "danger_zone",
                "required_fields": ["roi"],
                "perception_profile": "person_down",
                "cameras": {"cam-01": {"version": 1, "enabled": True, "roi": [[[0.2, 0.2], [0.8, 0.2], [0.8, 0.8]]]}},
            }
        )
        entry = module_capabilities([self.write(document)])["documents"][0]
        shared = next(group for group in entry["perception_groups"] if group["perception_profile"] == "person_down")
        self.assertEqual(shared["modules"], ["danger_zone", "person_down"])
        self.assertTrue(shared["shared"])

    def test_enabled_camera_missing_required_field_fails_fast_with_context(self):
        document = json.loads(json.dumps(DOCUMENT))
        document["modules"][0]["cameras"]["cam-01"].pop("roi")
        path = self.write(document)
        with self.assertRaises(ConfigError) as caught:
            load_module_registry(path)
        error = caught.exception
        self.assertEqual(
            (error.code, error.module, error.camera_id, error.field),
            (ERROR_MISSING_REQUIRED_FIELD, "person_down", "cam-01", "roi"),
        )
        report = module_capabilities([path])
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["errors"][0]["field"], "roi")

    def test_malformed_documents_are_rejected(self):
        for payload in (
            {"modules": "nope"},
            {"modules": [{"module": "x"}]},
            {"cameras": {}},
            ["modules"],
            {"modules": [], "session": 5},
        ):
            path = self.write(payload, name="bad.json")
            with self.assertRaises(ConfigError):
                load_module_registry(path)
        with self.assertRaises(ConfigError):
            load_module_registry(self.dir / "missing.json")

    def test_falsy_non_dict_cameras_is_rejected_instead_of_silently_accepted(self):
        for cameras in ([], False, 0, ""):
            document = json.loads(json.dumps(DOCUMENT))
            document["modules"][0]["cameras"] = cameras
            with self.assertRaises(ConfigError) as caught:
                load_module_registry(self.write(document, name="cameras.json"))
            self.assertEqual(caught.exception.code, "invalid_module_config_document")

    def test_required_fields_and_thresholds_must_be_lists_of_names(self):
        for key, value in (("required_fields", 5), ("required_fields", "roi"), ("thresholds", 5), ("thresholds", "minscore")):
            document = json.loads(json.dumps(DOCUMENT))
            document["modules"][0][key] = value
            with self.assertRaises(ConfigError) as caught:
                load_module_registry(self.write(document, name="names.json"))
            self.assertEqual(caught.exception.code, "invalid_module_config_document", (key, value))
        document = json.loads(json.dumps(DOCUMENT))
        document["modules"][0]["thresholds"] = [1]
        with self.assertRaises(ConfigError):
            load_module_registry(self.write(document, name="names2.json"))

    def test_non_allowlisted_factory_is_rejected(self):
        document = json.loads(json.dumps(DOCUMENT))
        document["modules"][0]["factory"] = "fire_smoke"
        with self.assertRaises(ConfigError) as caught:
            load_module_registry(self.write(document))
        self.assertEqual(caught.exception.code, ERROR_FACTORY_NOT_ALLOWED)

    def test_conflicting_sessions_across_documents_are_rejected(self):
        first = self.write(activated_document("s1"), name="a.json")
        second = self.write(activated_document("s2"), name="b.json")
        with self.assertRaises(ConfigError):
            load_module_registry([first, second])

    def test_secret_bearing_config_never_reaches_the_report(self):
        document = json.loads(json.dumps(DOCUMENT))
        document["modules"][0]["cameras"]["cam-01"]["api_key"] = "sk-live-should-not-leak"
        path = self.write(document)
        report = module_capabilities([path])
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["errors"][0]["code"], ERROR_SECRET_FIELD)
        self.assertNotIn("sk-live-should-not-leak", json.dumps(report))


class DoctorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.source = self.dir / "source.mkv"
        self.source.write_bytes(b"not real media")
        self.config_path = self.dir / "edge.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "source": str(self.source),
                    "output_dir": str(self.dir / "out"),
                    "analytics_enabled": False,
                    "disabled_reason": "lab analytics disabled",
                }
            )
        )

    def run_main(self, *extra):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--config", str(self.config_path), *extra])
        return code, buffer.getvalue()

    def test_preflight_without_module_documents_reports_not_configured(self):
        config = load_edge_config(json.loads(self.config_path.read_text()))
        report = preflight(config)
        self.assertEqual(report["capabilities"]["modules"]["status"], "not_configured")
        self.assertNotIn("capacity", json.dumps(report).lower())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
    def test_cli_reports_module_capability_and_stops_nonzero_on_invalid_config(self):
        document = self.dir / "modules.json"
        document.write_text(json.dumps(DOCUMENT))
        code, output = self.run_main("--module-config", str(document))
        self.assertEqual(code, 0, output)
        report = json.loads(output)
        self.assertEqual(report["scope"], "preflight")
        modules = report["capabilities"]["modules"]
        self.assertEqual(modules["documents"][0]["modules"][0]["module"], "person_down")

        broken = json.loads(json.dumps(DOCUMENT))
        broken["modules"][0]["cameras"]["cam-01"].pop("roi")
        document.write_text(json.dumps(broken))
        code, output = self.run_main("--module-config", str(document))
        self.assertEqual(code, 1)
        report = json.loads(output)
        self.assertEqual(report["capabilities"]["modules"]["status"], "error")
        self.assertEqual(report["capabilities"]["modules"]["errors"][0]["field"], "roi")


class RuntimeConsumerTests(unittest.TestCase):
    """EdgeRuntime is the consumer of the registry switch (ticket #03 delta)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.source = self.dir / "source.mkv"
        self.source.write_bytes(b"not real media")
        self.registry = AlertModuleRegistry()
        self.registry.register(AlertModuleDefinition(module="person_down", config_version="v1", factory="person_down"))

    def runtime(self, **kwargs):
        return EdgeRuntime(
            source=self.source,
            output_dir=self.dir / "out",
            camera_id="lab-camera",
            session_id="lab-replay",
            **kwargs,
        )

    def test_registry_switch_turns_analytics_off_with_the_module_reason(self):
        config = self.registry.parse(
            "person_down", "lab-camera", {"version": 1, "enabled": False, "disabled_reason": "roi not approved"}
        )
        self.registry.activate(config, session_id="lab-replay")
        status = self.runtime(analytics_enabled=True, module_registry=self.registry, module_session="lab-replay").status()
        self.assertEqual(status["analytics"]["state"], "disabled")
        self.assertIn("roi not approved", status["analytics"]["reason"])

    def test_registry_switch_turns_analytics_on_even_when_config_said_off(self):
        self.registry.activate(
            self.registry.parse(
                "person_down",
                "lab-camera",
                {"version": 1, "enabled": True, "roi": [[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]]},
            ),
            session_id="lab-replay",
        )
        status = self.runtime(
            analytics_enabled=False, disabled_reason="config said off", module_registry=self.registry, module_session="lab-replay"
        ).status()
        self.assertEqual(status["analytics"]["state"], "not_started")

    def test_runtime_without_registry_keeps_its_own_enable_flag(self):
        status = self.runtime(analytics_enabled=False, disabled_reason="explicit").status()
        self.assertEqual(status["analytics"]["state"], "disabled")
        self.assertEqual(status["analytics"]["reason"], "explicit")


if __name__ == "__main__":
    unittest.main()
