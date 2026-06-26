from __future__ import annotations

import pytest

from haptic_plan_config import haptic_plan_config_from_dict
from haptic_trial_scheduler import (
    HapticOnsetConflictError,
    HapticTrialScheduler,
    HapticTrialSchedulerConfig,
    adjust_onset_away_from_digit_onsets,
)


def test_adjust_onset_delays_out_of_digit_guard_window() -> None:
    adjustment = adjust_onset_away_from_digit_onsets(
        onset_ms=1000.0,
        digit_onsets_ms=[1000.0, 2500.0],
        guard_ms=150.0,
        max_haptic_delay_ms=500.0,
    )

    assert adjustment.original_planned_onset_ms == 1000.0
    assert adjustment.adjusted_onset_ms == 1150.0
    assert adjustment.nearest_digit_onset_ms == 1000.0
    assert adjustment.digit_onset_delta_ms == 0.0
    assert adjustment.onset_was_delayed is True
    assert adjustment.sync_warning == ""


def test_adjust_onset_records_warning_when_delay_limit_is_too_small() -> None:
    adjustment = adjust_onset_away_from_digit_onsets(
        onset_ms=1000.0,
        digit_onsets_ms=[1000.0],
        guard_ms=150.0,
        max_haptic_delay_ms=100.0,
        if_cannot_avoid="log_warning_and_send",
    )

    assert adjustment.adjusted_onset_ms == 1000.0
    assert adjustment.onset_was_delayed is False
    assert adjustment.should_skip is False
    assert adjustment.sync_warning == "haptic_onset_conflict_could_not_avoid_within_max_delay"


def test_adjust_onset_skip_event_policy_marks_skip() -> None:
    adjustment = adjust_onset_away_from_digit_onsets(
        onset_ms=1000.0,
        digit_onsets_ms=[1000.0],
        guard_ms=150.0,
        max_haptic_delay_ms=100.0,
        if_cannot_avoid="skip_event",
    )

    assert adjustment.should_skip is True
    assert adjustment.sync_warning == "haptic_onset_conflict_could_not_avoid_within_max_delay"


def test_adjust_onset_abort_policy_raises() -> None:
    with pytest.raises(HapticOnsetConflictError):
        adjust_onset_away_from_digit_onsets(
            onset_ms=1000.0,
            digit_onsets_ms=[1000.0],
            guard_ms=150.0,
            max_haptic_delay_ms=100.0,
            if_cannot_avoid="abort",
        )


def test_scheduler_applies_digit_guard_to_contact() -> None:
    scheduler = HapticTrialScheduler(
        _guard_plan(),
        HapticTrialSchedulerConfig(
            avoid_haptic_on_digit_onset=True,
            digit_onset_guard_ms=150.0,
            max_haptic_delay_ms=500.0,
        ),
    )

    scheduler.update(
        zone="open_zone",
        now_ms=1000.0,
        digit_onsets_ms=[1000.0],
    )
    assert scheduler.update(zone="open_zone", now_ms=1149.0) == []
    contact = scheduler.update(zone="open_zone", now_ms=1150.0)[0]

    assert contact.event_name == "contact"
    assert contact.original_planned_onset_ms == 1000.0
    assert contact.adjusted_onset_ms == 1150.0
    assert contact.nearest_digit_onset_ms == 1000.0
    assert contact.digit_onset_delta_ms == 0.0
    assert contact.onset_was_delayed is True


def _guard_plan() -> object:
    return haptic_plan_config_from_dict(
        {
            "plan_id": "guard_plan",
            "description": "",
            "random_seed": 1,
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
                    "command_id": 1,
                    "duration_ms": 150,
                    "trigger_zone": "open_zone",
                    "onset_policy": {"type": "when_enter_zone", "zone": "open_zone"},
                },
                {
                    "name": "release",
                    "modality": "vibration",
                    "command_label": "contact_exit",
                    "command_id": 2,
                    "duration_ms": 150,
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

