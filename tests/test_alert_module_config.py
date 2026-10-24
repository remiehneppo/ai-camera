"""Ticket #03 delta slice: independent module x camera configuration contract."""

import math
import unittest

from domain.alert_module_config import (
    ALLOWLISTED_FACTORIES,
    AlertModuleDefinition,
    AlertModuleRegistry,
    ConfigError,
    ERROR_DUPLICATE_MODULE,
    ERROR_FACTORY_NOT_ALLOWED,
    ERROR_INVALID_CAMERA_ID,
    ERROR_INVALID_CONFIG_VERSION,
    ERROR_INVALID_EXCEPTION,
    ERROR_INVALID_ROI,
    ERROR_INVALID_SCHEDULE,
    ERROR_INVALID_SESSION_ID,
    ERROR_INVALID_THRESHOLD,
    ERROR_MISSING_DISABLED_REASON,
    ERROR_MISSING_REQUIRED_FIELD,
    ERROR_SECRET_FIELD,
    ERROR_STALE_CONFIG_VERSION,
    ERROR_UNKNOWN_FIELD,
    ERROR_UNKNOWN_MODULE,
    ERROR_UNKNOWN_THRESHOLD,
    STATUS_ACTIVE,
    STATUS_DISABLED,
    STATUS_PENDING,
    STATUS_REJECTED,
    ExceptionRule,
    RegionOfInterest,
    ScheduleWindow,
    parse_camera_module_config,
)

PERSON_DOWN = AlertModuleDefinition(
    module="person_down",
    config_version="person-down-v1",
    factory="person_down",
    required_fields=frozenset({"roi", "thresholds"}),
    thresholds=frozenset({"min_score", "persistence_seconds"}),
)
VEHICLE = AlertModuleDefinition(
    module="vehicle_incident",
    config_version="vehicle-v1",
    factory="vehicle_incident",
    required_fields=frozenset({"roi"}),
    thresholds=frozenset({"motion_delta"}),
)
DANGER = AlertModuleDefinition(
    module="danger_zone",
    config_version="danger-v1",
    factory="danger_zone",
    required_fields=frozenset({"roi"}),
    perception_profile="person_down",
)

ROI = [[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]]
SCHEDULE = [{"days": ["mon", "tue"], "start_second": 21600, "end_second": 61200}]


def enabled_payload(version=1, **overrides):
    payload = {
        "version": version,
        "enabled": True,
        "roi": ROI,
        "schedule": SCHEDULE,
        "thresholds": {"min_score": 0.4, "persistence_seconds": 5},
        "exceptions": [{"code": "event_zone", "reason": "fair approved by operations"}],
    }
    payload.update(overrides)
    return payload


