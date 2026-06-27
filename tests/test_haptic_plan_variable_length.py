from __future__ import annotations

import pytest

from haptic_plan_config import haptic_plan_config_from_dict
from haptic_trial_scheduler import HapticTrialScheduler


@pytest.mark.parametrize("middle_count", [3, 6, 9])
def test_scheduler_runs_variable_length_middle_events_in_config_order(middle_count: int) -> None:
    names = [
        f"{'left' if index % 2 else 'slip'}_{index + 1}"
        for index in range(middle_count)
    ]
    plan = haptic_plan_config_from_dict(_plan(names))
    scheduler = HapticTrialScheduler(plan)
    emitted = []

    scheduler.update(zone="open_zone", now_ms=1000.0)
    emitted.extend(scheduler.update(zone="open_zone", now_ms=1000.0))
    for now_ms in range(1001, 1001 + middle_count + 2):
        emitted.extend(scheduler.update(zone="closed_zone", now_ms=float(now_ms)))

    assert [event.event_name for event in emitted] == ["contact", *names, "release"]
    assert emitted[-1].haptic_episode_completed is True


def test_first_event_must_still_be_contact() -> None:
    payload = _plan(["slip_1"])
    payload["events"][0], payload["events"][1] = payload["events"][1], payload["events"][0]

    with pytest.raises(ValueError, match="first haptic plan event must be contact"):
        haptic_plan_config_from_dict(payload)


def test_last_event_must_still_be_release() -> None:
    payload = _plan(["slip_1"])
    payload["events"][-1] = payload["events"][1]

    with pytest.raises(ValueError, match="last haptic plan event must be release"):
        haptic_plan_config_from_dict(payload)


def _plan(middle_names: list[str]) -> dict:
    events = [
        {
            "name": "contact",
            "modality": "vibration",
            "command_label": "contact_enter",
            "duration_ms": 1,
            "trigger_zone": "open_zone",
        }
    ]
    for name in middle_names:
        if name.startswith("left"):
            events.append(
                {
                    "name": name,
                    "modality": "matrix",
                    "channel_list": [1, 2, 3],
                    "duration_ms": 1,
                    "trigger_zone": "closed_zone",
                }
            )
        else:
            events.append(
                {
                    "name": name,
                    "modality": "vibration",
                    "command_label": name,
                    "duration_ms": 1,
                    "trigger_zone": "closed_zone",
                }
            )
    events.append(
        {
            "name": "release",
            "modality": "vibration",
            "command_label": "contact_exit",
            "duration_ms": 1,
            "trigger_zone": "closed_zone",
        }
    )
    return {
        "plan_id": "variable_length",
        "description": "",
        "random_seed": 1,
        "timing": {
            "contact_onset_delay_ms": [0, 0],
            "inter_event_gap_ms": [0, 0],
            "refractory_ms": 0,
        },
        "events": events,
        "zones": {
            "open_zone": {"lower": "auto_a", "upper": "auto_max"},
            "closed_zone": {"lower": "auto_min", "upper": "auto_a"},
        },
    }
