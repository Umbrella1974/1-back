from __future__ import annotations

import math

import pytest

from wrist_rotation import (
    WristRotationConfig,
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


def _axis_angle_z(degrees: float):
    radians = math.radians(degrees)
    return (
        math.cos(radians / 2.0),
        0.0,
        0.0,
        math.sin(radians / 2.0),
    )