class FailFastTests(unittest.TestCase):
    def fail_with(self, payload, definition=PERSON_DOWN, camera_id="cam-01"):
        with self.assertRaises(ConfigError) as caught:
            parse_camera_module_config(definition, camera_id, payload)
        return caught.exception

    def test_enabled_config_with_missing_required_field_names_module_camera_and_field(self):
        payload = enabled_payload()
        payload.pop("thresholds")
        error = self.fail_with(payload)
        self.assertEqual(error.code, ERROR_MISSING_REQUIRED_FIELD)
        self.assertEqual((error.module, error.camera_id, error.field), ("person_down", "cam-01", "thresholds"))
        self.assertIn("module=person_down", str(error))
        self.assertIn("camera=cam-01", str(error))
        self.assertIn("field=thresholds", str(error))

    def test_empty_required_field_is_not_silently_skipped(self):
        error = self.fail_with(enabled_payload(roi=[]))
        self.assertEqual((error.code, error.field), (ERROR_MISSING_REQUIRED_FIELD, "roi"))

    def test_disabled_config_requires_a_reason_and_enabled_config_must_not_carry_one(self):
        error = self.fail_with({"version": 1, "enabled": False})
        self.assertEqual((error.code, error.field), (ERROR_MISSING_DISABLED_REASON, "disabled_reason"))
        error = self.fail_with({"version": 1, "enabled": False, "disabled_reason": "   "})
        self.assertEqual(error.code, ERROR_MISSING_DISABLED_REASON)
        error = self.fail_with({"version": 1, "enabled": True, "disabled_reason": "why"})
        self.assertEqual(error.code, "invalid_field_type")

    def test_disabled_config_needs_no_module_specific_fields(self):
        config = parse_camera_module_config(
            PERSON_DOWN, "cam-01", {"version": 3, "enabled": False, "disabled_reason": "capability not cleared for site"}
        )
        self.assertFalse(config.enabled)
        self.assertEqual(config.disabled_reason, "capability not cleared for site")

    def test_secret_material_is_rejected_and_never_echoed(self):
        error = self.fail_with({"version": 1, "enabled": True, "roi": ROI, "api_key": "sk-live-abcdef"})
        self.assertEqual((error.code, error.field), (ERROR_SECRET_FIELD, "api_key"))
        self.assertNotIn("sk-live-abcdef", str(error))
        self.assertNotIn("sk-live-abcdef", repr(error.describe()))

    def test_nested_secret_material_is_rejected_too(self):
        error = self.fail_with(
            {"version": 1, "enabled": True, "roi": ROI, "thresholds": {"min_score": 0.4, "db_password": 1}}
        )
        self.assertEqual(error.code, ERROR_SECRET_FIELD)
        self.assertIn("db_password", error.field or "")

    def test_unknown_field_and_version_are_rejected(self):
        error = self.fail_with(enabled_payload(roi_override=ROI))
        self.assertEqual((error.code, error.field), (ERROR_UNKNOWN_FIELD, "roi_override"))
        error = self.fail_with(enabled_payload(version=0))
        self.assertEqual(error.code, ERROR_INVALID_CONFIG_VERSION)
        error = self.fail_with({name: value for name, value in enabled_payload().items() if name != "version"})
        self.assertEqual((error.code, error.field), (ERROR_MISSING_REQUIRED_FIELD, "version"))

    def test_threshold_names_come_from_the_module_definition_and_values_must_be_finite(self):
        error = self.fail_with(enabled_payload(thresholds={"min_score": 0.4, "persistence_seconds": 5, "iou": 0.2}))
        self.assertEqual((error.code, error.field), (ERROR_UNKNOWN_THRESHOLD, "thresholds.iou"))
        error = self.fail_with(enabled_payload(thresholds={"min_score": math.inf, "persistence_seconds": 5}))
        self.assertEqual((error.code, error.field), (ERROR_INVALID_THRESHOLD, "thresholds.min_score"))

    def test_roi_schedule_and_exception_shapes_are_validated_with_field_context(self):
        for payload in (
            enabled_payload(roi=[[[0.1, 0.1], [0.9, 0.1]]]),
            enabled_payload(roi=[[[0.1, 0.1], [1.4, 0.1], [0.9, 0.9]]]),
            enabled_payload(roi=[[[0.1, 0.1], [0.9], [0.9, 0.9]]]),
            enabled_payload(roi=[[[0.1, float("nan")], [0.9, 0.1], [0.9, 0.9]]]),
        ):
            error = self.fail_with(payload)
            self.assertEqual((error.code, error.field), (ERROR_INVALID_ROI, "roi"))
        for payload, code, field in (
            (enabled_payload(schedule=[{"days": ["mon", "funday"], "start_second": 0, "end_second": 10}]),
             ERROR_INVALID_SCHEDULE, "schedule"),
            (enabled_payload(schedule=[{"days": ["mon"], "start_second": 100, "end_second": 100}]),
             ERROR_INVALID_SCHEDULE, "schedule"),
            (enabled_payload(exceptions=[{"code": "x"}]), ERROR_INVALID_EXCEPTION, "exceptions"),
            (enabled_payload(exceptions=[{"code": "x y", "reason": "r"}]), ERROR_INVALID_EXCEPTION, "exceptions"),
        ):
            error = self.fail_with(payload)
            self.assertEqual((error.code, error.field), (code, field))

    def test_unsafe_identifiers_are_rejected(self):
        with self.assertRaises(ConfigError) as caught:
            parse_camera_module_config(PERSON_DOWN, "../cam", enabled_payload())
        self.assertEqual(caught.exception.code, ERROR_INVALID_CAMERA_ID)

    def test_unusable_field_type_fails_fast_instead_of_raising_type_error(self):
        with self.assertRaises(ConfigError) as caught:
            parse_camera_module_config(
                PERSON_DOWN, "cam-01", {"version": 1, "enabled": True, "roi": 5, "thresholds": {"min_score": 0.4}}
            )
        self.assertEqual((caught.exception.code, caught.exception.field), ("invalid_field_type", "roi"))


