from __future__ import annotations

import csv

from dualtask_logger import DualTaskLogger
from haptic_plan_config import haptic_plan_config_from_dict
from haptic_trial_scheduler import HapticTrialSchedulerConfig
from manus_pinch_input import PinchInputSample
from nback_dualtask_runner import NBackConfig, NBackTimeline
from pinch_calibration import PinchCalibrationResult
from run_pinch_haptic_1back import (
    SessionEndPolicy,
    _is_release_end_reason,
    run_pinch_haptic_1back_core,
)
from simple_haptic_sender import SimpleHapticSender


def test_release_starts_post_recording_and_blocks_second_contact(tmp_path) -> None:
    session_id = "single-episode-session"
    logger = DualTaskLogger(session_id=session_id, output_root=tmp_path)
    timeline = NBackTimeline(
        NBackConfig(
            num_trials=10,
            fixation_duration_ms=0,
            stimulus_duration_ms=100,
            isi_min_ms=100,
            isi_max_ms=100,
        ),
        sequence=[1, 2, 3, 4, 5, 6, 7, 8, 9, 0],
        isi_ms=[100] * 10,
        wall_time_fn=lambda: 0.0,
    )

    result = run_pinch_haptic_1back_core(
        [
            _sample(session_id, frame_index=1, monotonic_ms=1000.0, distance=0.08),
            _sample(session_id, frame_index=2, monotonic_ms=1001.0, distance=0.08),
            _sample(session_id, frame_index=3, monotonic_ms=1002.0, distance=0.02),
            _sample(session_id, frame_index=4, monotonic_ms=1003.0, distance=0.08),
            _sample(session_id, frame_index=5, monotonic_ms=1004.0, distance=0.02),
        ],
        calibration=_calibration(),
        plan=_plan(),
        logger=logger,
        nback_timeline=timeline,
        sender=SimpleHapticSender(session_id=session_id),
        scheduler_config=HapticTrialSchedulerConfig(avoid_haptic_on_digit_onset=False),
            session_end_policy=SessionEndPolicy(
                allow_multiple_haptic_trials=False,
                finish_active_haptic_before_exit=True,
                post_release_recording_ms=3,
            ),
        start_monotonic_ms=1000.0,
        end_monotonic_ms=3000.0,
        tick_interval_ms=1.0,
    )

    with logger.paths.haptic_events_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert result.session_should_end is True
    assert result.end_reason == "haptic_release_post_recording_complete"
    assert result.haptic_episode_completed is True
    assert result.haptic_trial_count == 1
    assert result.total_nback_trials < 10
    assert result.post_release_recording_ms == 3
    assert result.post_release_started_ms is not None
    assert result.post_release_end_ms == result.post_release_started_ms + 4
    assert result.post_release_pinch_samples >= 1
    assert [row["event_name"] for row in rows] == ["contact", "release"]
    assert rows[-1]["end_reason"] == "haptic_release"
    assert rows[-1]["haptic_episode_completed"] == "True"


def test_post_release_complete_counts_as_release_end_reason() -> None:
    assert _is_release_end_reason("haptic_release") is True
    assert _is_release_end_reason("haptic_release_post_recording_complete") is True
    assert _is_release_end_reason("duration_elapsed") is False


def test_post_release_continue_nback_flag_controls_nback_after_release(tmp_path) -> None:
    stopped_result, stopped_haptic_rows = _run_post_release_case(
        tmp_path,
        session_id="post-release-nback-stopped",
        post_release_continue_nback=False,
    )
    continued_result, continued_haptic_rows = _run_post_release_case(
        tmp_path,
        session_id="post-release-nback-continued",
        post_release_continue_nback=True,
    )

    assert stopped_result.end_reason == "haptic_release_post_recording_complete"
    assert continued_result.end_reason == "haptic_release_post_recording_complete"
    assert stopped_result.total_pinch_samples == continued_result.total_pinch_samples
    assert stopped_result.post_release_pinch_samples >= 3
    assert continued_result.post_release_pinch_samples >= 3
    assert [row["event_name"] for row in stopped_haptic_rows] == ["contact", "release"]
    assert [row["event_name"] for row in continued_haptic_rows] == ["contact", "release"]
    assert continued_result.total_nback_trials > stopped_result.total_nback_trials


