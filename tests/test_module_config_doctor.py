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
from domain.alert_module_config import ERROR_MISSING_REQUIRED_FIELD, ERROR_SECRET_FIELD, ConfigError

DOCUMENT = {
    "modules": [
        {
            "module": "person_down",
            "config_version": "person-down-v1",
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
        cameras = report["documents"][0]["modules"][0]["cameras"]
        self.assertEqual([camera["camera_id"] for camera in cameras], ["cam-01", "cam-02"])
        self.assertEqual(cameras[0]["capability"], "not_activated")
        self.assertEqual((cameras[1]["capability"], cameras[1]["reason"]), ("disabled", "capability not cleared for site"))

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
        for payload in ({"modules": "nope"}, {"modules": [{"module": "x"}]}, {"cameras": {}}, ["modules"]):
            path = self.write(payload, name="bad.json")
            with self.assertRaises(ConfigError):
                load_module_registry(path)
        with self.assertRaises(ConfigError):
            load_module_registry(self.dir / "missing.json")

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


if __name__ == "__main__":
    unittest.main()
