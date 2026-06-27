from __future__ import annotations

import math
import csv

import pytest

from dualtask_logger import DualTaskLogger
from wrist_rotation import (
    WristRotationConfig,
    WristRotationCalibrationResult,
    classify_wrist_rotation_frame,
    calibrate_wrist_rotation,
    classify_wrist_rotation,
    extract_wrist_quaternion,
    invert_quaternion,
    multiply_quaternion,
    normalize_quaternion,
    quaternion_angle,
    relative_quaternion,
)


def test_extract_wrist_quaternion_uses_rotation_not_position() -> None:
    raw = {
        "frame": 7,
        "skeletons": [
            {
                "nodes": [
                    {"id": 0, "rotation": [1.0, 0.0, 0.0, 0.0]},
                    {"id": 4, "position": [1.0, 2.0, 3.0]},
                ]
            }
        ],
    }

    assert extract_wrist_quaternion(raw, node_id=0) == (1.0, 0.0, 0.0, 0.0)


def test_extract_wrist_quaternion_supports_xyzw_order() -> None:
    raw = {
        "skeletons": [
            {"nodes": [{"id": 0, "rotation": [0.0, 0.0, 0.0, 1.0]}]}
        ]
    }

    assert extract_wrist_quaternion(raw, node_id=0, quaternion_order="xyzw") == (
        1.0,
        0.0,
        0.0,
        0.0,
    )


def test_quaternion_math_relative_identity() -> None:
    q = _axis_angle_z(30.0)

    assert multiply_quaternion(q, invert_quaternion(q)) == pytest.approx((1.0, 0.0, 0.0, 0.0))
    assert relative_quaternion(q, q) == pytest.approx((1.0, 0.0, 0.0, 0.0))
    assert quaternion_angle(q) == pytest.approx(math.radians(30.0))
    assert normalize_quaternion((2.0, 0.0, 0.0, 0.0)) == (1.0, 0.0, 0.0, 0.0)


def test_calibration_classifies_left_right_and_neutral() -> None:
    config = WristRotationConfig(min_valid_frames=2, classification_margin=0.15)
    neutral = [(1.0, 0.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0)]
    left = [_axis_angle_z(25.0), _axis_angle_z(30.0)]
    right = [_axis_angle_z(-25.0), _axis_angle_z(-30.0)]

    calibration = calibrate_wrist_rotation(neutral, left, right, config=config)
    left_sample = classify_wrist_rotation(_axis_angle_z(35.0), calibration)
    right_sample = classify_wrist_rotation(_axis_angle_z(-35.0), calibration)
    neutral_sample = classify_wrist_rotation((1.0, 0.0, 0.0, 0.0), calibration)

    assert calibration.calibration_passed is True
    assert calibration.left_score_mean > calibration.right_score_mean
    assert left_sample.wrist_rotation_class == "left"
    assert right_sample.wrist_rotation_class == "right"
    assert neutral_sample.wrist_rotation_class == "neutral"


def test_calibration_fails_when_not_enough_frames() -> None:
    calibration = calibrate_wrist_rotation(
        [(1.0, 0.0, 0.0, 0.0)],
        [_axis_angle_z(20.0)],
        [_axis_angle_z(-20.0)],
        config=WristRotationConfig(min_valid_frames=2),
    )

    assert calibration.calibration_passed is False
    assert calibration.failure_reason == "not_enough_valid_wrist_rotation_frames"
    assert calibration.valid_frame_counts["neutral"] == 1


def test_missing_node0_rotation_writes_invalid_sample_without_crashing(tmp_path) -> None:
    logger = DualTaskLogger(session_id="wrist-session", output_root=tmp_path)
    calibration = WristRotationCalibrationResult(
        node_id=0,
        quaternion_order="wxyz",
        neutral_mean_q=(1.0, 0.0, 0.0, 0.0),
        left_score_mean=0.2,
        right_score_mean=-0.2,
        threshold=0.0,
        rotation_axis_vector=(0.0, 0.0, 1.0),
        calibration_passed=True,
    )

    sample = classify_wrist_rotation_frame(
        {"frame": 9, "skeletons": [{"nodes": [{"id": 0}]}]},
        calibration,
        session_id="wrist-session",
    )
    logger.write_wrist_rotation_sample(sample)

    with logger.paths.wrist_rotation_timeseries_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert sample.wrist_rotation_valid is False
    assert sample.wrist_rotation_class == "unknown"
    assert sample.note == "missing_wrist_rotation"
    assert rows[0]["source_frame_id"] == "9"
    assert rows[0]["distance_to_left"] == ""
    assert rows[0]["distance_to_right"] == ""


def test_wrist_logger_writes_calibration_json(tmp_path) -> None:
    logger = DualTaskLogger(session_id="wrist-cal", output_root=tmp_path)
    calibration = WristRotationCalibrationResult(
        node_id=0,
        quaternion_order="wxyz",
        calibration_passed=False,
        failure_reason="not_enough_valid_wrist_rotation_frames",
    )

    logger.write_wrist_rotation_calibration(calibration)

    assert logger.paths.wrist_rotation_calibration_json.exists()


def _axis_angle_z(degrees: float):
    radians = math.radians(degrees)
    return (
        math.cos(radians / 2.0),
        0.0,
        0.0,
        math.sin(radians / 2.0),
    )
