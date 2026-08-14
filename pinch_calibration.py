"""Pinch distance calibration helpers."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any, Iterable


@dataclass(frozen=True)
class PinchCalibrationConfig:
    """Config for open/closed hand pinch distance calibration."""

    open_hand_duration_s: float = 3.0
    contact_hand_duration_s: float = 3.0
    pinch_hand_duration_s: float = 3.0
    threshold_ratio: float = 0.65
    min_valid_frames: int = 30
    min_distance_range: float = 0.02
    min_distance_range_ratio: float = 0.15

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
        object.__setattr__(
            self,
            "contact_hand_duration_s",
            _positive_float(self.contact_hand_duration_s, "contact_hand_duration_s"),
        )
        ratio = float(self.threshold_ratio)
        if not math.isfinite(ratio) or ratio < 0.0 or ratio > 1.0:
            raise ValueError("threshold_ratio must be between 0 and 1.")
        object.__setattr__(self, "threshold_ratio", ratio)
        if isinstance(self.min_valid_frames, bool) or int(self.min_valid_frames) <= 0:
            raise ValueError("min_valid_frames must be a positive integer.")
        object.__setattr__(self, "min_valid_frames", int(self.min_valid_frames))
        object.__setattr__(
            self,
            "min_distance_range",
            _non_negative_float(self.min_distance_range, "min_distance_range"),
        )
        range_ratio = _finite_float(
            self.min_distance_range_ratio,
            "min_distance_range_ratio",
        )
        if range_ratio < 0.0 or range_ratio > 1.0:
            raise ValueError("min_distance_range_ratio must be between 0 and 1.")
        object.__setattr__(self, "min_distance_range_ratio", range_ratio)


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
    contact_hand_duration_s: float | None = None
    contact_valid_frame_count: int = 0
    open_distance_mean: float | None = None
    open_distance_median: float | None = None
    open_distance_mad: float | None = None
    open_distance_p10: float | None = None
    open_distance_p90: float | None = None
    contact_distance_mean: float | None = None
    contact_distance_median: float | None = None
    contact_distance_mad: float | None = None
    contact_distance_p10: float | None = None
    contact_distance_p90: float | None = None
    pinch_distance_mean: float | None = None
    pinch_distance_median: float | None = None
    pinch_distance_mad: float | None = None
    pinch_distance_p10: float | None = None
    pinch_distance_p90: float | None = None
    open_contact_boundary: float | None = None
    contact_pinch_boundary: float | None = None
    pinch_reference_quality_passed: bool | None = None
    pinch_reference_quality_reason: str = ""
    distance_range: float | None = None
    distance_range_ratio: float | None = None
    calibration_passed: bool = True
    calibration_failure_reason: str = ""

    def __post_init__(self) -> None:
        distance_range = float(self.max_distance) - float(self.min_distance)
        distance_range_ratio = (
            distance_range / float(self.max_distance)
            if float(self.max_distance) > 0.0
            else 0.0
        )
        if self.distance_range is None:
            object.__setattr__(self, "distance_range", distance_range)
        if self.distance_range_ratio is None:
            object.__setattr__(self, "distance_range_ratio", distance_range_ratio)

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
    contact_samples: Iterable[Any] | None = None,
    config: PinchCalibrationConfig | None = None,
    thumb_node_id: int = 4,
    target_finger_node_id: int = 14,
) -> PinchCalibrationResult:
    """Compute calibration from parsed pinch samples."""

    return calibrate_from_distances(
        _valid_distances(open_samples),
        _valid_distances(pinch_samples),
        contact_distances=(
            _valid_distances(contact_samples) if contact_samples is not None else None
        ),
        config=config,
        thumb_node_id=thumb_node_id,
        target_finger_node_id=target_finger_node_id,
    )


def calibrate_from_distances(
    open_distances: Iterable[float],
    pinch_distances: Iterable[float],
    *,
    contact_distances: Iterable[float] | None = None,
    config: PinchCalibrationConfig | None = None,
    thumb_node_id: int = 4,
    target_finger_node_id: int = 14,
) -> PinchCalibrationResult:
    """Compute calibration from valid open-hand and pinch-hand distances."""

    calibration_config = config or PinchCalibrationConfig()
    open_values = [_positive_float(value, "open_distance") for value in open_distances]
    pinch_values = [_positive_float(value, "pinch_distance") for value in pinch_distances]
    contact_values = (
        [_positive_float(value, "contact_distance") for value in contact_distances]
        if contact_distances is not None
        else []
    )
    if len(open_values) < calibration_config.min_valid_frames:
        raise ValueError(
            f"open hand valid frame count {len(open_values)} is less than "
            f"min_valid_frames {calibration_config.min_valid_frames}."
        )
    if contact_distances is not None and len(contact_values) < calibration_config.min_valid_frames:
        raise ValueError(
            f"contact hand valid frame count {len(contact_values)} is less than "
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
    quality = check_calibration_quality(
        min_distance=min_distance,
        max_distance=max_distance,
        config=calibration_config,
    )
    open_summary = _distribution_summary(open_values)
    contact_summary = _distribution_summary(contact_values) if contact_values else {}
    pinch_summary = _distribution_summary(pinch_values)
    reference_quality = _pinch_reference_quality(open_summary, contact_summary, pinch_summary)
    return PinchCalibrationResult(
        min_distance=min_distance,
        max_distance=max_distance,
        threshold_a=threshold_a,
        threshold_ratio=calibration_config.threshold_ratio,
        thumb_node_id=int(thumb_node_id),
        target_finger_node_id=int(target_finger_node_id),
        open_hand_duration_s=calibration_config.open_hand_duration_s,
        contact_hand_duration_s=(
            calibration_config.contact_hand_duration_s if contact_values else None
        ),
        pinch_hand_duration_s=calibration_config.pinch_hand_duration_s,
        open_valid_frame_count=len(open_values),
        contact_valid_frame_count=len(contact_values),
        pinch_valid_frame_count=len(pinch_values),
        open_distance_mean=open_summary.get("mean"),
        open_distance_median=open_summary.get("median"),
        open_distance_mad=open_summary.get("mad"),
        open_distance_p10=open_summary.get("p10"),
        open_distance_p90=open_summary.get("p90"),
        contact_distance_mean=contact_summary.get("mean"),
        contact_distance_median=contact_summary.get("median"),
        contact_distance_mad=contact_summary.get("mad"),
        contact_distance_p10=contact_summary.get("p10"),
        contact_distance_p90=contact_summary.get("p90"),
        pinch_distance_mean=pinch_summary.get("mean"),
        pinch_distance_median=pinch_summary.get("median"),
        pinch_distance_mad=pinch_summary.get("mad"),
        pinch_distance_p10=pinch_summary.get("p10"),
        pinch_distance_p90=pinch_summary.get("p90"),
        open_contact_boundary=reference_quality.get("open_contact_boundary"),
        contact_pinch_boundary=reference_quality.get("contact_pinch_boundary"),
        pinch_reference_quality_passed=reference_quality.get("passed"),
        pinch_reference_quality_reason=reference_quality.get("reason", ""),
        distance_range=quality["distance_range"],
        distance_range_ratio=quality["distance_range_ratio"],
        calibration_passed=quality["calibration_passed"],
        calibration_failure_reason=quality["calibration_failure_reason"],
    )


def check_calibration_quality(
    *,
    min_distance: float,
    max_distance: float,
    config: PinchCalibrationConfig | None = None,
) -> dict[str, Any]:
    """Return range-based calibration quality fields."""

    calibration_config = config or PinchCalibrationConfig()
    min_value = _finite_float(min_distance, "min_distance")
    max_value = _finite_float(max_distance, "max_distance")
    distance_range = max_value - min_value
    distance_range_ratio = distance_range / max_value if max_value > 0.0 else 0.0
    failure_reason = ""
    if (
        distance_range < calibration_config.min_distance_range
        or distance_range_ratio < calibration_config.min_distance_range_ratio
    ):
        failure_reason = "max-min too small"
    return {
        "distance_range": distance_range,
        "distance_range_ratio": distance_range_ratio,
        "calibration_passed": not failure_reason,
        "calibration_failure_reason": failure_reason,
    }


def _distribution_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    center = median(ordered)
    return {
        "mean": sum(ordered) / len(ordered),
        "median": center,
        "mad": median([abs(value - center) for value in ordered]),
        "p10": _percentile(ordered, 0.10),
        "p90": _percentile(ordered, 0.90),
    }


def _pinch_reference_quality(
    open_summary: dict[str, float],
    contact_summary: dict[str, float],
    pinch_summary: dict[str, float],
) -> dict[str, Any]:
    if not contact_summary:
        return {"passed": None, "reason": "contact_reference_not_collected"}
    open_median = open_summary["median"]
    contact_median = contact_summary["median"]
    pinch_median = pinch_summary["median"]
    if not (open_median > contact_median > pinch_median):
        return {
            "passed": False,
            "reason": "reference_order_not_open_contact_pinch",
        }
    open_contact_boundary = (open_median + contact_median) / 2.0
    contact_pinch_boundary = (contact_median + pinch_median) / 2.0
    overlap_reasons = []
    if open_summary["p10"] < open_contact_boundary:
        overlap_reasons.append("open_distribution_crosses_open_contact_boundary")
    if contact_summary["p90"] > open_contact_boundary:
        overlap_reasons.append("contact_distribution_crosses_open_contact_boundary")
    if contact_summary["p10"] < contact_pinch_boundary:
        overlap_reasons.append("contact_distribution_crosses_contact_pinch_boundary")
    if pinch_summary["p90"] > contact_pinch_boundary:
        overlap_reasons.append("pinch_distribution_crosses_contact_pinch_boundary")
    return {
        "passed": not overlap_reasons,
        "reason": ";".join(overlap_reasons),
        "open_contact_boundary": open_contact_boundary,
        "contact_pinch_boundary": contact_pinch_boundary,
    }


def _percentile(ordered_values: list[float], fraction: float) -> float:
    if not ordered_values:
        raise ValueError("ordered_values must not be empty.")
    if len(ordered_values) == 1:
        return ordered_values[0]
    rank = (len(ordered_values) - 1) * fraction
    lower_index = int(math.floor(rank))
    upper_index = int(math.ceil(rank))
    if lower_index == upper_index:
        return ordered_values[lower_index]
    lower = ordered_values[lower_index]
    upper = ordered_values[upper_index]
    return lower + (upper - lower) * (rank - lower_index)


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


def _non_negative_float(value: Any, name: str) -> float:
    result = _finite_float(value, name)
    if result < 0.0:
        raise ValueError(f"{name} must be non-negative.")
    return result
