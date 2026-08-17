from __future__ import annotations

from types import SimpleNamespace

import pytest

from simple_haptic_sender import SimpleHapticSender, SimpleHapticSenderConfig
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
