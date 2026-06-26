from __future__ import annotations

import csv

from haptic_plan_config import haptic_plan_config_from_dict
from haptic_trial_scheduler import HapticTrialScheduler, HapticTrialSchedulerConfig
from simple_haptic_sender import SimpleHapticSender


def test_scheduler_events_are_recorded_to_disabled_sender_csv(tmp_path) -> None:
    plan = haptic_plan_config_from_dict(
        {
            "plan_id": "dry_run_plan",
            "description": "",
            "random_seed": 1,
            "timing": {
                "contact_onset_delay_ms": [0, 0],
                "inter_event_gap_ms": [10, 10],
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
                },
                {
                    "name": "slip",
                    "modality": "vibration",
                    "command_label": "slip_start",
                    "command_id": 3,
                    "duration_ms": 800,
                    "trigger_zone": "closed_zone",
                },
                {
                    "name": "left",
                    "modality": "matrix",
                    "channel_list": [1, 2, 3],
                    "duration_ms": 800,
                    "trigger_zone": "closed_zone",
                },
                {
                    "name": "right",
                    "modality": "matrix",
                    "channel_list": [5, 6, 7],
                    "duration_ms": 800,
                    "trigger_zone": "closed_zone",
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
    scheduler = HapticTrialScheduler(
        plan,
        HapticTrialSchedulerConfig(
            avoid_haptic_on_digit_onset=True,
            digit_onset_guard_ms=150,
            max_haptic_delay_ms=500,
        ),
    )
    sender = SimpleHapticSender(
        session_id="dry-session",
        monotonic_ms_fn=lambda: 42.0,
        wall_time_fn=lambda: 0.0,
    )

    scheduled_events = []
    scheduled_events.extend(
        scheduler.update(
            zone="open_zone",
            now_ms=1000.0,
            pinch_distance=0.08,
            frame_index=1,
            digit_onsets_ms=[1000.0],
        )
    )
    scheduled_events.extend(
        scheduler.update(
            zone="open_zone",
            now_ms=1150.0,
            pinch_distance=0.08,
            frame_index=2,
            digit_onsets_ms=[1000.0],
        )
    )
    scheduler.update(zone="closed_zone", now_ms=1151.0, pinch_distance=0.02, frame_index=3)
    for now_ms, frame_index in (
        (1310.0, 4),
        (2120.0, 5),
        (2930.0, 6),
        (3740.0, 7),
    ):
        scheduled_events.extend(
            scheduler.update(
                zone="closed_zone",
                now_ms=now_ms,
                pinch_distance=0.02,
                frame_index=frame_index,
            )
        )

    for event in scheduled_events:
        sender.record_scheduled_event(event)
    path = sender.write_csv(tmp_path / "haptic_events.csv")

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert [row["event_name"] for row in rows] == [
        "contact",
        "slip",
        "left",
        "right",
        "release",
    ]
    assert rows[2]["channel_list"] == "[1,2,3]"
    assert rows[3]["channel_list"] == "[5,6,7]"
    assert rows[0]["sampled_delay_ms"] == "0"
    assert all(row["sampled_gap_ms"] == "10" for row in rows[1:])
    assert all(row["original_planned_onset_ms"] for row in rows)
    assert all(row["adjusted_onset_ms"] for row in rows)
    assert rows[0]["original_planned_onset_ms"] == "1000.0"
    assert rows[0]["adjusted_onset_ms"] == "1150.0"
    assert rows[0]["onset_was_delayed"] == "True"
    assert rows[0]["actual_zone_at_emit"] == "open_zone"
    assert all(row["actual_zone_at_emit"] == "closed_zone" for row in rows[1:])
    assert all(row["tcp_enabled"] == "False" for row in rows)
    assert all(row["send_status"] == "disabled" for row in rows)
    assert all(row["session_id"] == "dry-session" for row in rows)
