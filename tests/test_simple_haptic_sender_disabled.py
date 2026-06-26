from __future__ import annotations

import csv
from types import SimpleNamespace

import pytest
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


@pytest.mark.parametrize(
    ("event_name", "expected_sender"),
    [
        ("contact", "send_contact"),
        ("release", "send_release"),
        ("slip", "send_slip"),
        ("left", "send_matrix_left"),
        ("right", "send_matrix_right"),
    ],
)
def test_record_scheduled_event_dispatches_to_public_send_methods(
    event_name: str,
    expected_sender: str,
) -> None:
    class TrackingSender(SimpleHapticSender):
        def __init__(self) -> None:
            super().__init__(session_id="session-dispatch")
            self.called_sender = ""

        def send_contact(self, **kwargs):
            self.called_sender = "send_contact"
            return super().send_contact(**kwargs)

        def send_release(self, **kwargs):
            self.called_sender = "send_release"
            return super().send_release(**kwargs)

        def send_slip(self, **kwargs):
            self.called_sender = "send_slip"
            return super().send_slip(**kwargs)

        def send_matrix_left(self, channel_list, **kwargs):
            self.called_sender = "send_matrix_left"
            return super().send_matrix_left(channel_list, **kwargs)

        def send_matrix_right(self, channel_list, **kwargs):
            self.called_sender = "send_matrix_right"
            return super().send_matrix_right(channel_list, **kwargs)

    scheduled = SimpleNamespace(
        haptic_trial_index=0,
        event_index=0,
        event_name=event_name,
        modality="matrix" if event_name in {"left", "right"} else "vibration",
        command_label="contact_enter" if event_name == "contact" else None,
        command_id=1 if event_name == "contact" else None,
        channel_list=(1, 2, 3),
        duration_ms=150,
        trigger_zone="open_zone",
        trigger_pinch_distance=0.08,
        trigger_frame_index=1,
        original_planned_onset_ms=1000.0,
        adjusted_onset_ms=1000.0,
        nearest_digit_onset_ms=None,
        digit_onset_delta_ms=None,
        onset_was_delayed=False,
        sync_warning="",
        sampled_delay_ms=10 if event_name == "contact" else None,
        sampled_gap_ms=None if event_name == "contact" else 20,
    )
    sender = TrackingSender()

    record = sender.record_scheduled_event(scheduled)

    assert sender.called_sender == expected_sender
    assert record.event_name == event_name
