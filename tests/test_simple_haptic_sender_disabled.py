from __future__ import annotations

import csv
from types import SimpleNamespace

import pytest
from haptic_plan_config import haptic_plan_config_from_dict
from vendor_exp2_abc.vibration_tcp_worker import VibrationHapticConnectionError
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
        actual_zone_at_emit="open_zone",
        trigger_pinch_distance=0.08,
        trigger_frame_index=12,
    )

    assert record.session_id == "session-a"
    assert record.event_name == "contact"
    assert record.command_id == 10
    assert record.actual_zone_at_emit == "open_zone"
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
        actual_zone_at_emit="open_zone",
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
    assert record.actual_zone_at_emit == "open_zone"


def test_enabled_vibration_sender_queues_vendor_tcp_payload(tmp_path) -> None:
    sent_payloads: list[bytes] = []

    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(
            vibration_enabled=True,
            matrix_enabled=False,
            disabled_mode=False,
            vibration_tcp_enabled=True,
            vibration_socket_factory=_socket_factory(sent_payloads),
        ),
        session_id="tcp-vibration",
        wall_time_fn=lambda: 0.0,
    )

    record = sender.send_contact(duration_ms=150)
    sender.write_csv(tmp_path / "haptic_events.csv")

    assert sent_payloads == [b"1\n"]
    assert record.tcp_enabled is True
    assert record.tcp_queued is True
    assert record.tcp_success is True
    assert record.send_status == "sent"


def test_vibration_end_command_is_polled_when_due(tmp_path) -> None:
    sent_payloads: list[bytes] = []
    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(
            vibration_enabled=True,
            disabled_mode=False,
            vibration_tcp_enabled=True,
            vibration_socket_factory=_socket_factory(sent_payloads),
        ),
        session_id="tcp-end",
        wall_time_fn=lambda: 0.0,
    )
    scheduled = SimpleNamespace(
        haptic_trial_index=0,
        event_index=1,
        event_name="slip",
        modality="vibration",
        command_label="slip_start",
        command_id=3,
        end_command_label="slip_end",
        end_command_id=4,
        duration_ms=1000,
        sampled_duration_ms=1000,
        event_end_monotonic_ms=2000.0,
        trigger_zone="closed_zone",
        actual_zone_at_emit="closed_zone",
        trigger_pinch_distance=0.02,
        trigger_frame_index=10,
        actual_emit_monotonic_ms=1000.0,
        original_planned_onset_ms=1000.0,
        adjusted_onset_ms=1000.0,
        nearest_digit_onset_ms=None,
        digit_onset_delta_ms=None,
        onset_was_delayed=False,
        sync_warning="",
    )

    start_record = sender.record_scheduled_event(scheduled)
    assert sender.poll_due_control_commands(1999.0) == []
    end_records = sender.poll_due_control_commands(2000.0)
    sender.write_csv(tmp_path / "haptic_events.csv")

    assert sent_payloads == [b"3\n", b"4\n"]
    assert len(end_records) == 1
    assert end_records[0].event_name == "slip_end"
    assert end_records[0].source_event_name == "slip"
    assert end_records[0].actual_duration_ms == 1000.0
    assert start_record.end_command_sent is True
    assert start_record.actual_duration_ms == 1000.0


def test_enabled_matrix_sender_queues_vendor_tcp_packet(tmp_path) -> None:
    sent_payloads: list[bytes] = []

    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(
            vibration_enabled=False,
            matrix_enabled=True,
            disabled_mode=False,
            matrix_tcp_enabled=True,
            matrix_socket_factory=_socket_factory(sent_payloads),
        ),
        session_id="tcp-matrix",
        wall_time_fn=lambda: 0.0,
    )

    record = sender.send_matrix_left([1, 2, 3], duration_ms=500)
    sender.write_csv(tmp_path / "haptic_events.csv")

    assert sent_payloads == [b"\xAA\x55\xAA\x55\x03\x01\x02\x03\x06"]
    assert record.tcp_enabled is True
    assert record.tcp_queued is True
    assert record.tcp_success is True
    assert record.send_status == "sent"


def test_tcp_not_required_connection_failure_records_not_connected() -> None:
    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(
            vibration_enabled=True,
            disabled_mode=False,
            vibration_tcp_enabled=True,
            vibration_required=False,
            vibration_socket_factory=_failing_socket_factory,
        ),
        session_id="tcp-warning",
    )

    record = sender.send_contact(command_id=1, duration_ms=150)

    assert record.tcp_enabled is True
    assert record.tcp_queued is False
    assert record.tcp_success is False
    assert record.send_status == "not_connected"
    assert record.not_sent_reason == "not_connected"


def test_tcp_required_connection_failure_raises() -> None:
    with pytest.raises(VibrationHapticConnectionError):
        SimpleHapticSender(
            SimpleHapticSenderConfig(
                vibration_enabled=True,
                disabled_mode=False,
                vibration_tcp_enabled=True,
                vibration_required=True,
                vibration_socket_factory=_failing_socket_factory,
            ),
            session_id="tcp-required",
        )


def test_tcp_channel_disabled_does_not_connect() -> None:
    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(
            vibration_enabled=True,
            disabled_mode=False,
            vibration_tcp_enabled=False,
            vibration_socket_factory=_failing_socket_factory,
        ),
        session_id="tcp-disabled-channel",
    )

    record = sender.send_contact(duration_ms=150)

    assert record.tcp_enabled is False
    assert record.tcp_queued is False
    assert record.send_status == "disabled"
    assert record.not_sent_reason == "vibration_tcp_disabled"


def test_close_stops_and_closes_worker_socket() -> None:
    sockets: list[_FakeSocket] = []

    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(
            vibration_enabled=True,
            disabled_mode=False,
            vibration_tcp_enabled=True,
            vibration_socket_factory=_socket_factory([], sockets=sockets),
        ),
        session_id="tcp-close",
    )

    sender.close()

    assert sockets
    assert sockets[0].closed is True


class _FakeSocket:
    def __init__(self, sent_payloads: list[bytes]) -> None:
        self.sent_payloads = sent_payloads
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendall(self, payload: bytes) -> None:
        self.sent_payloads.append(bytes(payload))

    def close(self) -> None:
        self.closed = True


def _socket_factory(sent_payloads: list[bytes], *, sockets: list[_FakeSocket] | None = None):
    def factory(address, timeout):
        socket = _FakeSocket(sent_payloads)
        if sockets is not None:
            sockets.append(socket)
        return socket

    return factory


def _failing_socket_factory(address, timeout):
    raise OSError("no tcp server")