class ConfigurationTests(unittest.TestCase):
    def test_canonical_config_round_trips_and_hashes_the_whole_content(self):
        config = parse_camera_module_config(PERSON_DOWN, "cam-01", enabled_payload())
        self.assertEqual(config.roi, (RegionOfInterest(points=((0.1, 0.1), (0.9, 0.1), (0.9, 0.9))),))
        self.assertEqual(config.schedule, (ScheduleWindow(days=("mon", "tue"), start_second=21600, end_second=61200),))
        self.assertEqual(config.thresholds, (("min_score", 0.4), ("persistence_seconds", 5.0)))
        self.assertEqual(config.threshold("min_score"), 0.4)
        self.assertEqual(config.exceptions, (ExceptionRule(code="event_zone", reason="fair approved by operations"),))
        self.assertEqual(config.roi_polygon(), [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]])
        self.assertEqual(config.describe()["roi"], [[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]])

    def test_hash_changes_when_operator_meaning_changes(self):
        base = parse_camera_module_config(PERSON_DOWN, "cam-01", enabled_payload())
        moved = parse_camera_module_config(PERSON_DOWN, "cam-01", enabled_payload(version=2))
        self.assertNotEqual(base.config_hash, moved.config_hash)
        self.assertEqual(base.config_hash, parse_camera_module_config(PERSON_DOWN, "cam-01", enabled_payload()).config_hash)

    def test_roi_polygon_is_none_when_the_module_declares_no_roi(self):
        config = parse_camera_module_config(
            PERSON_DOWN, "cam-01", {"version": 1, "enabled": False, "disabled_reason": "off"}
        )
        self.assertIsNone(config.roi_polygon())


