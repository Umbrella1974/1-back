from __future__ import annotations

import csv
import json
from types import SimpleNamespace

from dualtask_logger import DualTaskLogger
from pinch_calibration import PinchCalibrationResult


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


def test_dualtask_logger_creates_session_directory(tmp_path) -> None:
    logger = DualTaskLogger(session_id="session-a", output_root=tmp_path)

    assert logger.session_dir == tmp_path / "session-a"
    assert logger.session_dir.exists()
    assert logger.paths.pinch_timeseries_csv.name == "pinch_timeseries.csv"


def test_dualtask_logger_writes_pinch_timeseries_csv(tmp_path) -> None:
    logger = DualTaskLogger(session_id="session-a", output_root=tmp_path)
    sample = SimpleNamespace(
        session_id="session-a",
        frame_index=1,
        wall_time_iso="2026-01-01T00:00:00+00:00",
        monotonic_ms=1000.0,
        source_timestamp=123,
        source_frame_id=7,
        hand_valid=True,
        pinch_valid=True,
        pinch_distance=0.08,
        thumb_node_id=4,
        target_finger_node_id=14,
        tracker_present=False,
        note="",
    )

    logger.write_pinch_sample(
        sample,
        calibration=_calibration(),
        zone="open_zone",
        queue_depth=12,
        queue_depth_at_phase_start=20,
        latest_received_frame_index=99,
    )

    with logger.paths.pinch_timeseries_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["session_id"] == "session-a"
    assert rows[0]["phase"] == "formal"
    assert rows[0]["zone"] == "open_zone"
    assert rows[0]["threshold_a"] == "0.055"
    assert rows[0]["queue_depth"] == "12"
    assert rows[0]["queue_depth_at_phase_start"] == "20"
    assert rows[0]["latest_received_frame_index"] == "99"
    assert logger.total_pinch_samples == 1
    assert logger.total_valid_pinch_samples == 1


def test_dualtask_logger_writes_calibration_timeseries_csv(tmp_path) -> None:
    logger = DualTaskLogger(session_id="session-a", output_root=tmp_path)
    sample = SimpleNamespace(
        session_id="session-a",
        frame_index=1,
        wall_time_iso="2026-01-01T00:00:00+00:00",
        monotonic_ms=1000.0,
        source_timestamp=123,
        source_frame_id=7,
        hand_valid=True,
        pinch_valid=True,
        pinch_distance=0.08,
        thumb_node_id=4,
        target_finger_node_id=14,
        tracker_present=False,
        note="",
    )

    logger.write_calibration_sample(
        sample,
        phase="open",
        queue_depth=7,
        queue_depth_at_phase_start=30,
        latest_received_frame_index=101,
    )

    with logger.paths.calibration_timeseries_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["session_id"] == "session-a"
    assert rows[0]["phase"] == "open"
    assert rows[0]["pinch_distance"] == "0.08"
    assert rows[0]["queue_depth"] == "7"
    assert rows[0]["queue_depth_at_phase_start"] == "30"
    assert rows[0]["latest_received_frame_index"] == "101"


def test_dualtask_logger_writes_calibration_and_summary_json(tmp_path) -> None:
    logger = DualTaskLogger(session_id="session-a", output_root=tmp_path)

    logger.write_calibration(_calibration())
    logger.write_summary(
        {
            "participant_id": "p01",
            "condition_id": "dry",
            "total_haptic_events": 5,
            "warnings": [],
            "errors": [],
        }
    )

    calibration = json.loads(logger.paths.calibration_json.read_text(encoding="utf-8"))
    summary = json.loads(logger.paths.summary_json.read_text(encoding="utf-8"))
    assert calibration["threshold_a"] == 0.055
    assert summary["session_id"] == "session-a"
    assert summary["participant_id"] == "p01"
    assert summary["output_files"]["haptic_events_csv"].endswith("haptic_events.csv")
    assert summary["output_files"]["calibration_timeseries_csv"].endswith(
        "calibration_timeseries.csv"
    )
