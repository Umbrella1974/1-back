"""Pinch distance calibration helpers."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class PinchCalibrationConfig:
    """Config for open/closed hand pinch distance calibration."""

    open_hand_duration_s: float = 3.0
    pinch_hand_duration_s: float = 3.0
    threshold_ratio: float = 0.65
    min_valid_frames: int = 30

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "open_hand_duration_s",
            _positive_float(self.open_hand_duration_s, "open_hand_duration_s"),
        )
        object.__setattr__(
            self,
            "pinch_hand_duration_s",
            _positive_float(self.pinch_hand_duration_s, "pinch_hand_duration_s"),
        )
        ratio = float(self.threshold_ratio)
        if not math.isfinite(ratio) or ratio < 0.0 or ratio > 1.0:
            raise ValueError("threshold_ratio must be between 0 and 1.")
        object.__setattr__(self, "threshold_ratio", ratio)
        if isinstance(self.min_valid_frames, bool) or int(self.min_valid_frames) <= 0:
            raise ValueError("min_valid_frames must be a positive integer.")
        object.__setattr__(self, "min_valid_frames", int(self.min_valid_frames))


@dataclass(frozen=True)
class PinchCalibrationResult:
    """Computed min/max pinch distances and threshold a."""

    min_distance: float
    max_distance: float
    threshold_a: float
    threshold_ratio: float
    thumb_node_id: int
    target_finger_node_id: int
    open_hand_duration_s: float
    pinch_hand_duration_s: float
    open_valid_frame_count: int
    pinch_valid_frame_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_threshold_a(
    *,
    min_distance: float,
    max_distance: float,
    threshold_ratio: float,
) -> float:
    """Compute a = min + ratio * (max - min)."""

    min_value = _finite_float(min_distance, "min_distance")
    max_value = _finite_float(max_distance, "max_distance")
    ratio = _finite_float(threshold_ratio, "threshold_ratio")
    if ratio < 0.0 or ratio > 1.0:
        raise ValueError("threshold_ratio must be between 0 and 1.")
    if max_value <= min_value:
        raise ValueError("max_distance must be greater than min_distance.")
    return min_value + ratio * (max_value - min_value)


def calibrate_from_samples(
    open_samples: Iterable[Any],
    pinch_samples: Iterable[Any],
    *,
    config: PinchCalibrationConfig | None = None,
    thumb_node_id: int = 4,
    target_finger_node_id: int = 14,
) -> PinchCalibrationResult:
    """Compute calibration from parsed pinch samples."""

    return calibrate_from_distances(
        _valid_distances(open_samples),
        _valid_distances(pinch_samples),
        config=config,
        thumb_node_id=thumb_node_id,
        target_finger_node_id=target_finger_node_id,
    )


def calibrate_from_distances(
    open_distances: Iterable[float],
    pinch_distances: Iterable[float],
    *,
    config: PinchCalibrationConfig | None = None,
    thumb_node_id: int = 4,
    target_finger_node_id: int = 14,
) -> PinchCalibrationResult:
    """Compute calibration from valid open-hand and pinch-hand distances."""

    calibration_config = config or PinchCalibrationConfig()
    open_values = [_positive_float(value, "open_distance") for value in open_distances]
    pinch_values = [_positive_float(value, "pinch_distance") for value in pinch_distances]
    if len(open_values) < calibration_config.min_valid_frames:
        raise ValueError(
            f"open hand valid frame count {len(open_values)} is less than "
            f"min_valid_frames {calibration_config.min_valid_frames}."
        )
    if len(pinch_values) < calibration_config.min_valid_frames:
        raise ValueError(
            f"pinch hand valid frame count {len(pinch_values)} is less than "
            f"min_valid_frames {calibration_config.min_valid_frames}."
        )

    min_distance = min(pinch_values)
    max_distance = max(open_values)
    threshold_a = calculate_threshold_a(
        min_distance=min_distance,
        max_distance=max_distance,
        threshold_ratio=calibration_config.threshold_ratio,
    )
    return PinchCalibrationResult(
        min_distance=min_distance,
        max_distance=max_distance,
        threshold_a=threshold_a,
        threshold_ratio=calibration_config.threshold_ratio,
        thumb_node_id=int(thumb_node_id),
        target_finger_node_id=int(target_finger_node_id),
        open_hand_duration_s=calibration_config.open_hand_duration_s,
        pinch_hand_duration_s=calibration_config.pinch_hand_duration_s,
        open_valid_frame_count=len(open_values),
        pinch_valid_frame_count=len(pinch_values),
    )


def is_in_open_zone(distance: float | None, calibration: PinchCalibrationResult) -> bool:
    """Return true when distance is in [a, max_distance]."""

    if distance is None:
        return False
    value = float(distance)
    return calibration.threshold_a <= value <= calibration.max_distance


def is_in_closed_zone(distance: float | None, calibration: PinchCalibrationResult) -> bool:
    """Return true when distance is in [min_distance, a]."""

    if distance is None:
        return False
    value = float(distance)
    return calibration.min_distance <= value <= calibration.threshold_a


def classify_pinch_zone(
    distance: float | None,
    calibration: PinchCalibrationResult,
) -> str:
    """Classify one distance into closed_zone/open_zone/out_of_range/invalid."""

    if distance is None:
        return "invalid"
    value = float(distance)
    if not math.isfinite(value):
        return "invalid"
    if value < calibration.min_distance or value > calibration.max_distance:
        return "out_of_range"
    if value >= calibration.threshold_a:
        return "open_zone"
    return "closed_zone"


def _valid_distances(samples: Iterable[Any]) -> list[float]:
    distances: list[float] = []
    for sample in samples:
        if not bool(getattr(sample, "pinch_valid", False)):
            continue
        distance = getattr(sample, "pinch_distance", None)
        if distance is None:
            continue
        try:
            value = float(distance)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0.0:
            distances.append(value)
    return distances


def _finite_float(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number.")
    return result


def _positive_float(value: Any, name: str) -> float:
    result = _finite_float(value, name)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive.")
    return result

