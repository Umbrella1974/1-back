from __future__ import annotations

import csv
import sys

from dualtask_logger import DualTaskLogger
from haptic_plan_config import haptic_plan_config_from_dict
from manus_pinch_input import PinchInputSample
from pinch_calibration import PinchCalibrationResult
from run_pinch_haptic_dry_run import run_pinch_haptic_dry_run_core
from simple_haptic_sender import SimpleHapticSender


def test_dry_run_core_drives_scheduler_and_writes_csv_outputs(tmp_path) -> None:
    session_id = "dry-core-session"
    logger = DualTaskLogger(session_id=session_id, output_root=tmp_path)
    sender = SimpleHapticSender(session_id=session_id)
    result = run_pinch_haptic_dry_run_core(
        _samples(session_id),
        calibration=_calibration(),
        plan=_plan(),
        logger=logger,
        sender=sender,
    )

    with logger.paths.haptic_events_csv.open(newline="", encoding="utf-8") as handle:
        haptic_rows = list(csv.DictReader(handle))
    with logger.paths.pinch_timeseries_csv.open(newline="", encoding="utf-8") as handle:
        pinch_rows = list(csv.DictReader(handle))

    assert [row["event_name"] for row in haptic_rows] == [
        "contact",
        "slip",
        "left",
        "right",
        "release",
    ]
    assert haptic_rows[2]["channel_list"] == "[1,2,3]"
    assert haptic_rows[3]["channel_list"] == "[5,6,7]"
    assert all(row["session_id"] == session_id for row in haptic_rows)
    assert all(row["session_id"] == session_id for row in pinch_rows)
    assert all(row["tcp_enabled"] == "False" for row in haptic_rows)
    assert all(row["send_status"] == "disabled" for row in haptic_rows)
    assert result.total_haptic_events == 5
    assert result.total_pinch_samples == len(pinch_rows)
    assert result.total_valid_pinch_samples == len(pinch_rows)
    assert "pygame" not in sys.modules


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


def _plan():
    return haptic_plan_config_from_dict(
        {
            "plan_id": "dry_core_plan",
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
                    "name": "slip",
                    "modality": "vibration",
                    "command_label": "slip_start",
                    "command_id": 3,
                    "duration_ms": 1,
                    "trigger_zone": "closed_zone",
                },
                {
                    "name": "left",
                    "modality": "matrix",
                    "channel_list": [1, 2, 3],
                    "duration_ms": 1,
                    "trigger_zone": "closed_zone",
                },
                {
                    "name": "right",
                    "modality": "matrix",
                    "channel_list": [5, 6, 7],
                    "duration_ms": 1,
                    "trigger_zone": "closed_zone",
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


def _samples(session_id: str) -> list[PinchInputSample]:
    return [
        _sample(session_id, frame_index=1, monotonic_ms=1000.0, distance=0.08),
        _sample(session_id, frame_index=2, monotonic_ms=1001.0, distance=0.02),
        _sample(session_id, frame_index=3, monotonic_ms=1002.0, distance=0.02),
        _sample(session_id, frame_index=4, monotonic_ms=1003.0, distance=0.02),
        _sample(session_id, frame_index=5, monotonic_ms=1004.0, distance=0.02),
    ]


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