def test_release_is_held_until_configured_nback_trial_and_nback_completes(tmp_path) -> None:
    session_id = "release-held-until-trial-window"
    logger = DualTaskLogger(session_id=session_id, output_root=tmp_path)
    timeline = NBackTimeline(
        NBackConfig(
            num_trials=50,
            fixation_duration_ms=0,
            stimulus_duration_ms=20,
            isi_min_ms=20,
            isi_max_ms=20,
        ),
        sequence=[index % 10 for index in range(50)],
        isi_ms=[20] * 50,
        wall_time_fn=lambda: 0.0,
    )

    result = run_pinch_haptic_1back_core(
        [
            _sample(session_id, frame_index=1, monotonic_ms=1000.0, distance=0.08),
            _sample(session_id, frame_index=2, monotonic_ms=1001.0, distance=0.08),
            _sample(session_id, frame_index=3, monotonic_ms=1002.0, distance=0.02),
            _sample(session_id, frame_index=4, monotonic_ms=3000.0, distance=0.02),
        ],
        calibration=_calibration(),
        plan=_plan(),
        logger=logger,
        nback_timeline=timeline,
        sender=SimpleHapticSender(session_id=session_id),
        scheduler_config=HapticTrialSchedulerConfig(avoid_haptic_on_digit_onset=False),
        session_end_policy=SessionEndPolicy(
            allow_multiple_haptic_trials=False,
            finish_active_haptic_before_exit=True,
            post_release_recording_ms=30,
            post_release_continue_nback=True,
            release_nback_trial_window=(40, 50),
            prerelease_haptic_complete_by_trial=45,
            hold_release_until_nback_trial=True,
            finish_nback_after_haptic_release=True,
        ),
        start_monotonic_ms=1000.0,
        end_monotonic_ms=1100.0,
        tick_interval_ms=10.0,
    )

    with logger.paths.haptic_events_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert result.end_reason == "nback_complete_after_haptic_release"
    assert result.total_nback_trials == 50
    assert result.release_was_held is True
    assert result.release_emit_trial_number == 40
    assert result.haptic_policy_warnings == ()
    assert [row["event_name"] for row in rows] == ["contact", "release"]
    assert float(rows[1]["monotonic_ms"]) == timeline.trials[39].fixation_onset_monotonic_ms
    assert "release_held_until_nback_trial" in rows[1]["timing_note"]


def test_prerelease_deadline_warning_when_plan_is_too_slow(tmp_path) -> None:
    session_id = "prerelease-deadline-warning"
    logger = DualTaskLogger(session_id=session_id, output_root=tmp_path)
    timeline = NBackTimeline(
        NBackConfig(
            num_trials=50,
            fixation_duration_ms=0,
            stimulus_duration_ms=20,
            isi_min_ms=20,
            isi_max_ms=20,
        ),
        sequence=[index % 10 for index in range(50)],
        isi_ms=[20] * 50,
        wall_time_fn=lambda: 0.0,
    )

    result = run_pinch_haptic_1back_core(
        [
            _sample(session_id, frame_index=1, monotonic_ms=1000.0, distance=0.08),
            _sample(session_id, frame_index=2, monotonic_ms=1001.0, distance=0.08),
            _sample(session_id, frame_index=3, monotonic_ms=1002.0, distance=0.02),
            _sample(session_id, frame_index=4, monotonic_ms=4000.0, distance=0.02),
        ],
        calibration=_calibration(),
        plan=_slow_prerelease_plan(),
        logger=logger,
        nback_timeline=timeline,
        sender=SimpleHapticSender(session_id=session_id),
        scheduler_config=HapticTrialSchedulerConfig(avoid_haptic_on_digit_onset=False),
        session_end_policy=SessionEndPolicy(
            allow_multiple_haptic_trials=False,
            finish_active_haptic_before_exit=True,
            post_release_recording_ms=30,
            post_release_continue_nback=True,
            release_nback_trial_window=(40, 50),
            prerelease_haptic_complete_by_trial=45,
            hold_release_until_nback_trial=True,
            finish_nback_after_haptic_release=True,
        ),
        start_monotonic_ms=1000.0,
        end_monotonic_ms=1100.0,
        tick_interval_ms=10.0,
    )

    assert result.end_reason == "nback_complete_after_haptic_release"
    assert result.release_emit_trial_number is not None
    assert 45 <= result.release_emit_trial_number <= 50
    assert result.haptic_policy_warnings == (
        "prerelease_haptic_not_complete_by_trial_45",
    )


