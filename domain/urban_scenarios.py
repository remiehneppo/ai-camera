"""Canonical definitions for all 14 CiviWatch Urban Safety Scenarios (US01–US14).

Pure domain module with zero I/O or third-party dependencies.
Maps each requirement scenario (US01–US14) from docs/requirements/urban-safety-scenarios.md
to its canonical factory name, taxonomies, default severity, anchor policy, tunable thresholds,
and hard-negative classes for Tier-2 VLM verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, FrozenSet, Mapping, Tuple

__all__ = [
    "ALL_SCENARIO_FACTORIES",
    "ALL_URBAN_TAXONOMIES",
    "SCENARIO_BY_FACTORY",
    "SCENARIO_BY_ID",
    "SCENARIO_SPECS",
    "UrbanScenarioSpec",
    "get_scenario_for_taxonomy",
]


@dataclass(frozen=True)
class UrbanScenarioSpec:
    """Immutable specification of one urban safety scenario group."""

    scenario_id: str
    code: str
    title_vi: str
    factory: str
    taxonomies: Tuple[str, ...]
    default_severity: str
    anchor_kind: str
    tunable_thresholds: FrozenSet[str]
    hard_negatives: Tuple[str, ...]


SCENARIO_SPECS: Final[Tuple[UrbanScenarioSpec, ...]] = (
    UrbanScenarioSpec(
        scenario_id="US01",
        code="fire_smoke_suspected",
        title_vi="Cháy / khói nghi ngờ",
        factory="fire_smoke_suspected",
        taxonomies=("fire_suspected", "smoke_suspected", "fire_smoke_suspected"),
        default_severity="critical",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "min_persistence_seconds",
            "cooldown_seconds",
            "max_observation_gap",
            "fire_ratio_threshold",
            "smoke_ratio_threshold",
            "min_score",
        }),
        hard_negatives=("steam_or_mist", "vehicle_headlight_glare", "dust_cloud", "authorized_heat_source"),
    ),
    UrbanScenarioSpec(
        scenario_id="US02",
        code="urban_flooding",
        title_vi="Ngập nước đô thị vượt mốc",
        factory="urban_flooding",
        taxonomies=("urban_flooding",),
        default_severity="high",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "min_persistence_seconds",
            "cooldown_seconds",
            "max_observation_gap",
            "water_coverage_threshold",
            "min_score",
        }),
        hard_negatives=("wet_road_surface", "small_puddle", "sky_reflection"),
    ),
    UrbanScenarioSpec(
        scenario_id="US03",
        code="illegal_dumping",
        title_vi="Đổ trộm / tồn lưu rác sai quy định",
        factory="illegal_dumping",
        taxonomies=("illegal_dumping_action", "unlawful_waste_accumulation", "illegal_dumping"),
        default_severity="medium",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "min_dwell_seconds",
            "separation_distance_px",
            "cooldown_seconds",
            "max_observation_gap",
            "min_score",
        }),
        hard_negatives=("authorized_waste_collection", "passerby_near_existing_waste", "scheduled_pickup"),
    ),
    UrbanScenarioSpec(
        scenario_id="US04",
        code="sidewalk_encroachment",
        title_vi="Lấn chiếm vỉa hè / hành lang thông thoáng",
        factory="sidewalk_encroachment",
        taxonomies=("sidewalk_encroachment",),
        default_severity="medium",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "min_dwell_seconds",
            "min_object_count",
            "cooldown_seconds",
            "max_observation_gap",
            "min_score",
        }),
        hard_negatives=("pedestrian_walking_through", "permitted_sidewalk_activity"),
    ),
    UrbanScenarioSpec(
        scenario_id="US05",
        code="illegal_parking",
        title_vi="Đỗ xe sai vùng / khung giờ",
        factory="illegal_parking",
        taxonomies=("illegal_parking",),
        default_severity="medium",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "max_dwell_seconds",
            "stationary_speed_threshold",
            "stationary_displacement_threshold",
            "max_observation_gap",
            "cooldown_seconds",
            "min_score",
        }),
        hard_negatives=("red_light_waiting", "traffic_congestion_queue", "brief_legal_stop"),
    ),
    UrbanScenarioSpec(
        scenario_id="US06",
        code="crowd_incident",
        title_vi="Tụ tập đông người & Nghi gây rối trật tự",
        factory="crowd_incident",
        taxonomies=("crowd_concentration", "suspected_disorder"),
        default_severity="high",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "min_crowd_count",
            "min_duration_seconds",
            "min_disorder_count",
            "disorder_speed_threshold",
            "disorder_acceleration_threshold",
            "disorder_dispersal_threshold",
            "disorder_direction_variance_threshold",
            "max_observation_gap",
            "cooldown_seconds",
        }),
        hard_negatives=("bus_stop_queue", "orderly_event_gathering", "single_jogger"),
    ),
    UrbanScenarioSpec(
        scenario_id="US07",
        code="violent_altercation",
        title_vi="Nghi ngờ ẩu đả / tương tác bạo lực",
        factory="violent_altercation",
        taxonomies=("violent_altercation",),
        default_severity="critical",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "min_interaction_seconds",
            "proximity_distance_px",
            "motion_energy_threshold",
            "cooldown_seconds",
            "max_observation_gap",
            "min_score",
        }),
        hard_negatives=("sports_activity", "friendly_greeting_or_hug", "helping_fallen_person"),
    ),
    UrbanScenarioSpec(
        scenario_id="US08",
        code="vehicle_incident",
        title_vi="Tai nạn giao thông có phương tiện",
        factory="vehicle_incident",
        taxonomies=("vehicle_vehicle", "vehicle_pedestrian", "vehicle_rollover_or_barrier", "vehicle_incident"),
        default_severity="critical",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "max_observation_gap",
            "cooldown_seconds",
            "min_moving_speed",
            "stationary_speed",
            "impact_deceleration_threshold",
            "deflection_threshold",
            "two_wheeler_rollover_ar",
            "two_wheeler_upright_ar",
            "car_rollover_ar_delta",
            "pedestrian_drop_velocity",
            "pedestrian_lying_ar",
            "proximity_distance",
        }),
        hard_negatives=("perspective_bbox_overlap", "normal_lane_merge", "stationary_parked_vehicle"),
    ),
    UrbanScenarioSpec(
        scenario_id="US09",
        code="person_down",
        title_vi="Người ngã / nằm bất động trên đường",
        factory="person_down",
        taxonomies=("person_fall", "person_lying_persistent", "person_on_stationary_vehicle"),
        default_severity="critical",
        anchor_kind="onset",
        tunable_thresholds=frozenset({
            "standing_aspect_ratio",
            "lying_aspect_ratio",
            "min_drop_velocity",
            "min_lying_duration",
            "cooldown_seconds",
            "max_motion_speed",
            "persistent_lying_duration",
            "max_observation_gap",
            "vehicle_upright_aspect_ratio",
            "vehicle_fallen_aspect_ratio",
            "vehicle_stable_duration",
            "vehicle_min_stable_frames",
            "vehicle_overlap_iou",
        }),
        hard_negatives=("crouching_or_tying_shoes", "resting_on_stationary_motorbike", "picking_up_item"),
    ),
    UrbanScenarioSpec(
        scenario_id="US10",
        code="danger_zone",
        title_vi="Xâm nhập vùng nguy hiểm",
        factory="danger_zone",
        taxonomies=("danger_zone_intrusion",),
        default_severity="critical",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "min_dwell_seconds",
            "consecutive_hits",
            "max_observation_gap",
            "cooldown_seconds",
            "min_score",
        }),
        hard_negatives=("outside_roi_passerby", "outside_active_schedule"),
    ),
    UrbanScenarioSpec(
        scenario_id="US11",
        code="abandoned_object",
        title_vi="Vật bỏ quên / tồn lưu bất thường",
        factory="abandoned_object",
        taxonomies=("abandoned_object_dropped", "unattended_object_persistent", "abandoned_object"),
        default_severity="high",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "min_unattended_seconds",
            "owner_separation_px",
            "cooldown_seconds",
            "max_observation_gap",
            "min_score",
        }),
        hard_negatives=("owner_standing_nearby", "fixed_street_furniture", "authorized_cargo"),
    ),
    UrbanScenarioSpec(
        scenario_id="US12",
        code="fallen_tree",
        title_vi="Cây đổ / cành lớn gãy chắn đường",
        factory="fallen_tree",
        taxonomies=("fallen_tree",),
        default_severity="high",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "min_persistence_seconds",
            "min_obstruction_area_ratio",
            "cooldown_seconds",
            "max_observation_gap",
            "min_score",
        }),
        hard_negatives=("tree_shadow_on_road", "upright_swaying_tree", "small_leaf_debris"),
    ),
    UrbanScenarioSpec(
        scenario_id="US13",
        code="streetlight_outage",
        title_vi="Đèn đường hỏng / không sáng trong lịch bật",
        factory="streetlight_outage",
        taxonomies=("streetlight_outage",),
        default_severity="medium",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "min_dark_duration_seconds",
            "luminance_threshold",
            "transition_grace_seconds",
            "cooldown_seconds",
            "max_observation_gap",
        }),
        hard_negatives=("daytime_schedule_off", "sunset_transition_window", "occluded_lamp_head"),
    ),
    UrbanScenarioSpec(
        scenario_id="US14",
        code="property_vandalism",
        title_vi="Nghi ngờ phá hoại tài sản công cộng",
        factory="property_vandalism",
        taxonomies=("property_vandalism",),
        default_severity="high",
        anchor_kind="alert_condition",
        tunable_thresholds=frozenset({
            "min_impact_duration_seconds",
            "motion_spike_threshold",
            "cooldown_seconds",
            "max_observation_gap",
            "min_score",
        }),
        hard_negatives=("authorized_maintenance_work", "routine_cleaning", "normal_facility_use"),
    ),
)

SCENARIO_BY_ID: Final[Mapping[str, UrbanScenarioSpec]] = {
    spec.scenario_id: spec for spec in SCENARIO_SPECS
}

SCENARIO_BY_FACTORY: Final[Mapping[str, UrbanScenarioSpec]] = {
    spec.factory: spec for spec in SCENARIO_SPECS
}

ALL_SCENARIO_FACTORIES: Final[FrozenSet[str]] = frozenset(
    {spec.factory for spec in SCENARIO_SPECS} | {"urban_safety_vlm"}
)

ALL_URBAN_TAXONOMIES: Final[FrozenSet[str]] = frozenset(
    tax for spec in SCENARIO_SPECS for tax in spec.taxonomies
)


def get_scenario_for_taxonomy(taxonomy: str) -> UrbanScenarioSpec | None:
    """Return the UrbanScenarioSpec that owns the given taxonomy, or None."""
    for spec in SCENARIO_SPECS:
        if taxonomy in spec.taxonomies or taxonomy == spec.code:
            return spec
    return None