class DefinitionTests(unittest.TestCase):
    def test_factory_must_be_allowlisted_by_the_registry_and_an_identifier(self):
        self.assertIn("person_down", ALLOWLISTED_FACTORIES)
        with self.assertRaises(ConfigError) as caught:
            AlertModuleDefinition(module="person_down", config_version="v1", factory="bad factory")
        self.assertEqual(caught.exception.code, ERROR_FACTORY_NOT_ALLOWED)
        shipped = AlertModuleDefinition(module="fire_smoke", config_version="v1", factory="fire_smoke")
        with self.assertRaises(ConfigError) as caught:
            AlertModuleRegistry().register(shipped)
        self.assertEqual(caught.exception.code, ERROR_FACTORY_NOT_ALLOWED)
        with self.assertRaises(ConfigError) as caught:
            AlertModuleRegistry(allowlisted_factories=()).register(PERSON_DOWN)
        self.assertEqual(caught.exception.code, ERROR_FACTORY_NOT_ALLOWED)

    def test_perception_profile_defaults_to_the_factory(self):
        self.assertEqual(PERSON_DOWN.perception_profile, "person_down")
        self.assertEqual(DANGER.perception_profile, "person_down")

    def test_definition_rejects_non_sets_and_unknown_required_fields(self):
        for kwargs in (
            {"required_fields": "roi"},
            {"required_fields": 5},
            {"thresholds": "min_score"},
            {"thresholds": 5},
            {"required_fields": frozenset({"unknown"})},
        ):
            with self.assertRaises(ConfigError):
                AlertModuleDefinition(module="person_down", config_version="v1", factory="person_down", **kwargs)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = AlertModuleRegistry()
        self.registry.register(PERSON_DOWN)
        self.registry.register(VEHICLE)
        self.registry.register(DANGER)

    def test_registration_is_independent(self):
        self.assertEqual(self.registry.modules(), ("danger_zone", "person_down", "vehicle_incident"))
        self.registry.stage(self.registry.parse("person_down", "cam-01", enabled_payload()))
        self.assertIsNone(self.registry.state("vehicle_incident", "cam-01"))
        self.assertIsNone(self.registry.state("person_down", "cam-02"))
        with self.assertRaises(ConfigError) as caught:
            self.registry.register(PERSON_DOWN)
        self.assertEqual(caught.exception.code, ERROR_DUPLICATE_MODULE)
        with self.assertRaises(ConfigError) as caught:
            self.registry.parse("fire_smoke", "cam-01", enabled_payload())
        self.assertEqual(caught.exception.code, ERROR_UNKNOWN_MODULE)

    def test_stage_does_not_observe_and_activate_is_the_boundary(self):
        state = self.registry.stage(self.registry.parse("person_down", "cam-01", enabled_payload()))
        self.assertEqual((state.status, state.observed_version), (STATUS_PENDING, None))
        activated = self.registry.activate(
            self.registry.parse("person_down", "cam-01", enabled_payload()), session_id="s1"
        )
        self.assertEqual((activated.status, activated.observed_version), (STATUS_ACTIVE, 1))
        self.assertEqual(self.registry.state("person_down", "cam-01"), activated)

    def test_staging_does_not_disturb_what_is_currently_observed(self):
        self.registry.activate(self.registry.parse("person_down", "cam-01", enabled_payload(version=1)), session_id="s1")
        staged = self.registry.stage(self.registry.parse("person_down", "cam-01", enabled_payload(version=2)))
        self.assertEqual((staged.status, staged.observed_version, staged.desired_version), (STATUS_ACTIVE, 1, 2))
        applied = self.registry.activate(
            self.registry.parse("person_down", "cam-01", enabled_payload(version=2)), session_id="s1"
        )
        self.assertEqual(applied.observed_version, 2)

    def test_disabled_module_reports_its_reason_and_is_not_activated(self):
        config = self.registry.parse(
            "vehicle_incident", "cam-01", {"version": 1, "enabled": False, "disabled_reason": "waiting for calibration"}
        )
        state = self.registry.activate(config, session_id="s1")
        self.assertEqual((state.status, state.reason), (STATUS_DISABLED, "waiting for calibration"))
        report = self.registry.capabilities()
        camera = next(module for module in report["modules"] if module["module"] == "vehicle_incident")["cameras"][0]
        self.assertEqual((camera["capability"], camera["reason"]), ("disabled", "waiting for calibration"))

    def test_stale_activation_is_rejected_and_last_known_good_version_is_kept(self):
        newer = self.registry.parse("person_down", "cam-01", enabled_payload(version=2))
        self.registry.activate(newer, session_id="s1")
        stale = self.registry.parse("person_down", "cam-01", enabled_payload(version=1))
        state = self.registry.activate(stale, session_id="s1")
        self.assertEqual((state.status, state.reason), (STATUS_REJECTED, ERROR_STALE_CONFIG_VERSION))
        self.assertEqual(state.observed_version, 2)
        self.assertEqual(self.registry.state("person_down", "cam-01").observed_version, 2)
        self.assertEqual(self.registry.config("person_down", "cam-01").version, 2)
        forward = self.registry.parse("person_down", "cam-01", enabled_payload(version=3))
        self.assertEqual(self.registry.activate(forward, session_id="s1").observed_version, 3)

    def test_session_change_rebinds_activation_and_keeps_configuration(self):
        self.registry.activate(self.registry.parse("person_down", "cam-01", enabled_payload()), session_id="s1")
        self.registry.stage(
            self.registry.parse("vehicle_incident", "cam-01", {"version": 1, "enabled": False, "disabled_reason": "off"})
        )
        reset = self.registry.reset_session("cam-01", "s2")
        self.assertEqual(reset, ("person_down", "vehicle_incident"))
        state = self.registry.state("person_down", "cam-01")
        self.assertEqual((state.status, state.observed_version, state.session_id), (STATUS_PENDING, None, "s2"))
        self.assertEqual(self.registry.config("person_down", "cam-01").version, 1)
        vehicle = self.registry.state("vehicle_incident", "cam-01")
        self.assertEqual((vehicle.status, vehicle.reason), (STATUS_DISABLED, "off"))
        with self.assertRaises(ConfigError) as caught:
            self.registry.activate(
                self.registry.parse("person_down", "cam-01", enabled_payload()), session_id="bad session"
            )
        self.assertEqual(caught.exception.code, ERROR_INVALID_SESSION_ID)
        self.assertNotIn("module=*", str(caught.exception))

    def test_capabilities_report_hashes_and_never_claims_capacity(self):
        self.registry.activate(self.registry.parse("person_down", "cam-01", enabled_payload()), session_id="s1")
        entry = next(module for module in self.registry.capabilities()["modules"] if module["module"] == "person_down")
        self.assertEqual(entry["factory"], "person_down")
        self.assertEqual(entry["cameras"][0]["capability"], "enabled")
        self.assertEqual(len(entry["cameras"][0]["config_hash"]), 64)
        self.assertNotIn("capacity", str(self.registry.capabilities()).lower())


