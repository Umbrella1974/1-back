from __future__ import annotations

from haptic_plan_config import haptic_plan_config_from_dict
from haptic_trial_scheduler import (
    PENDING_CONTACT,
    PENDING_PLAN_EVENT,
    REFRACTORY,
    WAIT_CLOSED_ZONE,
    WAIT_OPEN_ZONE,
    HapticTrialScheduler,
)


def _plan(
    *,
    contact_delay: list[int] | None = None,
    event_gap: list[int] | None = None,
    random_seed: int = 123,
) -> object:
    return haptic_plan_config_from_dict(
        {
            "plan_id": "scheduler_plan",
            "description": "",
            "random_seed": random_seed,
            "timing": {
                "contact_onset_delay_ms": contact_delay or [500, 500],
                "inter_event_gap_ms": event_gap or [300, 300],
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
                    "onset_policy": {"type": "when_enter_zone", "zone": "open_zone"},
                },
                {
                    "name": "slip",
                    "modality": "vibration",
                    "command_label": "slip_start",
                    "command_id": 3,
                    "duration_ms": 800,
                    "trigger_zone": "closed_zone",
                    "onset_policy": {
                        "type": "after_zone_transition",
                        "from_zone": "open_zone",
                        "to_zone": "closed_zone",
                    },
                },
                {
                    "name": "left",
                    "modality": "matrix",
                    "channel_list": [1, 2, 3],
                    "duration_ms": 800,
                    "trigger_zone": "closed_zone",
                    "onset_policy": {"type": "after_previous", "gap_ms": 0},
                },
                {
                    "name": "right",
                    "modality": "matrix",
                    "channel_list": [5, 6, 7],
                    "duration_ms": 800,
                    "trigger_zone": "closed_zone",
                    "onset_policy": {"type": "after_previous", "gap_ms": 0},
                },
                {
                    "name": "release",
                    "modality": "vibration",
                    "command_label": "contact_exit",
                    "command_id": 2,
                    "duration_ms": 150,
                    "trigger_zone": "closed_zone",
                    "onset_policy": {"type": "after_previous", "gap_ms": 0},
                },
            ],
            "zones": {
                "open_zone": {"lower": "auto_a", "upper": "auto_max"},
                "closed_zone": {"lower": "auto_min", "upper": "auto_a"},
            },
        }
    )


def test_scheduler_state_machine_runs_plan_after_delays() -> None:
    scheduler = HapticTrialScheduler(_plan())

    assert scheduler.state == WAIT_OPEN_ZONE
    assert scheduler.update(zone="closed_zone", now_ms=0.0) == []
    assert scheduler.state == WAIT_OPEN_ZONE

    assert scheduler.update(zone="open_zone", now_ms=1000.0) == []
    assert scheduler.state == PENDING_CONTACT
    assert scheduler.update(zone="open_zone", now_ms=1499.0) == []

    contact = scheduler.update(
        zone="open_zone",
        now_ms=1500.0,
        pinch_distance=0.08,
        frame_index=10,
    )[0]

    assert contact.event_name == "contact"
    assert contact.event_index == 0
    assert contact.haptic_trial_index == 0
    assert contact.original_planned_onset_ms == 1500.0
    assert contact.adjusted_onset_ms == 1500.0
    assert contact.sampled_delay_ms == 500
    assert contact.duration_ms == 150
    assert contact.trigger_zone == "open_zone"
    assert contact.trigger_pinch_distance == 0.08
    assert contact.trigger_frame_index == 10
    assert scheduler.state == WAIT_CLOSED_ZONE

    assert scheduler.update(zone="open_zone", now_ms=1600.0) == []
    assert scheduler.state == WAIT_CLOSED_ZONE
    assert scheduler.update(zone="closed_zone", now_ms=1700.0) == []
    assert scheduler.state == PENDING_PLAN_EVENT
    assert scheduler.update(zone="closed_zone", now_ms=1949.0) == []

    slip = scheduler.update(zone="open_zone", now_ms=1950.0)[0]
    assert slip.event_name == "slip"
    assert slip.sampled_gap_ms == 300
    assert slip.duration_ms == 800
    assert scheduler.state == PENDING_PLAN_EVENT

    left = scheduler.update(zone="open_zone", now_ms=3050.0)[0]
    right = scheduler.update(zone="open_zone", now_ms=4150.0)[0]
    release = scheduler.update(zone="open_zone", now_ms=5250.0)[0]

    assert [event.event_name for event in (slip, left, right, release)] == [
        "slip",
        "left",
        "right",
        "release",
    ]
    assert left.channel_list == (1, 2, 3)
    assert right.channel_list == (5, 6, 7)
    assert release.event_index == 4
    assert release.command_label == "contact_exit"
    assert scheduler.state == REFRACTORY

    assert scheduler.update(zone="open_zone", now_ms=6000.0) == []
    assert scheduler.state == REFRACTORY
    assert scheduler.update(zone="open_zone", now_ms=8400.0) == []
    assert scheduler.state == PENDING_CONTACT
    next_contact = scheduler.update(zone="open_zone", now_ms=8900.0)[0]
    assert next_contact.event_name == "contact"
    assert next_contact.haptic_trial_index == 1


