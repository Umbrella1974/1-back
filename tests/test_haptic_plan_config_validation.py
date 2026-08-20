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
                "output": {"mode": "hold"},
                "duration_ms": 800,
                "trigger_zone": "closed_zone",
                "onset_policy": {"type": "after_previous", "gap_ms": 100},
            },
            {
                "name": "right",
                "modality": "matrix",
                "channel_list": [5, 6, 7],
                "output": {"mode": "hold"},
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
    assert plan.events[0].name == "contact"
    assert plan.events[-1].name == "release"
    assert len(plan.events) >= 2


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


def test_trial_window_and_wrist_neutral_gate_round_trip() -> None:
    payload = _valid_plan()
    payload["events"][2]["nback_trial_window"] = [20, 25]
    payload["events"][2]["require_wrist_neutral_before_emit"] = True
    payload["events"][2]["wrist_neutral_timeout_ms"] = 3000

    plan = haptic_plan_config_from_dict(payload)
    second = haptic_plan_config_from_dict(plan.to_dict())

    assert second.events[2].nback_trial_window == (20, 25)
    assert second.events[2].require_wrist_neutral_before_emit is True
    assert second.events[2].wrist_neutral_timeout_ms == 3000
    assert second.to_dict()["events"][2]["nback_trial_window"] == [20, 25]


def test_simultaneous_group_round_trips() -> None:
    payload = _valid_plan()
    payload["events"][0]["simultaneous_group"] = "g1"
    payload["events"][1]["simultaneous_group"] = "g1"

    plan = haptic_plan_config_from_dict(payload)
    second = haptic_plan_config_from_dict(plan.to_dict())

    assert second.events[0].simultaneous_group == "g1"
    assert second.events[1].simultaneous_group == "g1"
    assert second.to_dict()["events"][0]["simultaneous_group"] == "g1"


def test_no_zone_event_can_be_parsed_for_timed_grouped_mode() -> None:
    payload = _valid_plan()
    for event in payload["events"]:
        event.pop("trigger_zone", None)
        event.pop("onset_policy", None)
    payload.pop("zones")

    plan = haptic_plan_config_from_dict(payload)

    assert [event.trigger_zone for event in plan.events] == ["", "", "", "", ""]
    assert "zones" in plan.to_dict()
    assert plan.to_dict()["events"][0].get("trigger_zone") is None


def test_matrix_sequence_round_trips() -> None:
    payload = _valid_plan()
    payload["events"][2].pop("channel_list")
    payload["events"][2]["duration_ms"] = 200
    payload["events"][2]["matrix_sequence"] = [
        {"offset_ms": 0, "channel_list": [1, 2, 3]},
        {"offset_ms": 120, "channel_list": [4, 5, 6]},
    ]

    plan = haptic_plan_config_from_dict(payload)
    second = haptic_plan_config_from_dict(plan.to_dict())

    assert second.events[2].matrix_sequence[0].offset_ms == 0
    assert second.events[2].matrix_sequence[0].channel_list == (1, 2, 3)
    assert second.events[2].matrix_sequence[1].offset_ms == 120
    assert second.events[2].to_dict()["matrix_sequence"][1]["channel_list"] == [4, 5, 6]


def test_matrix_sequence_step_label_round_trips() -> None:
    payload = _valid_plan()
    payload["events"][2].pop("channel_list")
    payload["events"][2]["duration_ms"] = 200
    payload["events"][2]["matrix_sequence"] = [
        {"offset_ms": 0, "channel_list": [1, 2, 3], "step_label": "contact_down"},
        {"offset_ms": 120, "channel_list": [4, 5, 6], "step_label": "contact_up"},
    ]

    plan = haptic_plan_config_from_dict(payload)
    second = haptic_plan_config_from_dict(plan.to_dict())

    assert second.events[2].matrix_sequence[0].step_label == "contact_down"
    assert second.events[2].matrix_sequence[1].step_label == "contact_up"
    assert second.to_dict()["events"][2]["matrix_sequence"][0]["step_label"] == "contact_down"


def test_matrix_sequence_step_label_defaults_to_empty() -> None:
    payload = _valid_plan()
    payload["events"][2].pop("channel_list")
    payload["events"][2]["matrix_sequence"] = [{"offset_ms": 0, "channel_list": [1]}]

    plan = haptic_plan_config_from_dict(payload)

    assert plan.events[2].matrix_sequence[0].step_label == ""


def test_matrix_sequence_rejects_unsorted_offsets() -> None:
    payload = _valid_plan()
    payload["events"][2].pop("channel_list")
    payload["events"][2]["matrix_sequence"] = [
        {"offset_ms": 100, "channel_list": [1]},
        {"offset_ms": 50, "channel_list": [2]},
    ]

    with pytest.raises(ValueError, match="offset_ms must be >= previous offset"):
        haptic_plan_config_from_dict(payload)


def test_matrix_sequence_requires_duration_cover_offsets() -> None:
    payload = _valid_plan()
    payload["events"][2].pop("channel_list")
    payload["events"][2]["duration_ms"] = 99
    payload["events"][2]["matrix_sequence"] = [
        {"offset_ms": 0, "channel_list": [1]},
        {"offset_ms": 100, "channel_list": [2]},
    ]

    with pytest.raises(ValueError, match="duration_ms must cover matrix_sequence offsets"):
        haptic_plan_config_from_dict(payload)


def test_matrix_sequence_requires_matrix_modality() -> None:
    payload = _valid_plan()
    payload["events"][1]["matrix_sequence"] = [
        {"offset_ms": 0, "channel_list": [1]},
    ]

    with pytest.raises(ValueError, match="matrix_sequence requires modality: matrix"):
        haptic_plan_config_from_dict(payload)


def test_wrist_neutral_timeout_requires_gate_enabled() -> None:
    payload = _valid_plan()
    payload["events"][2]["wrist_neutral_timeout_ms"] = 3000

    with pytest.raises(
        ValueError,
        match="wrist_neutral_timeout_ms requires require_wrist_neutral_before_emit",
    ):
        haptic_plan_config_from_dict(payload)


def test_wrist_neutral_gate_must_be_boolean() -> None:
    payload = _valid_plan()
    payload["events"][2]["require_wrist_neutral_before_emit"] = "false"

    with pytest.raises(ValueError, match="require_wrist_neutral_before_emit.*true or false"):
        haptic_plan_config_from_dict(payload)


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
                    "output": {"mode": "hold"},
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


def _matrix_output_plan(
    *,
    event_output: dict | None = None,
    matrix_output: dict | None = None,
    channel_list: list[int] | None = None,
    matrix_sequence: list[dict] | None = None,
) -> dict:
    event: dict = {
        "name": "left",
        "modality": "matrix",
        "duration_ms": 800,
        "trigger_zone": "closed_zone",
    }
    if channel_list is not None:
        event["channel_list"] = channel_list
    if matrix_sequence is not None:
        event["matrix_sequence"] = matrix_sequence
    if event_output is not None:
        event["output"] = event_output
    payload = {
        "plan_id": "output_policy",
        "description": "",
        "random_seed": 1,
        "timing": {
            "contact_onset_delay_ms": [0, 0],
            "inter_event_gap_ms": [0, 0],
            "refractory_ms": 0,
        },
        "events": [
            {
                "name": "contact",
                "modality": "vibration",
                "command_label": "contact_enter",
                "command_id": 1,
                "duration_ms": 1,
                "trigger_zone": "open_zone",
            },
            event,
            {
                "name": "release",
                "modality": "vibration",
                "command_label": "contact_exit",
                "command_id": 2,
                "duration_ms": 1,
                "trigger_zone": "closed_zone",
            },
        ],
        "zones": {
            "open_zone": {"lower": "auto_a", "upper": "auto_max"},
            "closed_zone": {"lower": "auto_min", "upper": "auto_a"},
        },
    }
    if matrix_output is not None:
        payload["matrix_output"] = matrix_output
    return payload


def test_matrix_output_auto_off_requires_duration_ms() -> None:
    with pytest.raises(ValueError, match="auto_off mode requires duration_ms"):
        haptic_plan_config_from_dict(
            _matrix_output_plan(event_output={"mode": "auto_off"})
        )


def test_matrix_output_alternate_requires_step_ms() -> None:
    with pytest.raises(ValueError, match="alternate mode requires step_ms"):
        haptic_plan_config_from_dict(
            _matrix_output_plan(
                event_output={"mode": "alternate"},
                matrix_sequence=[
                    {"offset_ms": 0, "channel_list": [1, 2]},
                ],
            )
        )


def test_matrix_output_hold_rejects_extra_fields() -> None:
    with pytest.raises(ValueError, match="hold mode does not take"):
        haptic_plan_config_from_dict(
            _matrix_output_plan(event_output={"mode": "hold", "duration_ms": 650})
        )


def test_matrix_output_auto_off_rejects_step_ms() -> None:
    with pytest.raises(ValueError, match="auto_off mode does not take step_ms"):
        haptic_plan_config_from_dict(
            _matrix_output_plan(
                event_output={"mode": "auto_off", "duration_ms": 650, "step_ms": 100}
            )
        )


def test_matrix_output_alternate_rejects_duration_ms() -> None:
    with pytest.raises(ValueError, match="alternate mode does not take duration_ms"):
        haptic_plan_config_from_dict(
            _matrix_output_plan(
                event_output={"mode": "alternate", "step_ms": 100, "duration_ms": 650},
                matrix_sequence=[{"offset_ms": 0, "channel_list": [1, 2]}],
            )
        )


def test_matrix_output_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError, match="must be one of"):
        haptic_plan_config_from_dict(
            _matrix_output_plan(event_output={"mode": "blink"})
        )


