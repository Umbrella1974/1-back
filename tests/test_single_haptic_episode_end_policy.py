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
    run_pinch_haptic_1back_core,
)
from simple_haptic_sender import SimpleHapticSender


def test_release_sets_session_should_end_and_blocks_second_contact(tmp_path) -> None:
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
        ),
        start_monotonic_ms=1000.0,
        end_monotonic_ms=3000.0,
        tick_interval_ms=1.0,
    )

    with logger.paths.haptic_events_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert result.session_should_end is True
    assert result.end_reason == "haptic_release"
    assert result.haptic_episode_completed is True
    assert result.haptic_trial_count == 1
    assert result.total_nback_trials < 10
    assert [row["event_name"] for row in rows] == ["contact", "release"]
    assert rows[-1]["end_reason"] == "haptic_release"
    assert rows[-1]["haptic_episode_completed"] == "True"


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
