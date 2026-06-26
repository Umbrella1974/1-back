from __future__ import annotations

import csv

from dualtask_logger import DualTaskLogger
from haptic_plan_config import haptic_plan_config_from_dict
from haptic_trial_scheduler import HapticTrialSchedulerConfig
from manus_pinch_input import PinchInputSample
from nback_dualtask_runner import NBackConfig, NBackTimeline
from pinch_calibration import PinchCalibrationResult
from run_pinch_haptic_1back import run_pinch_haptic_1back_core
from simple_haptic_sender import SimpleHapticSender


def test_haptic_contact_avoids_1back_digit_onset(tmp_path) -> None:
    session_id = "guard-integration-session"
    logger = DualTaskLogger(session_id=session_id, output_root=tmp_path)
    timeline = NBackTimeline(
        NBackConfig(
            num_trials=1,
            fixation_duration_ms=0,
            stimulus_duration_ms=100,
            isi_min_ms=100,
            isi_max_ms=100,
        ),
        sequence=[7],
        isi_ms=[100],
        wall_time_fn=lambda: 0.0,
    )

    run_pinch_haptic_1back_core(
        [_sample(session_id, frame_index=1, monotonic_ms=1000.0, distance=0.08)],
        calibration=_calibration(),
        plan=_guard_plan(),
        logger=logger,
        nback_timeline=timeline,
        sender=SimpleHapticSender(session_id=session_id),
        scheduler_config=HapticTrialSchedulerConfig(
            avoid_haptic_on_digit_onset=True,
            digit_onset_guard_ms=150,
            max_haptic_delay_ms=500,
        ),
        start_monotonic_ms=1000.0,
        tick_interval_ms=10.0,
    )

    with logger.paths.haptic_events_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    assert rows[0]["event_name"] == "contact"
    assert rows[0]["original_planned_onset_ms"] == "1000.0"
    assert rows[0]["adjusted_onset_ms"] == "1150.0"
    assert rows[0]["nearest_digit_onset_ms"] == "1000.0"
    assert rows[0]["digit_onset_delta_ms"] == "0.0"
    assert rows[0]["onset_was_delayed"] == "True"
    assert rows[0]["actual_zone_at_emit"] == "open_zone"
    assert rows[0]["tcp_enabled"] == "False"


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


def _guard_plan():
    return haptic_plan_config_from_dict(
        {
            "plan_id": "guard_integration_plan",
            "description": "",
            "random_seed": 1,
            "timing": {
                "contact_onset_delay_ms": [0, 0],
                "inter_event_gap_ms": [0, 0],
                "refractory_ms": 3000,
            },
            "events": [
                {
                    "name": "contact",
                    "modality": "vibration",
                    "command_label": "contact_enter",
                    "command_id": 1,
                    "duration_ms": 1,
                    "trigger_zone": "open_zone",
                },
                {
                    "name": "release",
                    "modality": "vibration",
                    "command_label": "contact_exit",
                    "command_id": 2,
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
