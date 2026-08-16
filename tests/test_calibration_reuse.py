from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pinch_calibration import PinchCalibrationConfig, calibrate_from_samples
from run_pinch_haptic_1back import (
    CalibrationReuseConfig,
    _calibration_reuse_block_reason,
    _load_calibration_bundle,
    _next_calibration_version_path,
    _pinch_open_quick_check_from_samples,
    _save_calibration_bundle,
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
    )

    assert result.passed is True
    assert result.open_distance_delta == pytest.approx(0.0)


def test_pinch_open_quick_check_fails_when_open_distance_shifts() -> None:
    calibration = _calibration()

    result = _pinch_open_quick_check_from_samples(
        [_sample(0.089), _sample(0.090), _sample(0.091)],
        calibration=calibration,
        min_valid_frames=3,
        open_mad_multiplier=6.0,
    )

    assert result.passed is False
    assert result.reason == "open_distance_shifted_from_reference"


def test_calibration_reuse_allows_good_reference_quality() -> None:
    assert _calibration_reuse_block_reason(_calibration()) == ""


def test_calibration_reuse_blocks_bad_reference_quality() -> None:
    calibration = replace(
        _calibration(),
        pinch_reference_quality_passed=False,
        pinch_reference_quality_reason="reference_overlap",
    )

    reason = _calibration_reuse_block_reason(calibration)

    assert reason == "loaded_pinch_reference_quality_failed:reference_overlap"


def test_calibration_reuse_blocks_failed_calibration() -> None:
    calibration = replace(
        _calibration(),
        calibration_passed=False,
        calibration_failure_reason="not_enough_valid_frames",
    )

    reason = _calibration_reuse_block_reason(calibration)

    assert reason == "loaded_calibration_failed:not_enough_valid_frames"


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


def _sample(distance: float, valid: bool = True) -> SimpleNamespace:
    return SimpleNamespace(pinch_valid=valid, pinch_distance=distance)
