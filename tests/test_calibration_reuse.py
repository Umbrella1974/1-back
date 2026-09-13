from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pinch_calibration import (
    PinchCalibrationConfig,
    calibrate_from_repetition_samples,
    calibrate_from_samples,
)
from run_pinch_haptic_1back import (
    CalibrationReuseConfig,
    _calibration_reuse_config_from_dict,
    _calibration_reuse_block_reason,
    _calibration_quick_check_detail_lines,
    _current_finger_state_validity,
    _load_calibration_bundle,
    _next_calibration_version_path,
    _pinch_open_quick_check_from_samples,
    _quick_check_state_summary,
    _save_calibration_bundle,
    _saved_finger_calibration_compatibility,
)


def test_next_calibration_version_path_increments_existing_v_suffix(tmp_path) -> None:
    first = tmp_path / "P001_exp2_cal_v01.json"
    first.write_text("{}", encoding="utf-8")

    assert _next_calibration_version_path(first) == tmp_path / "P001_exp2_cal_v02.json"


def test_save_and_load_calibration_bundle_round_trip(tmp_path) -> None:
    calibration = _calibration()
    target = tmp_path / "P001_exp2_cal_v01.json"

    saved = _save_calibration_bundle(
        calibration,
        None,
        reuse_config=CalibrationReuseConfig(
            enabled=True,
            calibration_out=target,
            calibration_id="P001_exp2_cal_v01",
        ),
        fallback_base_path=None,
    )
    assert saved == target

    payload = json.loads(target.read_text(encoding="utf-8"))
    loaded = _load_calibration_bundle(target)

    assert payload["calibration_id"] == "P001_exp2_cal_v01"
    assert loaded.calibration_id == "P001_exp2_cal_v01"
    assert loaded.pinch_calibration.open_distance_median == pytest.approx(0.100)
    assert loaded.wrist_rotation_calibration is None


def test_save_calibration_bundle_updates_id_when_version_increments(tmp_path) -> None:
    calibration = _calibration()
    first = tmp_path / "P001_exp2_cal_v01.json"
    first.write_text("{}", encoding="utf-8")

    saved = _save_calibration_bundle(
        calibration,
        None,
        reuse_config=CalibrationReuseConfig(
            enabled=True,
            calibration_out=first,
            calibration_id="P001_exp2_cal_v01",
        ),
        fallback_base_path=None,
    )

    assert saved == tmp_path / "P001_exp2_cal_v02.json"
    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload["calibration_id"] == "P001_exp2_cal_v02"


def test_pinch_open_quick_check_passes_near_reference() -> None:
    calibration = _calibration()

    result = _pinch_open_quick_check_from_samples(
        [_sample(0.099), _sample(0.100), _sample(0.101)],
        calibration=calibration,
        min_valid_frames=3,
        open_mad_multiplier=6.0,
        open_distance_min_tolerance=0.0,
    )

    assert result.passed is True
    assert result.open_distance_delta == pytest.approx(0.0)


def test_pinch_open_quick_check_allows_range_based_open_distance_drift() -> None:
    calibration = _low_mad_calibration()

    result = _pinch_open_quick_check_from_samples(
        [_sample(0.1039), _sample(0.1040), _sample(0.1041)],
        calibration=calibration,
        min_valid_frames=3,
        open_mad_multiplier=6.0,
        open_distance_range_ratio=0.05,
        open_distance_min_tolerance=0.0,
    )

    assert result.passed is True
    assert result.open_distance_delta == pytest.approx(0.004)
    assert result.open_distance_tolerance == pytest.approx(calibration.distance_range * 0.05)


def test_pinch_open_quick_check_fails_when_open_distance_shifts_past_tolerance() -> None:
    calibration = _low_mad_calibration()

    result = _pinch_open_quick_check_from_samples(
        [_sample(0.1099), _sample(0.1100), _sample(0.1101)],
        calibration=calibration,
        min_valid_frames=3,
        open_mad_multiplier=6.0,
        open_distance_range_ratio=0.05,
        open_distance_min_tolerance=0.0,
    )

    assert result.passed is False
    assert result.reason == "open_distance_shifted_from_reference"


