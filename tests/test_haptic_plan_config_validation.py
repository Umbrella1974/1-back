from __future__ import annotations

import copy

import pytest
import yaml

from haptic_plan_config import haptic_plan_config_from_dict, load_haptic_plan_config


def _valid_plan() -> dict:
    return {
        "plan_id": "plan_001",
        "description": "phase one validation plan",
        "random_seed": 123,
        "timing": {
            "contact_onset_delay_ms": [500, 2000],
            "inter_event_gap_ms": [300, 1000],
            "refractory_ms": 3000,
        },
        "events": [
            {
                "name": "contact",
                "modality": "vibration",
                "command_label": "contact_enter",
                "command_id": 11,
                "duration_ms": 150,
                "trigger_zone": "open_zone",
                "onset_delay_ms": [600, 700],
                "onset_policy": {"type": "when_enter_zone", "zone": "open_zone"},
            },
            {
                "name": "slip",
                "modality": "vibration",
                "command_label": "slip_start",
                "command_id": 33,
                "duration_ms": 800,
                "trigger_zone": "closed_zone",
                "onset_gap_after_previous_ms": [350, 450],
                "onset_policy": {
                    "type": "after_zone_transition",
                    "from_zone": "open_zone",
                    "to_zone": "closed_zone",
                },
            },
            {
                "name": "left",
                "modality": "matrix",
                "channel_list": [9, 8, 7],
                "duration_ms": 800,
                "trigger_zone": "closed_zone",
                "onset_policy": {"type": "after_previous", "gap_ms": 100},
            },
            {
                "name": "right",
                "modality": "matrix",
                "channel_list": [5, 6, 7],
                "duration_ms": 800,
                "trigger_zone": "closed_zone",
                "onset_policy": {"type": "after_previous", "gap_ms": 100},
            },
            {
                "name": "release",
                "modality": "vibration",
                "command_label": "contact_exit",
                "command_id": 22,
                "duration_ms": 150,
                "trigger_zone": "closed_zone",
                "onset_policy": {"type": "after_previous", "gap_ms": 100},
            },
        ],
        "zones": {
            "open_zone": {"lower": "auto_a", "upper": "auto_max"},
            "closed_zone": {"lower": "auto_min", "upper": "auto_a"},
        },
    }


def test_valid_plan_preserves_commands_and_matrix_channels() -> None:
    plan = haptic_plan_config_from_dict(_valid_plan())

    assert plan.plan_id == "plan_001"
    assert plan.timing.contact_onset_delay_ms == (500, 2000)
    assert plan.timing.inter_event_gap_ms == (300, 1000)
    assert plan.timing.refractory_ms == 3000
    assert plan.events[0].name == "contact"
    assert plan.events[0].command_id == 11
    assert plan.events[0].onset_delay_ms == (600, 700)
    assert plan.events[1].command_id == 33
    assert plan.events[1].onset_gap_after_previous_ms == (350, 450)
    assert plan.events[2].name == "left"
    assert plan.events[2].channel_list == (9, 8, 7)
    assert plan.events[-1].command_label == "contact_exit"
    assert plan.events[-1].command_id == 22


def test_loads_yaml_plan(tmp_path) -> None:
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(_valid_plan(), sort_keys=False), encoding="utf-8")

    plan = load_haptic_plan_config(path)

    assert plan.random_seed == 123
    assert plan.zones["open_zone"].lower == "auto_a"


def test_repository_example_yaml_loads() -> None:
    plan = load_haptic_plan_config("haptic_plan_config_example.yaml")

    assert plan.timing.refractory_ms == 3000
    assert [event.name for event in plan.events] == [
        "contact",
        "slip",
        "left",
        "right",
        "release",
    ]


def test_first_event_must_be_contact() -> None:
    payload = _valid_plan()
    payload["events"][0], payload["events"][1] = payload["events"][1], payload["events"][0]

    with pytest.raises(ValueError, match="first haptic plan event must be contact"):
        haptic_plan_config_from_dict(payload)


def test_last_event_must_be_release() -> None:
    payload = _valid_plan()
    payload["events"][-1] = copy.deepcopy(payload["events"][2])

    with pytest.raises(ValueError, match="last haptic plan event must be release"):
        haptic_plan_config_from_dict(payload)


def test_invalid_matrix_channel_is_rejected() -> None:
    payload = _valid_plan()
    payload["events"][2]["channel_list"] = [1, 128]

    with pytest.raises(ValueError, match="0..127"):
        haptic_plan_config_from_dict(payload)


