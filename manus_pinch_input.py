"""MANUS-only pinch input derived from combined JSON frames."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from vendor_exp2_abc.device_frame_models import DeviceAdapterConfig
from vendor_exp2_abc.pinch_feature_extractor import PinchFeatureExtractor
from vendor_exp2_abc.raw_manus_vive_parser import parse_raw_manus_vive_frame


@dataclass(frozen=True)
class ManusPinchInputConfig:
    """Configurable MANUS node ids for pinch distance extraction."""

    thumb_node_id: int = 4
    target_finger_node_id: int = 14
    skeleton_index: int = 0
    tracker_index: int = 0
    require_tracker: bool = False
    timestamp_scale: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "thumb_node_id", int(self.thumb_node_id))
        object.__setattr__(self, "target_finger_node_id", int(self.target_finger_node_id))
        object.__setattr__(self, "skeleton_index", int(self.skeleton_index))
        object.__setattr__(self, "tracker_index", int(self.tracker_index))
        if not isinstance(self.require_tracker, bool):
            raise ValueError("require_tracker must be true or false.")
        scale = float(self.timestamp_scale)
        if not math.isfinite(scale):
            raise ValueError("timestamp_scale must be finite.")
        object.__setattr__(self, "timestamp_scale", scale)


@dataclass(frozen=True)
class PinchInputSample:
    """One parsed MANUS pinch sample."""

    session_id: str
    frame_index: int | None
    wall_time_iso: str
    monotonic_ms: float
    source_timestamp: Any
    source_frame_id: int | None
    hand_valid: bool
    pinch_valid: bool
    pinch_distance: float | None
    thumb_node_id: int
    target_finger_node_id: int
    thumb_position: list[float] | None
    target_finger_position: list[float] | None
    tracker_present: bool
    note: str = ""

    def to_csv_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["thumb_position"] = _json_or_empty(self.thumb_position)
        row["target_finger_position"] = _json_or_empty(self.target_finger_position)
        return row


class ManusOnlyPinchInput:
    """Extract pinch distance from MANUS hand nodes without requiring tracker data."""

    def __init__(self, config: ManusPinchInputConfig | None = None) -> None:
        self.config = config or ManusPinchInputConfig()
        self._adapter_config = DeviceAdapterConfig(
            skeleton_index=self.config.skeleton_index,
            tracker_index=self.config.tracker_index,
            thumb_tip_node_id=self.config.thumb_node_id,
            index_tip_node_id=self.config.target_finger_node_id,
            timestamp_scale=self.config.timestamp_scale,
        )
        self._extractor = PinchFeatureExtractor(
            thumb_tip_node_id=self.config.thumb_node_id,
            index_tip_node_id=self.config.target_finger_node_id,
        )

    def parse_sample(
        self,
        frame: Any,
        *,
        session_id: str = "",
        frame_index: int | None = None,
        wall_time: float | None = None,
        monotonic_ms: float | None = None,
    ) -> PinchInputSample:
        """Parse a combined JSON frame or LiveRawFrame-like object."""

        raw, inferred_frame_index, inferred_wall_time, inferred_monotonic_ms = _unwrap_frame(frame)
        if frame_index is None:
            frame_index = inferred_frame_index
        if wall_time is None:
            wall_time = inferred_wall_time if inferred_wall_time is not None else time.time()
        if monotonic_ms is None:
            monotonic_ms = (
                inferred_monotonic_ms
                if inferred_monotonic_ms is not None
                else time.monotonic() * 1000.0
            )

        device_frame = parse_raw_manus_vive_frame(raw, self._adapter_config)
        feature = self._extractor.extract(device_frame.hand)
        tracker_present = device_frame.tracker is not None
        pinch_valid = bool(feature.valid)
        note_parts: list[str] = []
        if device_frame.hand is None or not device_frame.hand.valid:
            note_parts.append("hand_missing_or_invalid")
        if not feature.valid:
            note_parts.append("missing_pinch_nodes")
        if self.config.require_tracker and not tracker_present:
            pinch_valid = False
            note_parts.append("tracker_required_missing")

        return PinchInputSample(
            session_id=str(session_id),
            frame_index=frame_index,
            wall_time_iso=datetime.fromtimestamp(float(wall_time), timezone.utc).isoformat(),
            monotonic_ms=float(monotonic_ms),
            source_timestamp=device_frame.source_timestamp,
            source_frame_id=device_frame.source_frame_id,
            hand_valid=bool(device_frame.hand is not None and device_frame.hand.valid),
            pinch_valid=pinch_valid,
            pinch_distance=(
                float(feature.pinch_distance)
                if feature.pinch_distance is not None and pinch_valid
                else None
            ),
            thumb_node_id=self.config.thumb_node_id,
            target_finger_node_id=self.config.target_finger_node_id,
            thumb_position=_vector_to_list(feature.thumb_tip_local),
            target_finger_position=_vector_to_list(feature.index_tip_local),
            tracker_present=tracker_present,
            note=";".join(note_parts),
        )


def parse_manus_pinch_sample(
    frame: Any,
    *,
    config: ManusPinchInputConfig | None = None,
    session_id: str = "",
    frame_index: int | None = None,
    wall_time: float | None = None,
    monotonic_ms: float | None = None,
) -> PinchInputSample:
    """Convenience wrapper for one-off parsing."""

    return ManusOnlyPinchInput(config).parse_sample(
        frame,
        session_id=session_id,
        frame_index=frame_index,
        wall_time=wall_time,
        monotonic_ms=monotonic_ms,
    )


def _unwrap_frame(frame: Any) -> tuple[dict[str, Any], int | None, float | None, float | None]:
    raw = getattr(frame, "raw_frame", frame)
    if not isinstance(raw, dict):
        raise ValueError("combined JSON frame must be a dict.")
    frame_index = _optional_int(getattr(frame, "frame_index", None))
    receive_wall_time = _optional_float(getattr(frame, "receive_wall_time", None))
    receive_monotonic = _optional_float(getattr(frame, "receive_time_monotonic", None))
    monotonic_ms = receive_monotonic * 1000.0 if receive_monotonic is not None else None
    if frame_index is None:
        frame_index = _optional_int(raw.get("frame"))
    return raw, frame_index, receive_wall_time, monotonic_ms


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _vector_to_list(value: Any) -> list[float] | None:
    if value is None:
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    return result if len(result) == 3 and all(math.isfinite(item) for item in result) else None


def _json_or_empty(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, separators=(",", ":"))