def test_calibration_quick_check_detail_lines_include_open_shift_context() -> None:
    calibration = _low_mad_calibration()

    result = _pinch_open_quick_check_from_samples(
        [_sample(0.1099), _sample(0.1100), _sample(0.1101)],
        calibration=calibration,
        min_valid_frames=3,
        open_mad_multiplier=6.0,
        open_distance_range_ratio=0.05,
        open_distance_min_tolerance=0.0,
    )

    details = "\n".join(_calibration_quick_check_detail_lines(result))

    assert "reference=100.00 mm" in details
    assert "current=110.00 mm" in details
    assert "delta=10.00 mm" in details
    assert "allowed=4.05 mm" in details
    assert "over_by=5.94 mm" in details


def test_calibration_reuse_config_reads_open_distance_tolerance_fields(tmp_path) -> None:
    config = _calibration_reuse_config_from_dict(
        {
            "enabled": True,
            "calibration_in": "P001_exp2_cal_v01.json",
            "open_distance_range_ratio": 0.08,
            "open_distance_min_tolerance": 0.006,
        },
        config_path=tmp_path / "config.yaml",
    )

    assert config.open_distance_range_ratio == pytest.approx(0.08)
    assert config.open_distance_min_tolerance == pytest.approx(0.006)


def test_calibration_reuse_blocks_legacy_calibration_for_new_protocol() -> None:
    assert (
        _calibration_reuse_block_reason(_calibration())
        == "legacy_calibration_requires_new_full_calibration"
    )


def test_calibration_reuse_allows_good_v2_reference_quality() -> None:
    assert _calibration_reuse_block_reason(_v2_calibration()) == ""


def test_calibration_reuse_blocks_bad_reference_quality() -> None:
    calibration = replace(
        _v2_calibration(),
        pinch_reference_quality_passed=False,
        pinch_reference_quality_reason="reference_overlap",
    )

    reason = _calibration_reuse_block_reason(calibration)

    assert reason == "loaded_pinch_reference_quality_failed:reference_overlap"


def test_calibration_reuse_blocks_failed_calibration() -> None:
    calibration = replace(
        _v2_calibration(),
        calibration_passed=False,
        calibration_failure_reason="not_enough_valid_frames",
    )

    reason = _calibration_reuse_block_reason(calibration)

    assert reason == "loaded_calibration_failed:not_enough_valid_frames"


def test_quick_check_small_separated_gap_is_warning_not_failure() -> None:
    summaries = {
        "open": _quick_check_state_summary([_sample(0.139), _sample(0.140), _sample(0.141)]),
        "contact": _quick_check_state_summary([_sample(0.0365), _sample(0.0370), _sample(0.0375)]),
        "pinch": _quick_check_state_summary([_sample(0.0305), _sample(0.0310), _sample(0.0315)]),
    }

    result = _current_finger_state_validity(
        summaries,
        min_valid_frames=3,
        calibration_config=PinchCalibrationConfig(min_valid_frames=3),
    )

    assert result["passed"] is True
    assert result["failed_components"] == ()
    assert result["warnings"] == (
        "quick_check_contact_pinch_gap_below_preferred_ratio",
    )


def test_quick_check_overlapping_distributions_still_fail() -> None:
    summaries = {
        "open": _quick_check_state_summary([_sample(0.139), _sample(0.140), _sample(0.141)]),
        "contact": _quick_check_state_summary([_sample(0.036), _sample(0.040), _sample(0.044)]),
        "pinch": _quick_check_state_summary([_sample(0.038), _sample(0.039), _sample(0.040)]),
    }

    result = _current_finger_state_validity(
        summaries,
        min_valid_frames=3,
        calibration_config=PinchCalibrationConfig(min_valid_frames=3),
    )

    assert result["passed"] is False
    assert "quick_check_contact_pinch_distribution_overlap" in result["reasons"]
    assert result["failed_components"] == ("contact", "pinch")


