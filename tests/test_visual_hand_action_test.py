from __future__ import annotations

from types import SimpleNamespace

from run_visual_hand_action_test import (
    _randomized_visual_trials,
    _visual_action_issue_from_metric,
    _visual_action_result_pages,
    _visual_events,
    VisualActionResult,
)


def test_visual_events_are_display_only_semantics() -> None:
    events = _visual_events(("up", "down", "left", "slip"))

    assert [event.name for event in events] == ["up", "down", "left", "slip"]
    assert events[0].channel_list == ()
    assert events[1].modality == "matrix"
    assert events[1].channel_list == ()
    assert events[3].modality == "vibration"


def test_randomized_visual_trials_are_episode_structured_and_reproducible() -> None:
    events = tuple(SimpleNamespace(name=name) for name in ("slip", "up", "down"))

    first = _randomized_visual_trials(
        events,
        episode_count=3,
        middle_events_per_episode=(2, 4),
        seed=17,
    )
    second = _randomized_visual_trials(
        events,
        episode_count=3,
        middle_events_per_episode=(2, 4),
        seed=17,
    )

    assert [event.name for event in first] == [event.name for event in second]
    for episode_index in range(1, 4):
        episode = [
            event for event in first if event.visual_episode_index == episode_index
        ]
        assert episode[0].name == "contact"
        assert episode[-1].name == "release"
        assert 2 <= len(episode[1:-1]) <= 4
        assert all(event.name in {"slip", "up", "down"} for event in episode[1:-1])


def test_visual_result_reports_wrong_first_response() -> None:
    issue = _visual_action_issue_from_metric(
        {
            "event_name": "up",
            "first_response": "left",
            "first_response_correct": "False",
            "eventual_correct": "True",
            "trial_quality": "clean",
            "quality_reason": "",
            "response_quality_reason": "",
            "cycle_quality": "complete",
            "cycle_quality_reason": "",
        },
        event_position=4,
        episode_index=1,
        episode_position=4,
    )

    assert issue is not None
    assert issue.category == "首次动作不一致"
    assert issue.detected_response == "left"


def test_visual_result_reports_incomplete_slip() -> None:
    issue = _visual_action_issue_from_metric(
        {
            "event_name": "slip",
            "first_response": "pinch",
            "first_response_correct": "True",
            "eventual_correct": "False",
            "trial_quality": "partial_no_release",
            "quality_reason": "no_stable_reopening_before_next_cue",
            "response_quality_reason": "",
            "cycle_quality": "incomplete_release",
            "cycle_quality_reason": "no_stable_reopening_before_next_cue",
        },
        event_position=2,
        episode_index=1,
        episode_position=2,
    )

    assert issue is not None
    assert issue.category == "动作不完整"
    assert issue.reason == "没有检测到松回"


def test_visual_result_pages_show_clean_summary() -> None:
    pages = _visual_action_result_pages(
        VisualActionResult(total_count=12, passed_count=12, issues=())
    )

    assert len(pages) == 1
    assert "所有动作均与语义一致" in pages[0]
