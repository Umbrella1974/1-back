from __future__ import annotations

from test_haptic_patterns import (
    build_test_trials,
    make_result_row,
    parse_answer,
    print_test_summary,
)

from learn_haptic_patterns import load_learning_session


def test_build_test_trials_repeats_each_cue_three_times() -> None:
    session = load_learning_session("only-motor.yaml", mode_name="only-motor")

    trials = build_test_trials(session.events, repeats_per_cue=3, random_seed=123)

    counts: dict[str, int] = {}
    for trial in trials:
        counts[trial.event.name] = counts.get(trial.event.name, 0) + 1
    assert len(trials) == len(session.events) * 3
    assert set(counts.values()) == {3}


def test_parse_answer_accepts_number_and_event_name() -> None:
    session = load_learning_session("only-motor.yaml", mode_name="only-motor")

    action, event = parse_answer("1", session.events)
    assert action == "answer"
    assert event == session.events[0]

    action, event = parse_answer(session.events[1].name, session.events)
    assert action == "answer"
    assert event == session.events[1]


def test_make_result_row_scores_correctness() -> None:
    session = load_learning_session("only-motor.yaml", mode_name="only-motor")
    true_event = session.events[0]
    wrong_event = session.events[1]

    row = make_result_row(
        session_id="test-session",
        participant_id="p01",
        mode_name="only-motor",
        trial_index=1,
        true_event=true_event,
        answer_event=wrong_event,
        reaction_time_sec="0.500000",
        replay_count=1,
        status="answered",
        random_seed=123,
    )

    assert row["true_event_name"] == true_event.name
    assert row["participant_id"] == "p01"
    assert row["answer_event_name"] == wrong_event.name
    assert row["is_correct"] is False
    assert row["replay_count"] == 1
    assert row["random_seed"] == 123


def test_print_test_summary_flags_all_wrong_cue(capsys) -> None:
    session = load_learning_session("only-motor.yaml", mode_name="only-motor")
    rows = [
        make_result_row(
            session_id="test-session",
            participant_id="p01",
            mode_name="only-motor",
            trial_index=1,
            true_event=session.events[0],
            answer_event=session.events[1],
            reaction_time_sec="0.500000",
            replay_count=0,
            status="answered",
            random_seed=123,
        )
    ]

    print_test_summary(rows, session.events[:2])

    output = capsys.readouterr().out
    assert "Accuracy: 0.0%" in output
    assert "Need relearning" in output
    assert session.events[0].name in output
