"""Pinch distance calibration helpers."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
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
    repetition_count: int = 3
    stability_window_s: float = 0.5
    stability_dwell_s: float = 0.4
    stable_recording_duration_s: float = 1.5
    quick_check_recording_duration_s: float = 0.75
    stability_valid_ratio_min: float = 0.8
    stability_mad_max: float | None = 0.004
    stability_range_max: float | None = 0.015
    stability_timeout_s: float = 8.0
    max_acquisition_attempts: int = 3
    min_state_gap_ratio: float = 0.10
    max_contact_rep_position_range: float = 0.25
    max_state_rep_median_range_ratio: float = 0.20
    contact_position_min: float | None = None
    contact_position_max: float | None = None

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
        if isinstance(self.repetition_count, bool) or int(self.repetition_count) <= 0:
            raise ValueError("repetition_count must be a positive integer.")
        object.__setattr__(self, "repetition_count", int(self.repetition_count))
        for name in (
            "stability_window_s",
            "stability_dwell_s",
            "stable_recording_duration_s",
            "quick_check_recording_duration_s",
            "stability_timeout_s",
        ):
            object.__setattr__(self, name, _positive_float(getattr(self, name), name))
        if (
            isinstance(self.max_acquisition_attempts, bool)
            or int(self.max_acquisition_attempts) <= 0
        ):
            raise ValueError("max_acquisition_attempts must be a positive integer.")
        object.__setattr__(
            self,
            "max_acquisition_attempts",
            int(self.max_acquisition_attempts),
        )
        for name in (
            "stability_valid_ratio_min",
            "min_state_gap_ratio",
            "max_contact_rep_position_range",
            "max_state_rep_median_range_ratio",
        ):
            value = _finite_float(getattr(self, name), name)
            if value < 0.0 or value > 1.0:
                raise ValueError(f"{name} must be between 0 and 1.")
            object.__setattr__(self, name, value)
        for name in ("stability_mad_max", "stability_range_max"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _non_negative_float(value, name))
        for name in ("contact_position_min", "contact_position_max"):
            value = getattr(self, name)
            if value is not None:
                value = _finite_float(value, name)
                if value < 0.0 or value > 1.0:
                    raise ValueError(f"{name} must be between 0 and 1.")
                object.__setattr__(self, name, value)
        if (
            self.contact_position_min is not None
            and self.contact_position_max is not None
            and self.contact_position_min > self.contact_position_max
        ):
            raise ValueError("contact_position_min must be <= contact_position_max.")
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
    calibration_schema_version: int = 1
    acquisition_protocol: str = "legacy_static_hold_v1"
    finger_repetition_count: int = 1
    finger_repetitions: tuple[dict[str, Any], ...] = ()
    finger_state_summaries: dict[str, dict[str, Any]] | None = None
    open_contact_gap: float | None = None
    contact_pinch_gap: float | None = None
    open_contact_gap_ratio: float | None = None
    contact_pinch_gap_ratio: float | None = None
    normalized_contact_position: float | None = None
    contact_rep_normalized_positions: tuple[float, ...] = ()
    contact_rep_position_range: float | None = None
    contact_rep_position_mad: float | None = None
    open_rep_median_range_ratio: float | None = None
    contact_rep_median_range_ratio: float | None = None
    pinch_rep_median_range_ratio: float | None = None
    paired_repetition_qc: tuple[dict[str, Any], ...] = ()
    pooled_reference_quality_passed: bool | None = None
    pooled_reference_quality_reason: str = ""
    calibration_warnings: tuple[str, ...] = ()
    full_calibration_qc_passed: bool | None = None
    full_calibration_qc_reasons: tuple[str, ...] = ()

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


def calibrate_from_repetition_samples(
    repetitions: dict[str, Iterable[Iterable[Any]]],
    *,
    config: PinchCalibrationConfig | None = None,
    thumb_node_id: int = 4,
    target_finger_node_id: int = 14,
) -> PinchCalibrationResult:
    """Compute calibration from staged Open/C/Pinch repetition samples."""

    return calibrate_from_repetition_distances(
        {
            state: [_valid_distances(samples) for samples in state_repetitions]
            for state, state_repetitions in repetitions.items()
        },
        config=config,
        thumb_node_id=thumb_node_id,
        target_finger_node_id=target_finger_node_id,
    )


def calibrate_from_repetition_distances(
    repetitions: dict[str, Iterable[Iterable[float]]],
    *,
    config: PinchCalibrationConfig | None = None,
    thumb_node_id: int = 4,
    target_finger_node_id: int = 14,
) -> PinchCalibrationResult:
    """Compute calibration and repetition consistency QC from staged distances."""

    cfg = config or PinchCalibrationConfig()
    normalized = _normalize_repetition_distances(repetitions, cfg)
    open_reps = normalized["open"]
    contact_reps = normalized["contact"]
    pinch_reps = normalized["pinch"]
    result = calibrate_from_distances(
        _flatten(open_reps),
        _flatten(pinch_reps),
        contact_distances=_flatten(contact_reps),
        config=cfg,
        thumb_node_id=thumb_node_id,
        target_finger_node_id=target_finger_node_id,
    )
    repetition_fields = _finger_repetition_fields(
        open_reps,
        contact_reps,
        pinch_reps,
        config=cfg,
    )
    paired_reference_reasons = list(
        repetition_fields["paired_reference_qc_reasons"]
    )
    if result.open_contact_boundary is None or result.contact_pinch_boundary is None:
        paired_reference_reasons.append("pooled_reference_boundaries_unavailable")
    reasons = list(repetition_fields["full_calibration_qc_reasons"])
    reasons.extend(paired_reference_reasons)
    if not result.calibration_passed and result.calibration_failure_reason:
        reasons.append(result.calibration_failure_reason)
    calibration_warnings = list(repetition_fields["calibration_qc_warnings"])
    if result.pinch_reference_quality_passed is False and result.pinch_reference_quality_reason:
        calibration_warnings.extend(
            item
            for item in result.pinch_reference_quality_reason.split(";")
            if item
        )
    paired_reference_reasons = list(dict.fromkeys(paired_reference_reasons))
    return replace(
        result,
        calibration_schema_version=3,
        acquisition_protocol="staged_repetition_v1",
        finger_repetition_count=len(open_reps),
        finger_repetitions=tuple(repetition_fields["finger_repetitions"]),
        finger_state_summaries=repetition_fields["finger_state_summaries"],
        open_contact_gap=repetition_fields["open_contact_gap"],
        contact_pinch_gap=repetition_fields["contact_pinch_gap"],
        open_contact_gap_ratio=repetition_fields["open_contact_gap_ratio"],
        contact_pinch_gap_ratio=repetition_fields["contact_pinch_gap_ratio"],
        normalized_contact_position=repetition_fields["normalized_contact_position"],
        contact_rep_normalized_positions=tuple(
            repetition_fields["contact_rep_normalized_positions"]
        ),
        contact_rep_position_range=repetition_fields["contact_rep_position_range"],
        contact_rep_position_mad=repetition_fields["contact_rep_position_mad"],
        open_rep_median_range_ratio=repetition_fields["open_rep_median_range_ratio"],
        contact_rep_median_range_ratio=repetition_fields["contact_rep_median_range_ratio"],
        pinch_rep_median_range_ratio=repetition_fields["pinch_rep_median_range_ratio"],
        paired_repetition_qc=tuple(repetition_fields["paired_repetition_qc"]),
        pooled_reference_quality_passed=result.pinch_reference_quality_passed,
        pooled_reference_quality_reason=result.pinch_reference_quality_reason,
        pinch_reference_quality_passed=not paired_reference_reasons,
        pinch_reference_quality_reason=";".join(paired_reference_reasons),
        calibration_warnings=tuple(dict.fromkeys(calibration_warnings)),
        full_calibration_qc_passed=not reasons,
        full_calibration_qc_reasons=tuple(dict.fromkeys(reasons)),
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


def _normalize_repetition_distances(
    repetitions: dict[str, Iterable[Iterable[float]]],
    config: PinchCalibrationConfig,
) -> dict[str, list[list[float]]]:
    result: dict[str, list[list[float]]] = {}
    for state in ("open", "contact", "pinch"):
        state_reps = list(repetitions.get(state, ()))
        if len(state_reps) < int(config.repetition_count):
            raise ValueError(f"{state} repetition count is less than {config.repetition_count}.")
        parsed: list[list[float]] = []
        for index, rep in enumerate(state_reps[: int(config.repetition_count)], start=1):
            values = [_positive_float(value, f"{state}_rep{index}_distance") for value in rep]
            if len(values) < config.min_valid_frames:
                raise ValueError(
                    f"{state} rep {index} valid frame count {len(values)} is less than "
                    f"min_valid_frames {config.min_valid_frames}."
                )
            parsed.append(values)
        result[state] = parsed
    return result


def _finger_repetition_fields(
    open_reps: list[list[float]],
    contact_reps: list[list[float]],
    pinch_reps: list[list[float]],
    *,
    config: PinchCalibrationConfig,
) -> dict[str, Any]:
    reps_by_state = {
        "open": open_reps,
        "contact": contact_reps,
        "pinch": pinch_reps,
    }
    state_summaries: dict[str, dict[str, Any]] = {}
    repetition_rows: list[dict[str, Any]] = []
    for state, state_reps in reps_by_state.items():
        medians: list[float] = []
        for index, values in enumerate(state_reps, start=1):
            summary = _distribution_summary(values)
            medians.append(summary["median"])
            row = {
                "requested_state": state,
                "repetition_index": index,
                "phase": f"{state}_rep{index}",
                "valid_count": len(values),
                "acquisition_duration_s": _state_duration_s(state, config),
                **summary,
            }
            row["range"] = summary["p90"] - summary["p10"]
            repetition_rows.append(row)
        state_summaries[state] = {
            "repetition_count": len(state_reps),
            "pooled": _distribution_summary(_flatten(state_reps)),
            "rep_medians": tuple(medians),
            "rep_median_range": max(medians) - min(medians) if medians else None,
            "rep_median_mad": _mad(medians) if medians else None,
        }

    open_median = state_summaries["open"]["pooled"]["median"]
    contact_median = state_summaries["contact"]["pooled"]["median"]
    pinch_median = state_summaries["pinch"]["pooled"]["median"]
    open_pinch_range = open_median - pinch_median
    open_contact_gap = open_median - contact_median
    contact_pinch_gap = contact_median - pinch_median
    open_contact_gap_ratio = _safe_ratio(open_contact_gap, open_pinch_range)
    contact_pinch_gap_ratio = _safe_ratio(contact_pinch_gap, open_pinch_range)
    normalized_contact = _safe_ratio(open_contact_gap, open_pinch_range)
    paired_count = min(len(open_reps), len(contact_reps), len(pinch_reps))
    contact_positions: list[float] = []
    paired_rows: list[dict[str, Any]] = []
    paired_reference_reasons: list[str] = []
    paired_reference_warnings: list[str] = []
    for index in range(paired_count):
        open_summary = _distribution_summary(open_reps[index])
        contact_summary = _distribution_summary(contact_reps[index])
        pinch_summary = _distribution_summary(pinch_reps[index])
        open_rep_median = open_summary["median"]
        contact_rep_median = contact_summary["median"]
        pinch_rep_median = pinch_summary["median"]
        rep_range = open_rep_median - pinch_rep_median
        open_contact_rep_gap = open_rep_median - contact_rep_median
        contact_pinch_rep_gap = contact_rep_median - pinch_rep_median
        open_contact_rep_ratio = _safe_ratio(open_contact_rep_gap, rep_range)
        contact_pinch_rep_ratio = _safe_ratio(contact_pinch_rep_gap, rep_range)
        position = _safe_ratio(
            open_contact_rep_gap,
            rep_range,
        )
        if position is not None and math.isfinite(position):
            contact_positions.append(position)

        rep_reasons: list[str] = []
        rep_warnings: list[str] = []
        failed_pairs: list[str] = []
        if not open_rep_median > contact_rep_median:
            rep_reasons.append("open_contact_order_invalid")
            failed_pairs.append("open_contact")
            paired_reference_reasons.append("reference_order_not_open_contact_pinch")
        if not contact_rep_median > pinch_rep_median:
            rep_reasons.append("contact_pinch_order_invalid")
            failed_pairs.append("contact_pinch")
            paired_reference_reasons.append("reference_order_not_open_contact_pinch")
        if (
            open_contact_rep_ratio is None
            or open_contact_rep_ratio < config.min_state_gap_ratio
        ):
            rep_warnings.append("open_contact_gap_below_preferred_ratio")
            paired_reference_warnings.append("open_contact_gap_below_preferred_ratio")
        if (
            contact_pinch_rep_ratio is None
            or contact_pinch_rep_ratio < config.min_state_gap_ratio
        ):
            rep_warnings.append("contact_pinch_gap_below_preferred_ratio")
            paired_reference_warnings.append("contact_pinch_gap_below_preferred_ratio")
        if open_summary["p10"] <= contact_summary["p90"]:
            rep_reasons.append("open_contact_distribution_overlap")
            failed_pairs.append("open_contact")
            paired_reference_reasons.append("paired_open_contact_distribution_overlap")
        if contact_summary["p10"] <= pinch_summary["p90"]:
            rep_reasons.append("contact_pinch_distribution_overlap")
            failed_pairs.append("contact_pinch")
            paired_reference_reasons.append("paired_contact_pinch_distribution_overlap")
        paired_rows.append(
            {
                "repetition_index": index + 1,
                "open_median": open_rep_median,
                "contact_median": contact_rep_median,
                "pinch_median": pinch_rep_median,
                "open_contact_gap": open_contact_rep_gap,
                "contact_pinch_gap": contact_pinch_rep_gap,
                "open_contact_gap_ratio": open_contact_rep_ratio,
                "contact_pinch_gap_ratio": contact_pinch_rep_ratio,
                "open_contact_distribution_gap": (
                    open_summary["p10"] - contact_summary["p90"]
                ),
                "contact_pinch_distribution_gap": (
                    contact_summary["p10"] - pinch_summary["p90"]
                ),
                "failed_pairs": tuple(dict.fromkeys(failed_pairs)),
                "passed": not rep_reasons,
                "reasons": tuple(dict.fromkeys(rep_reasons)),
                "warnings": tuple(dict.fromkeys(rep_warnings)),
            }
        )

    reasons: list[str] = []
    warnings: list[str] = list(paired_reference_warnings)
    if (
        normalized_contact is not None
        and config.contact_position_min is not None
        and normalized_contact < config.contact_position_min
    ):
        reasons.append("contact_position_too_close_to_open")
    if (
        normalized_contact is not None
        and config.contact_position_max is not None
        and normalized_contact > config.contact_position_max
    ):
        reasons.append("contact_position_too_close_to_pinch")

    contact_range = max(contact_positions) - min(contact_positions) if contact_positions else None
    if contact_range is None:
        reasons.append("contact_rep_position_unavailable")
    elif contact_range > config.max_contact_rep_position_range:
        warnings.append("contact_rep_position_inconsistent")

    rep_ratio_fields: dict[str, float | None] = {}
    for state in ("open", "contact", "pinch"):
        rep_range = state_summaries[state]["rep_median_range"]
        ratio = _safe_ratio(rep_range, open_pinch_range)
        rep_ratio_fields[f"{state}_rep_median_range_ratio"] = ratio
        if ratio is None or ratio > config.max_state_rep_median_range_ratio:
            target = warnings if state == "contact" else reasons
            target.append(f"{state}_rep_median_inconsistent")

    for row in repetition_rows:
        mad_ratio = _safe_ratio(row["mad"], open_pinch_range)
        range_ratio = _safe_ratio(row["range"], open_pinch_range)
        if config.stability_mad_max is not None and row["mad"] > config.stability_mad_max:
            reasons.append(f"{row['phase']}_within_hold_mad_too_large")
        if config.stability_range_max is not None and row["range"] > config.stability_range_max:
            reasons.append(f"{row['phase']}_within_hold_range_too_large")
        row["mad_ratio_to_open_pinch_range"] = mad_ratio
        row["range_ratio_to_open_pinch_range"] = range_ratio

    return {
        "finger_repetitions": repetition_rows,
        "finger_state_summaries": state_summaries,
        "open_contact_gap": open_contact_gap,
        "contact_pinch_gap": contact_pinch_gap,
        "open_contact_gap_ratio": open_contact_gap_ratio,
        "contact_pinch_gap_ratio": contact_pinch_gap_ratio,
        "normalized_contact_position": normalized_contact,
        "contact_rep_normalized_positions": tuple(contact_positions),
        "contact_rep_position_range": contact_range,
        "contact_rep_position_mad": _mad(contact_positions) if contact_positions else None,
        "paired_repetition_qc": tuple(paired_rows),
        "paired_reference_qc_passed": not paired_reference_reasons,
        "paired_reference_qc_reasons": tuple(dict.fromkeys(paired_reference_reasons)),
        "full_calibration_qc_reasons": tuple(dict.fromkeys(reasons)),
        "calibration_qc_warnings": tuple(dict.fromkeys(warnings)),
        **rep_ratio_fields,
    }


def _flatten(values: Iterable[Iterable[float]]) -> list[float]:
    return [item for group in values for item in group]


def _mad(values: Iterable[float]) -> float | None:
    items = [float(item) for item in values if math.isfinite(float(item))]
    if not items:
        return None
    center = median(items)
    return median([abs(item - center) for item in items])


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    denominator = float(denominator)
    if not math.isfinite(denominator) or abs(denominator) <= 1e-12:
        return None
    value = float(numerator) / denominator
    return value if math.isfinite(value) else None


def _state_duration_s(state: str, config: PinchCalibrationConfig) -> float:
    if state == "open":
        return config.open_hand_duration_s
    if state == "contact":
        return config.contact_hand_duration_s
    if state == "pinch":
        return config.pinch_hand_duration_s
    return config.stable_recording_duration_s


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
