from __future__ import annotations

from haptic_plan_config import haptic_plan_config_from_dict
from haptic_trial_scheduler import HapticTrialScheduler


def test_event_missing_duration_uses_global_defaults() -> None:
    scheduler = HapticTrialScheduler(haptic_plan_config_from_dict(_plan()))

    scheduler.update(zone="open_zone", now_ms=1000.0)
    contact = scheduler.update(zone="open_zone", now_ms=1005.0)[0]
    scheduler.update(zone="closed_zone", now_ms=1016.0)
    matrix = scheduler.update(zone="closed_zone", now_ms=1023.0)[0]
    release = scheduler.update(zone="closed_zone", now_ms=1052.0)[0]

    assert contact.duration_ms == 11
    assert contact.sampled_duration_ms == 11
    assert contact.sampled_delay_ms == 5
    assert contact.global_default_used is True
    assert matrix.event_name == "left_1"
    assert matrix.duration_ms == 22
    assert matrix.sampled_gap_ms == 7
    assert matrix.global_default_used is True
    assert release.duration_ms == 11
    assert release.global_default_used is True


def test_event_duration_and_gap_override_global_defaults() -> None:
    payload = _plan()
    payload["events"][1]["duration_ms"] = 99
    payload["events"][1]["onset_gap_after_previous_ms"] = [3, 3]
    scheduler = HapticTrialScheduler(haptic_plan_config_from_dict(payload))

    scheduler.update(zone="open_zone", now_ms=1000.0)
    scheduler.update(zone="open_zone", now_ms=1005.0)
    scheduler.update(zone="closed_zone", now_ms=1016.0)
    matrix = scheduler.update(zone="closed_zone", now_ms=1019.0)[0]

    assert matrix.duration_ms == 99
    assert matrix.sampled_duration_ms == 99
    assert matrix.sampled_gap_ms == 3
    assert matrix.global_default_used is False


def _plan() -> dict:
    return {
        "plan_id": "global_defaults",
        "description": "",
        "random_seed": 1,
        "timing": {
            "contact_onset_delay_ms": [0, 0],
            "inter_event_gap_ms": [0, 0],
            "refractory_ms": 0,
        },
        "haptic_defaults": {
            "vibration_duration_ms": [33, 33],
            "matrix_duration_ms": [22, 22],
            "inter_event_gap_ms": [7, 7],
            "contact_onset_delay_ms": [5, 5],
            "release_duration_ms": [11, 11],
        },
        "events": [
            {
                "name": "contact",
                "modality": "vibration",
                "command_label": "contact_enter",
                "trigger_zone": "open_zone",
            },
            {
                "name": "left_1",
                "modality": "matrix",
                "channel_list": [1, 2, 3],
                "trigger_zone": "closed_zone",
            },
            {
                "name": "release",
                "modality": "vibration",
                "command_label": "contact_exit",
                "trigger_zone": "closed_zone",
            },
        ],
        "zones": {
            "open_zone": {"lower": "auto_a", "upper": "auto_max"},
            "closed_zone": {"lower": "auto_min", "upper": "auto_a"},
        },
    }