def test_saved_boundary_margin_is_warning_when_classification_is_correct() -> None:
    calibration = _low_contact_pinch_gap_calibration()
    samples = {
        "open": [_sample(0.139), _sample(0.140), _sample(0.141)],
        "contact": [_sample(0.0365), _sample(0.0370), _sample(0.0375)],
        "pinch": [_sample(0.0305), _sample(0.0310), _sample(0.0315)],
    }

    result = _saved_finger_calibration_compatibility(
        samples,
        calibration=calibration,
        min_ratio=0.80,
        min_margin_ratio=0.05,
    )

    assert result["passed"] is True
    assert result["failed_components"] == ()
    assert "contact_saved_boundary_margin_below_preferred_ratio" in result["warnings"]
    assert "pinch_saved_boundary_margin_below_preferred_ratio" in result["warnings"]


def _calibration():
    config = PinchCalibrationConfig(
        open_hand_duration_s=1.0,
        contact_hand_duration_s=1.0,
        pinch_hand_duration_s=1.0,
        min_valid_frames=3,
        min_distance_range=0.0,
        min_distance_range_ratio=0.0,
    )
    return calibrate_from_samples(
        [_sample(0.099), _sample(0.100), _sample(0.101)],
        [_sample(0.019), _sample(0.020), _sample(0.021)],
        contact_samples=[_sample(0.059), _sample(0.060), _sample(0.061)],
        config=config,
    )


def _low_mad_calibration():
    config = PinchCalibrationConfig(
        open_hand_duration_s=1.0,
        contact_hand_duration_s=1.0,
        pinch_hand_duration_s=1.0,
        min_valid_frames=3,
        min_distance_range=0.0,
        min_distance_range_ratio=0.0,
    )
    return calibrate_from_samples(
        [_sample(0.0999), _sample(0.1000), _sample(0.1001)],
        [_sample(0.019), _sample(0.020), _sample(0.021)],
        contact_samples=[_sample(0.059), _sample(0.060), _sample(0.061)],
        config=config,
    )


def _low_contact_pinch_gap_calibration():
    config = PinchCalibrationConfig(
        open_hand_duration_s=1.0,
        contact_hand_duration_s=1.0,
        pinch_hand_duration_s=1.0,
        stable_recording_duration_s=1.0,
        min_valid_frames=3,
        min_distance_range=0.0,
        min_distance_range_ratio=0.0,
        stability_mad_max=None,
        stability_range_max=None,
    )
    return calibrate_from_repetition_samples(
        {
            "open": [[_sample(0.139), _sample(0.140), _sample(0.141)]] * 3,
            "contact": [[_sample(0.0365), _sample(0.0370), _sample(0.0375)]] * 3,
            "pinch": [[_sample(0.0305), _sample(0.0310), _sample(0.0315)]] * 3,
        },
        config=config,
    )


def _v2_calibration():
    config = PinchCalibrationConfig(
        open_hand_duration_s=1.0,
        contact_hand_duration_s=1.0,
        pinch_hand_duration_s=1.0,
        stable_recording_duration_s=1.0,
        min_valid_frames=3,
        min_distance_range=0.0,
        min_distance_range_ratio=0.0,
        stability_mad_max=None,
        stability_range_max=None,
    )
    return calibrate_from_repetition_samples(
        {
            "open": [
                [_sample(0.099), _sample(0.100), _sample(0.101)],
                [_sample(0.100), _sample(0.101), _sample(0.102)],
                [_sample(0.098), _sample(0.099), _sample(0.100)],
            ],
            "contact": [
                [_sample(0.059), _sample(0.060), _sample(0.061)],
                [_sample(0.060), _sample(0.061), _sample(0.062)],
                [_sample(0.058), _sample(0.059), _sample(0.060)],
            ],
            "pinch": [
                [_sample(0.019), _sample(0.020), _sample(0.021)],
                [_sample(0.020), _sample(0.021), _sample(0.022)],
                [_sample(0.018), _sample(0.019), _sample(0.020)],
            ],
        },
        config=config,
    )


def _sample(distance: float, valid: bool = True) -> SimpleNamespace:
    return SimpleNamespace(pinch_valid=valid, pinch_distance=distance)
