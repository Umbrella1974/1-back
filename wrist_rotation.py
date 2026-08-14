"""MANUS wrist0 relative rotation calibration and classification."""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


QUATERNION_ORDERS = {"wxyz", "xyzw"}
WRIST_CLASSES = {"neutral", "left", "right", "unknown"}
WRIST_UP_DOWN_CLASSES = {"neutral", "up", "down", "unknown"}


@dataclass(frozen=True)
class WristRotationConfig:
    enabled: bool = False
    node_id: int = 0
    quaternion_order: str = "wxyz"
    calibration_duration_s: float = 3.0
    min_valid_frames: int = 30
    feature_method: str = "calibrated_axis_projection"
    neutral_label: str = "neutral"
    left_label: str = "left"
    right_label: str = "right"
    up_label: str = "up"
    down_label: str = "down"
    enable_up_down: bool = False
    classification_margin: float = 0.15
    save_timeseries: bool = True
    required: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("wrist_rotation.enabled must be true or false.")
        object.__setattr__(self, "node_id", int(self.node_id))
        order = str(self.quaternion_order).strip().lower()
        if order not in QUATERNION_ORDERS:
            raise ValueError("wrist_rotation.quaternion_order must be wxyz or xyzw.")
        object.__setattr__(self, "quaternion_order", order)
        duration = float(self.calibration_duration_s)
        if not math.isfinite(duration) or duration <= 0.0:
            raise ValueError("wrist_rotation.calibration_duration_s must be positive.")
        object.__setattr__(self, "calibration_duration_s", duration)
        object.__setattr__(self, "min_valid_frames", max(1, int(self.min_valid_frames)))
        if self.feature_method != "calibrated_axis_projection":
            raise ValueError("wrist_rotation.feature_method must be calibrated_axis_projection.")
        margin = float(self.classification_margin)
        if not math.isfinite(margin) or margin < 0.0:
            raise ValueError("wrist_rotation.classification_margin must be non-negative.")
        object.__setattr__(self, "classification_margin", margin)
        if not isinstance(self.enable_up_down, bool):
            raise ValueError("wrist_rotation.enable_up_down must be true or false.")
        if not isinstance(self.save_timeseries, bool):
            raise ValueError("wrist_rotation.save_timeseries must be true or false.")
        if not isinstance(self.required, bool):
            raise ValueError("wrist_rotation.required must be true or false.")