def _run_post_release_case(
    tmp_path,
    *,
    session_id: str,
    post_release_continue_nback: bool,
):
    logger = DualTaskLogger(session_id=session_id, output_root=tmp_path)
    timeline = NBackTimeline(
        NBackConfig(
            num_trials=20,
            fixation_duration_ms=0,
            stimulus_duration_ms=20,
            isi_min_ms=20,
            isi_max_ms=20,
        ),
        sequence=[index % 10 for index in range(20)],
        isi_ms=[20] * 20,
        wall_time_fn=lambda: 0.0,
    )

    result = run_pinch_haptic_1back_core(
        [
            _sample(session_id, frame_index=1, monotonic_ms=1000.0, distance=0.08),
            _sample(session_id, frame_index=2, monotonic_ms=1001.0, distance=0.08),
            _sample(session_id, frame_index=3, monotonic_ms=1002.0, distance=0.02),
            _sample(session_id, frame_index=4, monotonic_ms=1100.0, distance=0.02),
            _sample(session_id, frame_index=5, monotonic_ms=1200.0, distance=0.02),
            _sample(session_id, frame_index=6, monotonic_ms=1300.0, distance=0.02),
        ],
        calibration=_calibration(),
        plan=_plan(),
        logger=logger,
        nback_timeline=timeline,
        sender=SimpleHapticSender(session_id=session_id),
        scheduler_config=HapticTrialSchedulerConfig(avoid_haptic_on_digit_onset=False),
        session_end_policy=SessionEndPolicy(
            allow_multiple_haptic_trials=False,
            finish_active_haptic_before_exit=True,
            post_release_recording_ms=300,
            post_release_continue_nback=post_release_continue_nback,
        ),
        start_monotonic_ms=1000.0,
        end_monotonic_ms=2000.0,
        tick_interval_ms=10.0,
    )

    with logger.paths.haptic_events_csv.open(newline="", encoding="utf-8") as handle:
        haptic_rows = list(csv.DictReader(handle))
    return result, haptic_rows


def _plan():
    return haptic_plan_config_from_dict(
        {
            "plan_id": "single_episode",
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
                    "duration_ms": 1,
                    "trigger_zone": "open_zone",
                },
                {
                    "name": "release",
                    "modality": "vibration",
                    "command_label": "contact_exit",
                    "duration_ms": 1,
                    "trigger_zone": "closed_zone",
                },
            ],
            "zones": {
                "open_zone": {"lower": "auto_a", "upper": "auto_max"},
                "closed_zone": {"lower": "auto_min", "upper": "auto_a"},
            },
        }
    )


def _slow_prerelease_plan():
    return haptic_plan_config_from_dict(
        {
            "plan_id": "slow_prerelease",
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
                    "duration_ms": 1,
                    "trigger_zone": "open_zone",
                },
                {
                    "name": "slip",
                    "modality": "vibration",
                    "command_label": "slip_start",
                    "duration_ms": 1,
                    "trigger_zone": "closed_zone",
                    "onset_gap_after_previous_ms": [1770, 1770],
                },
                {
                    "name": "release",
                    "modality": "vibration",
                    "command_label": "contact_exit",
                    "duration_ms": 1,
                    "trigger_zone": "closed_zone",
                    "onset_gap_after_previous_ms": [100, 100],
                },
            ],
            "zones": {
                "open_zone": {"lower": "auto_a", "upper": "auto_max"},
                "closed_zone": {"lower": "auto_min", "upper": "auto_a"},
            },
        }
    )


def _calibration() -> PinchCalibrationResult:
    return PinchCalibrationResult(
        min_distance=0.01,
        max_distance=0.10,
        threshold_a=0.055,
        threshold_ratio=0.5,
        thumb_node_id=4,
        target_finger_node_id=14,
        open_hand_duration_s=1.0,
        pinch_hand_duration_s=1.0,
        open_valid_frame_count=3,
        pinch_valid_frame_count=3,
    )


def _sample(
    session_id: str,
    *,
    frame_index: int,
    monotonic_ms: float,
    distance: float,
) -> PinchInputSample:
    return PinchInputSample(
        session_id=session_id,
        frame_index=frame_index,
        wall_time_iso="2026-01-01T00:00:00+00:00",
        monotonic_ms=monotonic_ms,
        source_timestamp=frame_index,
        source_frame_id=frame_index,
        hand_valid=True,
        pinch_valid=True,
        pinch_distance=distance,
        thumb_node_id=4,
        target_finger_node_id=14,
        thumb_position=[0.0, 0.0, 0.0],
        target_finger_position=[distance, 0.0, 0.0],
        tracker_present=False,
        note="",
    )
