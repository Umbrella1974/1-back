from __future__ import annotations

from learn_haptic_patterns import (
    _learning_log_row,
    load_learning_session,
    play_event_once_for_test,
    sender_config_from_learning_config,
)
from run_pinch_haptic_dry_run import load_dualtask_config
from simple_haptic_sender import SimpleHapticSender, SimpleHapticSenderConfig
from vendor_exp2_abc.matrix_haptic_protocol import encode_matrix_auto_off_packet


def test_learning_session_extracts_unique_events_from_dual_plan() -> None:
    session = load_learning_session("dualtask_config.yaml", mode_name="dual")

    assert [event.name for event in session.events] == [
        "contact",
        "slip",
        "up",
        "right",
        "left",
        "down",
        "release",
    ]
    assert session.events[0].modality == "vibration"
    assert session.events[1].modality == "vibration"
    assert session.events[2].modality == "matrix"


def test_learning_session_extracts_only_matrix_sequences() -> None:
    session = load_learning_session("only-matrix.yaml", mode_name="only-matrix")

    event_by_name = {event.name: event for event in session.events}
    assert [event.name for event in session.events] == [
        "contact",
        "slip",
        "up",
        "right",
        "left",
        "down",
        "release",
    ]
    assert all(event.modality == "matrix" for event in session.events)
    assert event_by_name["contact"].channel_list == (81, 82, 83, 84, 86, 87, 88, 89)
    assert len(event_by_name["slip"].matrix_sequence) == 2
    assert event_by_name["slip"].matrix_sequence[0].offset_ms == 0
    assert event_by_name["slip"].matrix_sequence[0].channel_list == (82, 84, 87)
    assert event_by_name["slip"].matrix_sequence[1].offset_ms == 100
    assert event_by_name["slip"].matrix_sequence[1].channel_list == (83, 86, 89)
    assert event_by_name["release"].channel_list == (85,)


def test_learning_session_extracts_down_from_only_motor_templates() -> None:
    session = load_learning_session("only-motor.yaml", mode_name="only-motor")

    event_by_name = {event.name: event for event in session.events}
    assert [event.name for event in session.events] == [
        "contact",
        "slip",
        "left",
        "right",
        "up",
        "down",
        "release",
    ]
    assert all(event.modality == "vibration" for event in session.events)
    assert event_by_name["down"].command_id is not None


def test_learning_sender_config_matches_only_motor_tcp_flags() -> None:
    config = sender_config_from_learning_config(load_dualtask_config("only-motor.yaml"))

    assert config.vibration_enabled is True
    assert config.vibration_tcp_enabled is True
    assert config.vibration_required is True
    assert config.matrix_enabled is False
    assert config.matrix_tcp_enabled is False
    assert config.matrix_required is False


def test_learning_sender_config_matches_only_matrix_tcp_flags() -> None:
    config = sender_config_from_learning_config(load_dualtask_config("only-matrix.yaml"))

    assert config.vibration_enabled is False
    assert config.vibration_tcp_enabled is False
    assert config.vibration_required is False
    assert config.matrix_enabled is True
    assert config.matrix_tcp_enabled is True
    assert config.matrix_required is True


def test_learning_play_preserves_single_matrix_output_policy() -> None:
    sent_payloads: list[bytes] = []
    session = load_learning_session("only-matrix.yaml", mode_name="only-matrix")
    event = session.events[0]
    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(
            matrix_enabled=True,
            matrix_tcp_enabled=True,
            disabled_mode=False,
            matrix_latest_only=False,
            matrix_socket_factory=_socket_factory(sent_payloads),
        ),
        session_id="learn-matrix-output",
    )
    try:
        play_event_once_for_test(sender, event)
        sender.close()
    finally:
        sender.close()

    assert sent_payloads == [encode_matrix_auto_off_packet(event.channel_list, 650)]


def test_learning_log_row_records_play_count_and_phase() -> None:
    session = load_learning_session("only-motor.yaml", mode_name="only-motor")
    event = session.events[0]

    row = _learning_log_row(
        session=session,
        participant_id="p01",
        session_id="learn-p01",
        event=event,
        phase="ordered",
        play_index=3,
        status="played",
    )

    assert row["participant_id"] == "p01"
    assert row["session_id"] == "learn-p01"
    assert row["mode_name"] == "only-motor"
    assert row["phase"] == "ordered"
    assert row["play_index"] == 3
    assert row["event_name"] == event.name
    assert row["status"] == "played"


class _FakeSocket:
    def __init__(self, sent_payloads: list[bytes]) -> None:
        self._sent_payloads = sent_payloads

    def settimeout(self, timeout: float) -> None:
        pass

    def sendall(self, payload: bytes) -> None:
        self._sent_payloads.append(bytes(payload))

    def close(self) -> None:
        pass


def _socket_factory(sent_payloads: list[bytes]):
    def factory(address, timeout=None):
        return _FakeSocket(sent_payloads)

    return factory
