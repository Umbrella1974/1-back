from __future__ import annotations

import csv
from types import SimpleNamespace

import pytest

from simple_haptic_sender import (
    HAPTIC_EVENT_FIELDS,
    SimpleHapticSender,
    SimpleHapticSenderConfig,
)
from vendor_exp2_abc.vibration_tcp_worker import VibrationHapticConnectionError


def test_vibration_end_command_tcp_smoke(tmp_path) -> None:
    sent_payloads: list[bytes] = []
    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(
            vibration_enabled=True,
            disabled_mode=False,
            vibration_tcp_enabled=True,
            vibration_socket_factory=_socket_factory(sent_payloads),
        ),
        session_id="tcp-smoke",
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

    sender.record_scheduled_event(scheduled)
    sender.poll_due_control_commands(2000.0)
    sender.write_csv(tmp_path / "haptic_events.csv")

    assert sent_payloads == [b"3\n", b"4\n"]
    assert [record.event_name for record in sender.records] == ["slip", "slip_end"]


def test_vibration_tcp_handshake_sends_ping_before_commands(tmp_path) -> None:
    sent_payloads: list[bytes] = []
    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(
            vibration_enabled=True,
            disabled_mode=False,
            vibration_tcp_enabled=True,
            vibration_handshake_enabled=True,
            vibration_socket_factory=_socket_factory(sent_payloads, response=b"OK PONG\n"),
        ),
        session_id="tcp-handshake",
        wall_time_fn=lambda: 0.0,
    )

    sender.send_contact(command_id=1)
    sender.write_csv(tmp_path / "haptic_events.csv")

    assert sent_payloads == [b"PING\n", b"1\n"]


def test_vibration_tcp_handshake_rejects_unexpected_response() -> None:
    with pytest.raises(VibrationHapticConnectionError):
        SimpleHapticSender(
            SimpleHapticSenderConfig(
                vibration_enabled=True,
                disabled_mode=False,
                vibration_tcp_enabled=True,
                vibration_required=True,
                vibration_handshake_enabled=True,
                vibration_socket_factory=_socket_factory([], response=b"ERR\n"),
            ),
            session_id="tcp-handshake-fail",
            wall_time_fn=lambda: 0.0,
        )


class _FakeSocket:
    def __init__(self, sent_payloads: list[bytes], response: bytes = b"") -> None:
        self.sent_payloads = sent_payloads
        self.response = response
        self.response_sent = False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendall(self, payload: bytes) -> None:
        self.sent_payloads.append(bytes(payload))

    def recv(self, size: int) -> bytes:
        if self.response_sent:
            return b""
        self.response_sent = True
        return self.response[:size]

    def close(self) -> None:
        pass


def _socket_factory(sent_payloads: list[bytes], response: bytes = b""):
    def factory(address, timeout):
        return _FakeSocket(sent_payloads, response=response)

    return factory


def test_matrix_sequence_step_label_exported_to_csv(tmp_path) -> None:
    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(disabled_mode=True),
        session_id="label-csv",
        wall_time_fn=lambda: 0.0,
    )
    sender.record_plan_event(
        SimpleNamespace(
            name="contact-up",
            modality="matrix",
            duration_ms=200,
            matrix_sequence=[
                {"offset_ms": 0, "channel_list": [1, 2, 3], "step_label": "contact_down"},
                {"offset_ms": 100, "channel_list": [4, 5, 6], "step_label": "contact_up"},
            ],
        )
    )
    path = sender.write_csv(tmp_path / "haptic_events.csv")

    rows = list(csv.DictReader(open(path, encoding="utf-8", newline="")))
    assert [row["matrix_sequence_step_label"] for row in rows] == [
        "contact_down",
        "contact_up",
    ]


def test_csv_exports_queued_and_sent_monotonic_ms(tmp_path) -> None:
    assert "queued_monotonic_ms" in HAPTIC_EVENT_FIELDS
    assert "sent_monotonic_ms" in HAPTIC_EVENT_FIELDS

    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(disabled_mode=True),
        session_id="ts-csv",
        wall_time_fn=lambda: 0.0,
    )
    rec = sender.send_contact(command_id=1)
    rec.queued_monotonic_ms = 123.0
    rec.sent_monotonic_ms = 456.0
    path = sender.write_csv(tmp_path / "haptic_events.csv")

    row = next(csv.DictReader(open(path, encoding="utf-8", newline="")))
    assert row["queued_monotonic_ms"] == "123.0"
    assert row["sent_monotonic_ms"] == "456.0"
    assert row["tcp_queued"] == "True"