def test_vibration_event_requires_plan_command_not_hardcoded_default() -> None:
    payload = _valid_plan()
    payload["events"][0].pop("command_id")
    payload["events"][0].pop("command_label")

    with pytest.raises(ValueError, match="requires command_label or command_id"):
        haptic_plan_config_from_dict(payload)


def test_timing_is_required() -> None:
    payload = _valid_plan()
    payload.pop("timing")

    with pytest.raises(ValueError, match="timing is required"):
        haptic_plan_config_from_dict(payload)


def test_invalid_timing_range_is_rejected() -> None:
    payload = _valid_plan()
    payload["timing"]["contact_onset_delay_ms"] = [200, 100]

    with pytest.raises(ValueError, match=r"contact_onset_delay_ms.*<=.*"):
        haptic_plan_config_from_dict(payload)

    payload = _valid_plan()
    payload["timing"]["inter_event_gap_ms"] = [0, -1]

    with pytest.raises(ValueError, match="non-negative"):
        haptic_plan_config_from_dict(payload)

    payload = _valid_plan()
    payload["timing"]["inter_event_gap_ms"] = [100]

    with pytest.raises(ValueError, match="two-item"):
        haptic_plan_config_from_dict(payload)


def test_invalid_event_range_is_rejected() -> None:
    payload = _valid_plan()
    payload["events"][0]["onset_delay_ms"] = [700, 600]

    with pytest.raises(ValueError, match=r"onset_delay_ms.*<=.*"):
        haptic_plan_config_from_dict(payload)

    payload = _valid_plan()
    payload["events"][1]["onset_gap_after_previous_ms"] = ["bad", 600]

    with pytest.raises(ValueError, match="integer"):
        haptic_plan_config_from_dict(payload)


def test_to_dict_round_trips_timing_and_event_ranges() -> None:
    first = haptic_plan_config_from_dict(_valid_plan())
    second = haptic_plan_config_from_dict(first.to_dict())

    assert second.to_dict() == first.to_dict()


def test_vibration_end_command_round_trips() -> None:
    payload = _valid_plan()
    payload["events"][1]["end_command_label"] = "slip_end"
    payload["events"][1]["end_command_id"] = 4

    plan = haptic_plan_config_from_dict(payload)
    second = haptic_plan_config_from_dict(plan.to_dict())

    assert second.events[1].end_command_label == "slip_end"
    assert second.events[1].end_command_id == 4
    assert second.to_dict()["events"][1]["end_command_id"] == 4


def test_matrix_event_rejects_end_command_id() -> None:
    payload = _valid_plan()
    payload["events"][2]["end_command_id"] = 4

    with pytest.raises(ValueError, match="matrix event cannot use end_command_id"):
        haptic_plan_config_from_dict(payload)


def test_scheduler_timing_schema_can_omit_onset_policy() -> None:
    plan = haptic_plan_config_from_dict(
        {
            "plan_id": "plan_timing",
            "description": "",
            "timing": {
                "contact_onset_delay_ms": [500, 2000],
                "inter_event_gap_ms": [300, 1000],
                "refractory_ms": 3000,
            },
            "events": [
                {
                    "name": "contact",
                    "modality": "vibration",
                    "command_label": "contact_enter",
                    "command_id": 1,
                    "duration_ms": 150,
                    "trigger_zone": "open_zone",
                    "onset_delay_ms": [600, 700],
                },
                {
                    "name": "left",
                    "modality": "matrix",
                    "channel_list": [1, 2, 3],
                    "duration_ms": 800,
                    "trigger_zone": "closed_zone",
                    "onset_gap_after_previous_ms": [350, 450],
                },
                {
                    "name": "release",
                    "modality": "vibration",
                    "command_label": "contact_exit",
                    "command_id": 2,
                    "duration_ms": 150,
                    "trigger_zone": "closed_zone",
                },
            ],
            "zones": {
                "open_zone": {"lower": "auto_a", "upper": "auto_max"},
                "closed_zone": {"lower": "auto_min", "upper": "auto_a"},
            },
        }
    )

    assert plan.timing.contact_onset_delay_ms == (500, 2000)
    assert plan.timing.inter_event_gap_ms == (300, 1000)
    assert plan.timing.refractory_ms == 3000
    assert plan.events[0].onset_policy.type == "when_enter_zone"
    assert plan.events[0].onset_delay_ms == (600, 700)
    assert plan.events[1].onset_policy.type == "after_previous"
    assert plan.events[1].onset_gap_after_previous_ms == (350, 450)