class RuntimeSeamTests(unittest.TestCase):
    """The seam a runtime consumes: activation_for_camera and perception sharing (ADR-0001)."""

    def setUp(self):
        self.registry = AlertModuleRegistry()
        self.registry.register(PERSON_DOWN)
        self.registry.register(VEHICLE)
        self.registry.register(DANGER)

    def test_disabled_camera_switch_reports_reason_and_no_roi(self):
        self.registry.activate(
            self.registry.parse("vehicle_incident", "cam-01", {"version": 1, "enabled": False, "disabled_reason": "off"}),
            session_id="s1",
        )
        switch = self.registry.activation_for_camera("cam-01", "s1")
        self.assertFalse(switch["analytics_enabled"])
        self.assertIsNone(switch["roi_polygon"])
        self.assertEqual(switch["disabled_modules"], [{"module": "vehicle_incident", "reason": "off"}])
        self.assertIn("vehicle_incident: off", switch["disabled_reason"])

    def test_enabled_camera_switch_exposes_roi_and_factory(self):
        self.registry.activate(self.registry.parse("person_down", "cam-01", enabled_payload()), session_id="s1")
        switch = self.registry.activation_for_camera("cam-01", "s1")
        self.assertTrue(switch["analytics_enabled"])
        self.assertIsNone(switch["disabled_reason"])
        self.assertEqual(switch["roi_polygon"], [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]])
        self.assertEqual(
            switch["modules"],
            [{"module": "person_down", "factory": "person_down", "perception_profile": "person_down"}],
        )
        self.assertEqual(self.registry.active_modules("cam-01"), ("person_down",))
        self.assertEqual(self.registry.active_modules("cam-02"), ())

    def test_modules_sharing_a_perception_profile_are_reported_as_one_group(self):
        self.registry.activate(self.registry.parse("person_down", "cam-01", enabled_payload()), session_id="s1")
        self.registry.activate(
            self.registry.parse("danger_zone", "cam-01", enabled_payload(thresholds={})), session_id="s1"
        )
        self.registry.activate(
            self.registry.parse("vehicle_incident", "cam-01", enabled_payload(thresholds={"motion_delta": 0.2})),
            session_id="s1",
        )
        groups = self.registry.perception_groups()
        self.assertEqual(len(groups), 2)
        shared = next(group for group in groups if group["perception_profile"] == "person_down")
        self.assertEqual(shared["modules"], ["danger_zone", "person_down"])
        self.assertTrue(shared["shared"])
        vehicle = next(group for group in groups if group["perception_profile"] == "vehicle_incident")
        self.assertEqual(vehicle["modules"], ["vehicle_incident"])
        self.assertFalse(vehicle["shared"])


if __name__ == "__main__":
    unittest.main()
