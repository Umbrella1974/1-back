from __future__ import annotations

from types import SimpleNamespace

import pytest

from pinch_calibration import (
    PinchCalibrationConfig,
    calculate_threshold_a,
    calibrate_from_samples,
    calibrate_from_repetition_samples,
    classify_pinch_zone,
    is_in_closed_zone,
    is_in_open_zone,
)


def _sample(distance: float, valid: bool = True) -> SimpleNamespace:
    return SimpleNamespace(pinch_valid=valid, pinch_distance=distance)


def test_threshold_a_uses_configured_ratio() -> None:
    assert calculate_threshold_a(
        min_distance=0.01,
        max_distance=0.11,
        threshold_ratio=0.65,
    ) == pytest.approx(0.075)


def test_calibration_uses_min_max_and_classifies_zones() -> None:
    config = PinchCalibrationConfig(
        open_hand_duration_s=1.0,
        pinch_hand_duration_s=1.0,
        threshold_ratio=0.65,
        min_valid_frames=3,
    )

    result = calibrate_from_samples(
        [_sample(0.08), _sample(0.09), _sample(0.10), _sample(0.01, valid=False)],
        [_sample(0.03), _sample(0.02), _sample(0.01)],
        config=config,
        thumb_node_id=4,
        target_finger_node_id=14,
    )

    assert result.min_distance == pytest.approx(0.01)
    assert result.max_distance == pytest.approx(0.10)
    assert result.threshold_a == pytest.approx(0.0685)
    assert result.open_valid_frame_count == 3
    assert result.pinch_valid_frame_count == 3
    assert result.distance_range == pytest.approx(0.09)
    assert result.distance_range_ratio == pytest.approx(0.9)
    assert result.calibration_passed is True
    assert result.calibration_failure_reason == ""
    assert result.thumb_node_id == 4
    assert result.target_finger_node_id == 14
    assert is_in_open_zone(result.threshold_a, result) is True
    assert is_in_open_zone(result.max_distance, result) is True
    assert is_in_closed_zone(result.min_distance, result) is True
    assert is_in_closed_zone(result.threshold_a, result) is True
    assert classify_pinch_zone(0.02, result) == "closed_zone"
    assert classify_pinch_zone(0.09, result) == "open_zone"


def test_calibration_records_contact_reference_distribution_and_boundaries() -> None:
    config = PinchCalibrationConfig(
        open_hand_duration_s=1.0,
        contact_hand_duration_s=1.0,
        pinch_hand_duration_s=1.0,
        threshold_ratio=0.65,
        min_valid_frames=3,
    )

    result = calibrate_from_samples(
        [_sample(0.099), _sample(0.100), _sample(0.101)],
        [_sample(0.019), _sample(0.020), _sample(0.021)],
        contact_samples=[_sample(0.059), _sample(0.060), _sample(0.061)],
        config=config,
    )

    assert result.open_distance_median == pytest.approx(0.100)
    assert result.contact_distance_median == pytest.approx(0.060)
    assert result.pinch_distance_median == pytest.approx(0.020)
    assert result.open_contact_boundary == pytest.approx(0.080)
    assert result.contact_pinch_boundary == pytest.approx(0.040)
    assert result.contact_valid_frame_count == 3
    assert result.pinch_reference_quality_passed is True
    assert result.pinch_reference_quality_reason == ""


def test_calibration_marks_bad_contact_reference_order() -> None:
    config = PinchCalibrationConfig(min_valid_frames=3)

    result = calibrate_from_samples(
        [_sample(0.090), _sample(0.091), _sample(0.092)],
        [_sample(0.020), _sample(0.021), _sample(0.022)],
        contact_samples=[_sample(0.100), _sample(0.101), _sample(0.102)],
        config=config,
    )

    assert result.pinch_reference_quality_passed is False
    assert result.pinch_reference_quality_reason == "reference_order_not_open_contact_pinch"