def test_matrix_output_unknown_key_rejected() -> None:
    with pytest.raises(ValueError, match="unknown"):
        haptic_plan_config_from_dict(
            _matrix_output_plan(event_output={"mode": "hold", "loop": True})
        )


@pytest.mark.parametrize("duration_ms", [30, 1600, 0, -50])
def test_matrix_output_auto_off_invalid_duration(duration_ms: int) -> None:
    with pytest.raises(ValueError):
        haptic_plan_config_from_dict(
            _matrix_output_plan(
                event_output={"mode": "auto_off", "duration_ms": duration_ms}
            )
        )


def test_matrix_output_on_non_matrix_event_rejected() -> None:
    payload = _matrix_output_plan(channel_list=[1, 2, 3])
    payload["events"][0]["output"] = {"mode": "hold"}  # contact is vibration
    with pytest.raises(ValueError, match="output is only valid on matrix events"):
        haptic_plan_config_from_dict(payload)


def test_matrix_output_single_channel_alternate_rejected() -> None:
    with pytest.raises(ValueError, match="cannot use alternate mode"):
        haptic_plan_config_from_dict(
            _matrix_output_plan(
                event_output={"mode": "alternate", "step_ms": 100},
                channel_list=[1, 2, 3],
            )
        )


def test_matrix_output_default_resolves_onto_single_channel_event() -> None:
    plan = haptic_plan_config_from_dict(
        _matrix_output_plan(
            matrix_output={"default": {"mode": "auto_off", "duration_ms": 650}},
            channel_list=[1, 2, 3],
        )
    )
    assert plan.events[1].output.mode == "auto_off"
    assert plan.events[1].output.duration_ms == 650


def test_matrix_output_default_requires_default_key() -> None:
    with pytest.raises(ValueError, match="matrix_output.default is required"):
        haptic_plan_config_from_dict(
            _matrix_output_plan(matrix_output={})
        )


def test_matrix_output_unknown_top_level_key_rejected() -> None:
    with pytest.raises(ValueError, match="unknown matrix_output keys"):
        haptic_plan_config_from_dict(
            _matrix_output_plan(matrix_output={"global": {"mode": "hold"}})
        )


def test_matrix_output_alternate_run_inherits_continuation_steps() -> None:
    plan = haptic_plan_config_from_dict(
        _matrix_output_plan(
            matrix_sequence=[
                {
                    "offset_ms": 0,
                    "channel_list": [1, 2],
                    "output": {"mode": "alternate", "step_ms": 100},
                },
                {"channel_list": [3, 4]},
                {"channel_list": [5, 6]},
            ]
        )
    )
    steps = plan.events[1].matrix_sequence
    assert [step.output.mode for step in steps] == ["alternate", "alternate", "alternate"]
    assert all(step.output.step_ms == 100 for step in steps)
