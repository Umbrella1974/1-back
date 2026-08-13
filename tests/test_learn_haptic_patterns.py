from __future__ import annotations

from learn_haptic_patterns import load_learning_session, sender_config_from_learning_config
from run_pinch_haptic_dry_run import load_dualtask_config


def test_learning_session_extracts_unique_events_from_dual_plan() -> None:
    session = load_learning_session("dualtask_config.yaml", mode_name="dual")

    assert [event.name for event in session.events] == [
        "contact",
        "slip",
        "up",
        "right",
        "left",
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
        "release",
    ]
    assert all(event.modality == "matrix" for event in session.events)
    assert event_by_name["contact"].channel_list == (81, 82, 83, 84, 86, 87, 88, 89)
    assert len(event_by_name["slip"].matrix_sequence) == 2
    assert event_by_name["slip"].matrix_sequence[0].channel_list == (82, 89)
    assert event_by_name["slip"].matrix_sequence[1].channel_list == (83, 87)
    assert event_by_name["release"].channel_list == (85,)


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
