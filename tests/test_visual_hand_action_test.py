from __future__ import annotations

from types import SimpleNamespace

from run_visual_hand_action_test import (
    _randomized_visual_trials,
    _visual_events,
)


def test_visual_events_are_display_only_semantics() -> None:
    events = _visual_events(("up", "down", "left", "contact"))

    assert [event.name for event in events] == ["up", "down", "left", "contact"]
    assert events[0].channel_list == ()
    assert events[1].modality == "matrix"
    assert events[1].channel_list == ()
    assert events[3].modality == "vibration"


def test_randomized_visual_trials_are_reproducible_by_seed() -> None:
    events = tuple(SimpleNamespace(name=name) for name in ("contact", "slip", "up"))

    first = _randomized_visual_trials(events, repetitions_per_event=2, seed=17)
    second = _randomized_visual_trials(events, repetitions_per_event=2, seed=17)

    assert [event.name for event in first] == [event.name for event in second]
    assert sorted(event.name for event in first) == [
        "contact",
        "contact",
        "slip",
        "slip",
        "up",
        "up",
    ]