from simple_haptic_sender import (
    _build_matrix_sequence_frames,
    _encode_matrix_output_packet,
)
from vendor_exp2_abc.matrix_haptic_protocol import (
    encode_matrix_auto_off_packet,
    encode_matrix_channel_packet,
    encode_matrix_hold_packet,
    encode_matrix_off_packet,
)


def test_matrix_output_packet_encodes_hold() -> None:
    assert _encode_matrix_output_packet([82, 84, 87], "hold", None, None) == (
        encode_matrix_hold_packet([82, 84, 87])
    )


def test_matrix_output_packet_encodes_auto_off() -> None:
    assert _encode_matrix_output_packet([82, 84, 87], "auto_off", 650, None) == (
        encode_matrix_auto_off_packet([82, 84, 87], 650)
    )


def test_matrix_output_packet_falls_back_to_legacy_for_empty_mode() -> None:
    assert _encode_matrix_output_packet([1, 2, 3], "", None, None) == (
        encode_matrix_channel_packet([1, 2, 3])
    )


def test_matrix_output_packet_alternate_must_go_through_sequence() -> None:
    with pytest.raises(ValueError, match="must be scheduled as an event sequence"):
        _encode_matrix_output_packet([1, 2], "alternate", None, 100)


def test_build_matrix_sequence_frames_cycles_alternate_then_offs() -> None:
    sequence = [
        {"offset_ms": 0, "channel_list": [1, 2], "output": {"mode": "alternate", "step_ms": 100}},
        {"channel_list": [3, 4], "output": {"mode": "alternate", "step_ms": 100}},
    ]
    frames = _build_matrix_sequence_frames(sequence, [None, None], duration_ms=250)

    assert [f.packet for f in frames] == [
        encode_matrix_hold_packet([1, 2]),
        encode_matrix_hold_packet([3, 4]),
        encode_matrix_hold_packet([1, 2]),
        encode_matrix_off_packet(),
    ]
    assert [f.delay_ms for f in frames] == [0.0, 100.0, 100.0, 50.0]


def test_build_matrix_sequence_frames_hold_and_auto_off_steps() -> None:
    sequence = [
        {"offset_ms": 0, "channel_list": [1, 2], "output": {"mode": "hold"}},
        {"offset_ms": 100, "channel_list": [3, 4], "output": {"mode": "auto_off", "duration_ms": 650}},
    ]
    frames = _build_matrix_sequence_frames(sequence, [None, None], duration_ms=1000)

    assert [f.packet for f in frames] == [
        encode_matrix_hold_packet([1, 2]),
        encode_matrix_auto_off_packet([3, 4], 650),
    ]
    assert [f.delay_ms for f in frames] == [0.0, 100.0]


def test_release_vibration_sends_matrix_off(tmp_path) -> None:
    sent_payloads: list[bytes] = []
    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(
            vibration_enabled=False,
            matrix_enabled=True,
            disabled_mode=False,
            matrix_tcp_enabled=True,
            matrix_socket_factory=_socket_factory(sent_payloads),
        ),
        session_id="release-off",
        wall_time_fn=lambda: 0.0,
    )
    scheduled = SimpleNamespace(
        haptic_trial_index=0,
        event_index=2,
        event_name="release",
        modality="vibration",
        command_label="contact_exit",
        command_id=2,
        channel_list=(),
        duration_ms=1500,
        trigger_zone="closed_zone",
        actual_zone_at_emit="closed_zone",
        trigger_pinch_distance=0.02,
        trigger_frame_index=1,
        actual_emit_monotonic_ms=1000.0,
    )

    sender.record_scheduled_event(scheduled)
    sender.write_csv(tmp_path / "haptic_events.csv")

    assert sent_payloads == [encode_matrix_off_packet()]
    assert any(r.event_name == "matrix_off" for r in sender.records)