def test_pending_contact_is_cancelled_when_hand_leaves_open_zone() -> None:
    scheduler = HapticTrialScheduler(_plan())

    scheduler.update(zone="open_zone", now_ms=1000.0)
    assert scheduler.state == PENDING_CONTACT
    assert scheduler.update(zone="closed_zone", now_ms=1200.0) == []

    assert scheduler.state == WAIT_OPEN_ZONE
    assert scheduler.update(zone="open_zone", now_ms=1300.0) == []
    assert scheduler.state == PENDING_CONTACT


def test_per_event_gap_overrides_timing_default() -> None:
    payload = _plan().to_dict()
    payload["timing"]["inter_event_gap_ms"] = [999, 999]
    payload["events"][1]["onset_gap_after_previous_ms"] = [111, 111]
    plan = haptic_plan_config_from_dict(payload)
    scheduler = HapticTrialScheduler(plan)

    scheduler.update(zone="open_zone", now_ms=1000.0)
    scheduler.update(zone="open_zone", now_ms=1500.0)
    scheduler.update(zone="closed_zone", now_ms=1600.0)
    slip = scheduler.update(zone="closed_zone", now_ms=1761.0)[0]

    assert slip.event_name == "slip"
    assert slip.sampled_gap_ms == 111


def test_contact_delay_can_be_overridden_per_event() -> None:
    payload = _plan().to_dict()
    payload["timing"]["contact_onset_delay_ms"] = [999, 999]
    payload["events"][0]["onset_delay_ms"] = [222, 222]
    plan = haptic_plan_config_from_dict(payload)
    scheduler = HapticTrialScheduler(plan)

    scheduler.update(zone="open_zone", now_ms=1000.0)
    assert scheduler.update(zone="open_zone", now_ms=1221.0) == []
    contact = scheduler.update(zone="open_zone", now_ms=1222.0)[0]

    assert contact.event_name == "contact"
    assert contact.sampled_delay_ms == 222


def test_random_seed_makes_sampled_timing_reproducible() -> None:
    first = HapticTrialScheduler(_plan(contact_delay=[10, 20], event_gap=[30, 40]))
    second = HapticTrialScheduler(_plan(contact_delay=[10, 20], event_gap=[30, 40]))

    first.update(zone="open_zone", now_ms=1000.0)
    second.update(zone="open_zone", now_ms=1000.0)
    first_contact = first.update(zone="open_zone", now_ms=2000.0)[0]
    second_contact = second.update(zone="open_zone", now_ms=2000.0)[0]
    first.update(zone="closed_zone", now_ms=2100.0)
    second.update(zone="closed_zone", now_ms=2100.0)
    first_slip = first.update(zone="closed_zone", now_ms=3000.0)[0]
    second_slip = second.update(zone="closed_zone", now_ms=3000.0)[0]

    assert first_contact.sampled_delay_ms == second_contact.sampled_delay_ms
    assert first_slip.sampled_gap_ms == second_slip.sampled_gap_ms