@dataclass(frozen=True)
class WristRotationCalibrationResult:
    node_id: int
    quaternion_order: str
    neutral_mean_q: tuple[float, float, float, float] | None = None
    left_mean_q: tuple[float, float, float, float] | None = None
    right_mean_q: tuple[float, float, float, float] | None = None
    up_mean_q: tuple[float, float, float, float] | None = None
    down_mean_q: tuple[float, float, float, float] | None = None
    left_relative_q: tuple[float, float, float, float] | None = None
    right_relative_q: tuple[float, float, float, float] | None = None
    up_relative_q: tuple[float, float, float, float] | None = None
    down_relative_q: tuple[float, float, float, float] | None = None
    rotation_axis_vector: tuple[float, float, float] | None = None
    up_down_axis_vector: tuple[float, float, float] | None = None
    left_score_mean: float | None = None
    right_score_mean: float | None = None
    up_score_mean: float | None = None
    down_score_mean: float | None = None
    threshold: float | None = None
    up_down_threshold: float | None = None
    calibration_passed: bool = False
    up_down_calibration_passed: bool = False
    failure_reason: str = ""
    up_down_failure_reason: str = ""
    valid_frame_counts: dict[str, int] = field(default_factory=dict)
    classification_margin: float = 0.15
    neutral_lr_score_summary: dict[str, float | int | None] = field(default_factory=dict)
    left_lr_score_summary: dict[str, float | int | None] = field(default_factory=dict)
    right_lr_score_summary: dict[str, float | int | None] = field(default_factory=dict)
    lr_old_neutral_region: dict[str, float | bool | None] = field(default_factory=dict)
    lr_neutral_centered_region: dict[str, float | bool | None] = field(default_factory=dict)
    neutral_up_down_score_summary: dict[str, float | int | None] = field(default_factory=dict)
    up_score_summary: dict[str, float | int | None] = field(default_factory=dict)
    down_score_summary: dict[str, float | int | None] = field(default_factory=dict)
    up_down_old_neutral_region: dict[str, float | bool | None] = field(default_factory=dict)
    up_down_neutral_centered_region: dict[str, float | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WristRotationSample:
    session_id: str = ""
    wall_time_iso: str = ""
    monotonic_ms: float | None = None
    source_frame_id: int | None = None
    node_id: int = 0
    q_w: float | None = None
    q_x: float | None = None
    q_y: float | None = None
    q_z: float | None = None
    wrist_rotation_valid: bool = False
    wrist_rotation_score: float | None = None
    wrist_rotation_class: str = "unknown"
    distance_to_left: float | None = None
    distance_to_right: float | None = None
    wrist_up_down_valid: bool = False
    wrist_up_down_score: float | None = None
    wrist_up_down_class: str = "unknown"
    distance_to_up: float | None = None
    distance_to_down: float | None = None
    note: str = ""

    def to_csv_row(self) -> dict[str, Any]:
        return asdict(self)


def wrist_rotation_config_from_dict(payload: dict[str, Any] | None) -> WristRotationConfig:
    value = payload or {}
    if not isinstance(value, dict):
        raise ValueError("wrist_rotation section must be an object.")
    return WristRotationConfig(
        enabled=bool(value.get("enabled", False)),
        node_id=value.get("node_id", 0),
        quaternion_order=str(value.get("quaternion_order", "wxyz")),
        calibration_duration_s=value.get("calibration_duration_s", 3.0),
        min_valid_frames=value.get("min_valid_frames", 30),
        feature_method=str(value.get("feature_method", "calibrated_axis_projection")),
        neutral_label=str(value.get("neutral_label", "neutral")),
        left_label=str(value.get("left_label", "left")),
        right_label=str(value.get("right_label", "right")),
        up_label=str(value.get("up_label", "up")),
        down_label=str(value.get("down_label", "down")),
        enable_up_down=bool(value.get("enable_up_down", False)),
        classification_margin=value.get("classification_margin", 0.15),
        save_timeseries=bool(value.get("save_timeseries", True)),
        required=bool(value.get("required", False)),
    )


def extract_wrist_quaternion(
    device_frame: Any,
    node_id: int = 0,
    *,
    quaternion_order: str = "wxyz",
) -> tuple[float, float, float, float] | None:
    """Extract MANUS skeleton node rotation as internal wxyz quaternion."""

    raw = getattr(device_frame, "raw_frame", device_frame)
    if hasattr(raw, "hand"):
        hand = getattr(raw, "hand", None)
        nodes = getattr(hand, "nodes", {}) if hand is not None else {}
        node = nodes.get(int(node_id)) if isinstance(nodes, dict) else None
        rotation = getattr(node, "rotation", None) if node is not None else None
        return _coerce_quaternion(rotation, quaternion_order=quaternion_order)
    if not isinstance(raw, dict):
        return None
    skeletons = raw.get("skeletons")
    if not isinstance(skeletons, list):
        return None
    for skeleton in skeletons:
        if not isinstance(skeleton, dict):
            continue
        nodes = skeleton.get("nodes")
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            if not isinstance(node, dict):
                continue
            current_id = node.get("id", node.get("node_id"))
            try:
                if int(current_id) != int(node_id):
                    continue
            except (TypeError, ValueError):
                continue
            return _coerce_quaternion(node.get("rotation"), quaternion_order=quaternion_order)
    return None


def normalize_quaternion(q: Iterable[float]) -> tuple[float, float, float, float]:
    values = tuple(float(item) for item in q)
    if len(values) != 4 or not all(math.isfinite(item) for item in values):
        raise ValueError("quaternion must contain four finite values.")
    norm = math.sqrt(sum(item * item for item in values))
    if norm <= 0.0:
        raise ValueError("quaternion norm must be positive.")
    return tuple(item / norm for item in values)  # type: ignore[return-value]


def invert_quaternion(q: Iterable[float]) -> tuple[float, float, float, float]:
    w, x, y, z = normalize_quaternion(q)
    return (w, -x, -y, -z)


def multiply_quaternion(
    q1: Iterable[float],
    q2: Iterable[float],
) -> tuple[float, float, float, float]:
    w1, x1, y1, z1 = normalize_quaternion(q1)
    w2, x2, y2, z2 = normalize_quaternion(q2)
    return normalize_quaternion(
        (
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        )
    )


def relative_quaternion(
    q_current: Iterable[float],
    q_neutral: Iterable[float],
) -> tuple[float, float, float, float]:
    return multiply_quaternion(q_current, invert_quaternion(q_neutral))


def quaternion_to_vector_part(q: Iterable[float]) -> tuple[float, float, float]:
    _, x, y, z = normalize_quaternion(q)
    return (x, y, z)


def quaternion_angle(q: Iterable[float]) -> float:
    w, _, _, _ = normalize_quaternion(q)
    w = max(-1.0, min(1.0, w))
    return 2.0 * math.acos(abs(w))


def calibrate_wrist_rotation(
    neutral_quaternions: Iterable[Iterable[float]],
    left_quaternions: Iterable[Iterable[float]],
    right_quaternions: Iterable[Iterable[float]],
    *,
    up_quaternions: Iterable[Iterable[float]] | None = None,
    down_quaternions: Iterable[Iterable[float]] | None = None,
    config: WristRotationConfig | None = None,
) -> WristRotationCalibrationResult:
    cfg = config or WristRotationConfig()
    neutral_values = [normalize_quaternion(q) for q in neutral_quaternions]
    left_values = [normalize_quaternion(q) for q in left_quaternions]
    right_values = [normalize_quaternion(q) for q in right_quaternions]
    up_values = [normalize_quaternion(q) for q in (up_quaternions or ())]
    down_values = [normalize_quaternion(q) for q in (down_quaternions or ())]
    counts = {
        cfg.neutral_label: len(neutral_values),
        cfg.left_label: len(left_values),
        cfg.right_label: len(right_values),
    }
    if cfg.enable_up_down:
        counts[cfg.up_label] = len(up_values)
        counts[cfg.down_label] = len(down_values)
    if any(count < cfg.min_valid_frames for count in counts.values()):
        return WristRotationCalibrationResult(
            node_id=cfg.node_id,
            quaternion_order=cfg.quaternion_order,
            calibration_passed=False,
            up_down_calibration_passed=False,
            failure_reason="not_enough_valid_wrist_rotation_frames",
            up_down_failure_reason=(
                "not_enough_valid_wrist_rotation_frames" if cfg.enable_up_down else ""
            ),
            valid_frame_counts=counts,
            classification_margin=cfg.classification_margin,
        )

    neutral_mean = mean_quaternion(neutral_values)
    left_mean = mean_quaternion(left_values, reference=neutral_mean)
    right_mean = mean_quaternion(right_values, reference=neutral_mean)
    left_relative = relative_quaternion(left_mean, neutral_mean)
    right_relative = relative_quaternion(right_mean, neutral_mean)
    axis_raw = _vector_sub(
        quaternion_to_vector_part(left_relative),
        quaternion_to_vector_part(right_relative),
    )
    try:
        axis = _normalize_vector(axis_raw)
    except ValueError:
        return WristRotationCalibrationResult(
            node_id=cfg.node_id,
            quaternion_order=cfg.quaternion_order,
            neutral_mean_q=neutral_mean,
            left_mean_q=left_mean,
            right_mean_q=right_mean,
            left_relative_q=left_relative,
            right_relative_q=right_relative,
            calibration_passed=False,
            failure_reason="left_right_wrist_rotation_too_similar",
            valid_frame_counts=counts,
            classification_margin=cfg.classification_margin,
        )

    left_score = _score(left_mean, neutral_mean, axis)
    right_score = _score(right_mean, neutral_mean, axis)
    threshold = (left_score + right_score) / 2.0
    neutral_lr_scores = [_score(q, neutral_mean, axis) for q in neutral_values]
    left_lr_scores = [_score(q, neutral_mean, axis) for q in left_values]
    right_lr_scores = [_score(q, neutral_mean, axis) for q in right_values]
    up_down_fields: dict[str, Any] = {}
    if cfg.enable_up_down:
        up_down_fields = _calibrate_up_down_fields(
            neutral_mean,
            neutral_values,
            up_values,
            down_values,
            config=cfg,
        )
    return WristRotationCalibrationResult(
        node_id=cfg.node_id,
        quaternion_order=cfg.quaternion_order,
        neutral_mean_q=neutral_mean,
        left_mean_q=left_mean,
        right_mean_q=right_mean,
        left_relative_q=left_relative,
        right_relative_q=right_relative,
        rotation_axis_vector=axis,
        left_score_mean=left_score,
        right_score_mean=right_score,
        threshold=threshold,
        calibration_passed=True,
        valid_frame_counts=counts,
        classification_margin=cfg.classification_margin,
        neutral_lr_score_summary=_score_summary(neutral_lr_scores),
        left_lr_score_summary=_score_summary(left_lr_scores),
        right_lr_score_summary=_score_summary(right_lr_scores),
        lr_old_neutral_region=_old_neutral_region(
            threshold=threshold,
            first_score=left_score,
            second_score=right_score,
            margin_ratio=cfg.classification_margin,
        ),
        lr_neutral_centered_region=_neutral_centered_region(
            positive_score=left_score,
            negative_score=right_score,
        ),
        **up_down_fields,
    )


def _calibrate_up_down_fields(
    neutral_mean: tuple[float, float, float, float],
    neutral_values: list[tuple[float, float, float, float]],
    up_values: list[tuple[float, float, float, float]],
    down_values: list[tuple[float, float, float, float]],
    *,
    config: WristRotationConfig,
) -> dict[str, Any]:
    up_mean = mean_quaternion(up_values, reference=neutral_mean)
    down_mean = mean_quaternion(down_values, reference=neutral_mean)
    up_relative = relative_quaternion(up_mean, neutral_mean)
    down_relative = relative_quaternion(down_mean, neutral_mean)
    axis_raw = _vector_sub(
        quaternion_to_vector_part(up_relative),
        quaternion_to_vector_part(down_relative),
    )
    try:
        axis = _normalize_vector(axis_raw)
    except ValueError:
        return {
            "up_mean_q": up_mean,
            "down_mean_q": down_mean,
            "up_relative_q": up_relative,
            "down_relative_q": down_relative,
            "up_down_calibration_passed": False,
            "up_down_failure_reason": "up_down_wrist_rotation_too_similar",
        }
    up_score = _score(up_mean, neutral_mean, axis)
    down_score = _score(down_mean, neutral_mean, axis)
    threshold = (up_score + down_score) / 2.0
    neutral_scores = [_score(q, neutral_mean, axis) for q in neutral_values]
    up_scores = [_score(q, neutral_mean, axis) for q in up_values]
    down_scores = [_score(q, neutral_mean, axis) for q in down_values]
    return {
        "up_mean_q": up_mean,
        "down_mean_q": down_mean,
        "up_relative_q": up_relative,
        "down_relative_q": down_relative,
        "up_down_axis_vector": axis,
        "up_score_mean": up_score,
        "down_score_mean": down_score,
        "up_down_threshold": threshold,
        "up_down_calibration_passed": True,
        "up_down_failure_reason": "",
        "neutral_up_down_score_summary": _score_summary(neutral_scores),
        "up_score_summary": _score_summary(up_scores),
        "down_score_summary": _score_summary(down_scores),
        "up_down_old_neutral_region": _old_neutral_region(
            threshold=threshold,
            first_score=up_score,
            second_score=down_score,
            margin_ratio=config.classification_margin,
        ),
        "up_down_neutral_centered_region": _neutral_centered_region(
            positive_score=up_score,
            negative_score=down_score,
        ),
    }


def classify_wrist_rotation(
    current_q: Iterable[float] | None,
    calibration_result: WristRotationCalibrationResult,
    *,
    monotonic_ms: float | None = None,
    wall_time: float | None = None,
    source_frame_id: int | None = None,
    session_id: str = "",
) -> WristRotationSample:
    wall_time_iso = datetime.fromtimestamp(
        float(time.time() if wall_time is None else wall_time),
        timezone.utc,
    ).isoformat()
    if current_q is None:
        return WristRotationSample(
            session_id=session_id,
            wall_time_iso=wall_time_iso,
            monotonic_ms=monotonic_ms,
            source_frame_id=source_frame_id,
            node_id=calibration_result.node_id,
            note="missing_wrist_rotation",
        )
    try:
        q = normalize_quaternion(current_q)
    except ValueError as exc:
        return WristRotationSample(
            session_id=session_id,
            wall_time_iso=wall_time_iso,
            monotonic_ms=monotonic_ms,
            source_frame_id=source_frame_id,
            node_id=calibration_result.node_id,
            note=str(exc),
        )
    if not calibration_result.calibration_passed:
        return _sample_from_score(
            q,
            calibration_result,
            None,
            "unknown",
            monotonic_ms=monotonic_ms,
            wall_time_iso=wall_time_iso,
            source_frame_id=source_frame_id,
            session_id=session_id,
            note="wrist_rotation_calibration_failed",
        )
    if (
        calibration_result.neutral_mean_q is None
        or calibration_result.rotation_axis_vector is None
        or calibration_result.left_score_mean is None
        or calibration_result.right_score_mean is None
        or calibration_result.threshold is None
    ):
        return _sample_from_score(
            q,
            calibration_result,
            None,
            "unknown",
            monotonic_ms=monotonic_ms,
            wall_time_iso=wall_time_iso,
            source_frame_id=source_frame_id,
            session_id=session_id,
            note="wrist_rotation_calibration_incomplete",
        )

    score = _score(q, calibration_result.neutral_mean_q, calibration_result.rotation_axis_vector)
    left_score = calibration_result.left_score_mean
    right_score = calibration_result.right_score_mean
    threshold = calibration_result.threshold
    margin = abs(left_score - right_score) * calibration_result.classification_margin
    if abs(score - threshold) <= margin:
        label = "neutral"
    elif abs(score - left_score) < abs(score - right_score):
        label = "left"
    else:
        label = "right"
    return _sample_from_score(
        q,
        calibration_result,
        score,
        label,
        up_down_result=_classify_up_down(q, calibration_result),
        monotonic_ms=monotonic_ms,
        wall_time_iso=wall_time_iso,
        source_frame_id=source_frame_id,
        session_id=session_id,
    )


def _classify_up_down(
    q: tuple[float, float, float, float],
    calibration_result: WristRotationCalibrationResult,
) -> tuple[float | None, str]:
    if not calibration_result.up_down_calibration_passed:
        return None, "unknown"
    if (
        calibration_result.neutral_mean_q is None
        or calibration_result.up_down_axis_vector is None
        or calibration_result.up_score_mean is None
        or calibration_result.down_score_mean is None
        or calibration_result.up_down_threshold is None
    ):
        return None, "unknown"
    score = _score(q, calibration_result.neutral_mean_q, calibration_result.up_down_axis_vector)
    up_score = calibration_result.up_score_mean
    down_score = calibration_result.down_score_mean
    threshold = calibration_result.up_down_threshold
    margin = abs(up_score - down_score) * calibration_result.classification_margin
    if abs(score - threshold) <= margin:
        return score, "neutral"
    if abs(score - up_score) < abs(score - down_score):
        return score, "up"
    return score, "down"


def classify_wrist_rotation_frame(
    frame: Any,
    calibration_result: WristRotationCalibrationResult,
    *,
    quaternion_order: str = "wxyz",
    session_id: str = "",
) -> WristRotationSample:
    q = extract_wrist_quaternion(
        frame,
        node_id=calibration_result.node_id,
        quaternion_order=quaternion_order,
    )
    raw = getattr(frame, "raw_frame", frame)
    source_frame_id = _optional_int(raw.get("frame")) if isinstance(raw, dict) else None
    wall_time = getattr(frame, "receive_wall_time", None)
    monotonic = getattr(frame, "receive_time_monotonic", None)
    monotonic_ms = float(monotonic) * 1000.0 if monotonic is not None else None
    return classify_wrist_rotation(
        q,
        calibration_result,
        monotonic_ms=monotonic_ms,
        wall_time=wall_time,
        source_frame_id=source_frame_id,
        session_id=session_id,
    )


def mean_quaternion(
    quaternions: Iterable[Iterable[float]],
    *,
    reference: Iterable[float] | None = None,
) -> tuple[float, float, float, float]:
    values = [normalize_quaternion(q) for q in quaternions]
    if not values:
        raise ValueError("cannot average empty quaternion list.")
    ref = normalize_quaternion(reference or values[0])
    aligned: list[tuple[float, float, float, float]] = []
    for q in values:
        aligned.append(tuple(-item for item in q) if _dot4(q, ref) < 0.0 else q)
    return normalize_quaternion(tuple(sum(q[i] for q in aligned) for i in range(4)))


def _coerce_quaternion(
    value: Any,
    *,
    quaternion_order: str,
) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    try:
        raw = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if len(raw) != 4 or not all(math.isfinite(item) for item in raw):
        return None
    if quaternion_order == "xyzw":
        raw = (raw[3], raw[0], raw[1], raw[2])
    elif quaternion_order != "wxyz":
        raise ValueError("quaternion_order must be wxyz or xyzw.")
    try:
        return normalize_quaternion(raw)
    except ValueError:
        return None


def _score(
    current_q: Iterable[float],
    neutral_q: Iterable[float],
    axis: Iterable[float],
) -> float:
    return _dot3(quaternion_to_vector_part(relative_quaternion(current_q, neutral_q)), axis)


def _sample_from_score(
    q: tuple[float, float, float, float],
    calibration_result: WristRotationCalibrationResult,
    score: float | None,
    label: str,
    *,
    up_down_result: tuple[float | None, str] | None = None,
    monotonic_ms: float | None,
    wall_time_iso: str,
    source_frame_id: int | None,
    session_id: str,
    note: str = "",
) -> WristRotationSample:
    left = calibration_result.left_score_mean
    right = calibration_result.right_score_mean
    up_down_score, up_down_label = up_down_result or (None, "unknown")
    up = calibration_result.up_score_mean
    down = calibration_result.down_score_mean
    return WristRotationSample(
        session_id=session_id,
        wall_time_iso=wall_time_iso,
        monotonic_ms=monotonic_ms,
        source_frame_id=source_frame_id,
        node_id=calibration_result.node_id,
        q_w=q[0],
        q_x=q[1],
        q_y=q[2],
        q_z=q[3],
        wrist_rotation_valid=score is not None and label in WRIST_CLASSES - {"unknown"},
        wrist_rotation_score=score,
        wrist_rotation_class=label,
        distance_to_left=abs(score - left) if score is not None and left is not None else None,
        distance_to_right=abs(score - right) if score is not None and right is not None else None,
        wrist_up_down_valid=(
            up_down_score is not None
            and up_down_label in WRIST_UP_DOWN_CLASSES - {"unknown"}
        ),
        wrist_up_down_score=up_down_score,
        wrist_up_down_class=up_down_label,
        distance_to_up=(
            abs(up_down_score - up)
            if up_down_score is not None and up is not None
            else None
        ),
        distance_to_down=(
            abs(up_down_score - down)
            if up_down_score is not None and down is not None
            else None
        ),
        note=note,
    )


def _normalize_vector(value: Iterable[float]) -> tuple[float, float, float]:
    values = tuple(float(item) for item in value)
    if len(values) != 3 or not all(math.isfinite(item) for item in values):
        raise ValueError("vector must contain three finite values.")
    norm = math.sqrt(sum(item * item for item in values))
    if norm <= 0.0:
        raise ValueError("vector norm must be positive.")
    return tuple(item / norm for item in values)  # type: ignore[return-value]


def _vector_sub(a: Iterable[float], b: Iterable[float]) -> tuple[float, float, float]:
    av = tuple(float(item) for item in a)
    bv = tuple(float(item) for item in b)
    return (av[0] - bv[0], av[1] - bv[1], av[2] - bv[2])


def _dot3(a: Iterable[float], b: Iterable[float]) -> float:
    av = tuple(float(item) for item in a)
    bv = tuple(float(item) for item in b)
    return av[0] * bv[0] + av[1] * bv[1] + av[2] * bv[2]


def _dot4(a: Iterable[float], b: Iterable[float]) -> float:
    av = tuple(float(item) for item in a)
    bv = tuple(float(item) for item in b)
    return av[0] * bv[0] + av[1] * bv[1] + av[2] * bv[2] + av[3] * bv[3]


def _score_summary(values: Iterable[float]) -> dict[str, float | int | None]:
    scores = sorted(float(item) for item in values if math.isfinite(float(item)))
    if not scores:
        return {
            "count": 0,
            "mean": None,
            "sd": None,
            "p05": None,
            "p50": None,
            "p95": None,
            "min": None,
            "max": None,
        }
    mean_value = sum(scores) / len(scores)
    variance = (
        sum((item - mean_value) ** 2 for item in scores) / (len(scores) - 1)
        if len(scores) > 1
        else 0.0
    )
    return {
        "count": len(scores),
        "mean": mean_value,
        "sd": math.sqrt(variance),
        "p05": _percentile(scores, 5.0),
        "p50": _percentile(scores, 50.0),
        "p95": _percentile(scores, 95.0),
        "min": scores[0],
        "max": scores[-1],
    }


def _old_neutral_region(
    *,
    threshold: float,
    first_score: float,
    second_score: float,
    margin_ratio: float,
) -> dict[str, float | bool | None]:
    margin = abs(float(first_score) - float(second_score)) * float(margin_ratio)
    lower = float(threshold) - margin
    upper = float(threshold) + margin
    return {
        "lower": lower,
        "upper": upper,
        "margin": margin,
        "zero_in_region": lower <= 0.0 <= upper,
    }


def _neutral_centered_region(
    *,
    positive_score: float,
    negative_score: float,
) -> dict[str, float | bool | None]:
    positive = float(positive_score)
    negative = float(negative_score)
    sanity_passed = positive > 0.0 > negative
    lower = negative / 2.0 if negative < 0.0 else None
    upper = positive / 2.0 if positive > 0.0 else None
    return {
        "lower": lower,
        "upper": upper,
        "zero_in_region": lower is not None and upper is not None and lower <= 0.0 <= upper,
        "sanity_passed": sanity_passed,
    }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile of empty values.")
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * float(pct) / 100.0
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
