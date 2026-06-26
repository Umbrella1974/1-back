from __future__ import annotations

import csv

from haptic_plan_config import haptic_plan_config_from_dict
from simple_haptic_sender import SimpleHapticSender, SimpleHapticSenderConfig


def test_disabled_sender_records_vibration_without_tcp() -> None:
    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(vibration_enabled=False, matrix_enabled=False),
        session_id="session-a",
        monotonic_ms_fn=lambda: 100.0,
        wall_time_fn=lambda: 0.0,
    )

    record = sender.send_contact(
        haptic_trial_index=2,
        command_label="contact_enter",
        command_id=10,
        duration_ms=150,
        trigger_zone="open_zone",
        trigger_pinch_distance=0.08,
        trigger_frame_index=12,
    )

    assert record.session_id == "session-a"
    assert record.event_name == "contact"
    assert record.command_id == 10
    assert record.vibration_enabled is False
    assert record.tcp_enabled is False
    assert record.tcp_queued is False
    assert record.tcp_success is False
    assert record.send_status == "disabled"
    assert "disabled_mode_no_tcp" in record.note


def test_disabled_sender_records_matrix_channels_from_plan() -> None:
    sender = SimpleHapticSender(session_id="session-b")
    plan = haptic_plan_config_from_dict(
        {
            "plan_id": "p",
            "description": "",
            "events": [
                {
                    "name": "contact",
                    "modality": "vibration",
                    "command_label": "contact_enter",
                    "duration_ms": 1,
                    "trigger_zone": "open_zone",
                    "onset_policy": {"type": "when_enter_zone", "zone": "open_zone"},
                },
                {
                    "name": "left",
                    "modality": "matrix",
                    "channel_list": [1, 2, 3],
                    "duration_ms": 1,
                    "trigger_zone": "closed_zone",
                    "onset_policy": {"type": "after_previous", "gap_ms": 0},
                },
                {
                    "name": "release",
                    "modality": "vibration",
                    "command_label": "contact_exit",
                    "duration_ms": 1,
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

    record = sender.record_plan_event(plan.events[1])

    assert record.event_name == "left"
    assert record.modality == "matrix"
    assert record.channel_list == [1, 2, 3]
    assert record.tcp_enabled is False
    assert record.send_status == "disabled"


def test_disabled_sender_writes_haptic_events_csv(tmp_path) -> None:
    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(visual_text_cue_enabled=True),
        session_id="session-c",
        monotonic_ms_fn=lambda: 200.0,
        wall_time_fn=lambda: 0.0,
    )
    sender.send_matrix_right([5, 6, 7], duration_ms=800)

    path = sender.write_csv(tmp_path / "haptic_events.csv")

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["session_id"] == "session-c"
    assert rows[0]["event_name"] == "right"
    assert rows[0]["channel_list"] == "[5,6,7]"
    assert rows[0]["visual_text_cue_enabled"] == "True"