def test_repetition_calibration_records_normalized_contact_consistency() -> None:
    config = PinchCalibrationConfig(
        min_valid_frames=3,
        min_distance_range=0.0,
        min_distance_range_ratio=0.0,
        stable_recording_duration_s=1.0,
        stability_mad_max=None,
        stability_range_max=None,
    )

    result = calibrate_from_repetition_samples(
        {
            "open": [
                [_sample(0.100), _sample(0.101), _sample(0.099)],
                [_sample(0.100), _sample(0.101), _sample(0.099)],
                [_sample(0.100), _sample(0.101), _sample(0.099)],
            ],
            "contact": [
                [_sample(0.060), _sample(0.061), _sample(0.059)],
                [_sample(0.055), _sample(0.056), _sample(0.054)],
                [_sample(0.058), _sample(0.059), _sample(0.057)],
            ],
            "pinch": [
                [_sample(0.020), _sample(0.021), _sample(0.019)],
                [_sample(0.020), _sample(0.021), _sample(0.019)],
                [_sample(0.020), _sample(0.021), _sample(0.019)],
            ],
        },
        config=config,
    )

    assert result.calibration_schema_version == 3
    assert result.finger_repetition_count == 3
    assert result.normalized_contact_position == pytest.approx(0.525)
    assert result.contact_rep_position_range == pytest.approx(0.0625)
    assert all(row["passed"] for row in result.paired_repetition_qc)
    assert result.full_calibration_qc_passed is True


def test_paired_qc_accepts_consistent_pairs_despite_pooled_overlap() -> None:
    config = PinchCalibrationConfig(
        min_valid_frames=3,
        min_distance_range=0.0,
        min_distance_range_ratio=0.0,
        stability_mad_max=None,
        stability_range_max=None,
    )

    result = calibrate_from_repetition_samples(
        {
            "open": [_constant_samples(0.14560), _constant_samples(0.13689), _constant_samples(0.13828)],
            "contact": [_constant_samples(0.05907), _constant_samples(0.06770), _constant_samples(0.06055)],
            "pinch": [_constant_samples(0.04844), _constant_samples(0.05721), _constant_samples(0.05115)],
        },
        config=config,
    )

    assert result.pooled_reference_quality_passed is False
    assert (
        result.pooled_reference_quality_reason
        == "pinch_distribution_crosses_contact_pinch_boundary"
    )
    assert result.pinch_reference_quality_passed is True
    assert result.calibration_warnings == (
        "pinch_distribution_crosses_contact_pinch_boundary",
    )
    assert all(row["passed"] for row in result.paired_repetition_qc)
    assert result.full_calibration_qc_passed is True


def test_paired_qc_rejects_reversed_contact_and_pinch_repetition() -> None:
    config = PinchCalibrationConfig(
        min_valid_frames=3,
        min_distance_range=0.0,
        min_distance_range_ratio=0.0,
        stability_mad_max=None,
        stability_range_max=None,
    )

    result = calibrate_from_repetition_samples(
        {
            "open": [_constant_samples(0.14)] * 3,
            "contact": [
                _constant_samples(0.060),
                _constant_samples(0.045),
                _constant_samples(0.047),
            ],
            "pinch": [
                _constant_samples(0.050),
                _constant_samples(0.050),
                _constant_samples(0.051),
            ],
        },
        config=config,
    )

    assert result.pinch_reference_quality_passed is False
    assert result.full_calibration_qc_passed is False
    assert result.paired_repetition_qc[0]["passed"] is True
    assert result.paired_repetition_qc[1]["failed_pairs"] == ("contact_pinch",)
    assert result.paired_repetition_qc[2]["failed_pairs"] == ("contact_pinch",)
    assert "reference_order_not_open_contact_pinch" in result.full_calibration_qc_reasons


def test_calibration_requires_min_valid_frames() -> None:
    config = PinchCalibrationConfig(min_valid_frames=2)

    with pytest.raises(ValueError, match="open hand valid frame count"):
        calibrate_from_samples([_sample(0.08)], [_sample(0.02), _sample(0.01)], config=config)


def test_calibration_fails_when_min_max_range_is_too_small() -> None:
    config = PinchCalibrationConfig(
        min_valid_frames=3,
        min_distance_range=0.02,
        min_distance_range_ratio=0.15,
    )

    result = calibrate_from_samples(
        [_sample(0.051), _sample(0.052), _sample(0.053)],
        [_sample(0.050), _sample(0.0505), _sample(0.051)],
        config=config,
    )

    assert result.distance_range == pytest.approx(0.003)
    assert result.distance_range_ratio == pytest.approx(0.003 / 0.053)
    assert result.calibration_passed is False
    assert result.calibration_failure_reason == "max-min too small"


def _constant_samples(distance: float) -> list[SimpleNamespace]:
    return [_sample(distance) for _ in range(3)]
