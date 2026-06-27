"""Session file logging for pinch+haptic dry-runs."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PINCH_TIMESERIES_FIELDS = [
    "session_id",
    "frame_index",
    "wall_time_iso",
    "monotonic_ms",
    "source_timestamp",
    "source_frame_id",
    "hand_valid",
    "pinch_valid",
    "pinch_distance",
    "min_distance",
    "max_distance",
    "threshold_a",
    "zone",
    "thumb_node_id",
    "target_finger_node_id",
    "tracker_present",
    "note",
]


NBACK_EVENT_FIELDS = [
    "session_id",
    "wall_time_iso",
    "stimulus_index",
    "stimulus",
    "is_target",
    "stimulus_onset_monotonic_ms",
    "response_key",
    "response_monotonic_ms",
    "correct",
    "rt_ms",
]


WRIST_ROTATION_TIMESERIES_FIELDS = [
    "session_id",
    "wall_time_iso",
    "monotonic_ms",
    "source_frame_id",
    "node_id",
    "q_w",
    "q_x",
    "q_y",
    "q_z",
    "wrist_rotation_valid",
    "wrist_rotation_score",
    "wrist_rotation_class",
    "distance_to_left",
    "distance_to_right",
    "note",
]


@dataclass(frozen=True)
class DualTaskOutputPaths:
    raw_frames_jsonl: Path
    pinch_timeseries_csv: Path
    haptic_events_csv: Path
    nback_events_csv: Path
    wrist_rotation_calibration_json: Path
    wrist_rotation_timeseries_csv: Path
    calibration_json: Path
    summary_json: Path

    def to_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


class DualTaskLogger:
    """Write dry-run session outputs into a single session directory."""

    def __init__(
        self,
        *,
        session_id: str,
        output_root: str | Path = "outputs",
        session_dir: str | Path | None = None,
    ) -> None:
        self.session_id = str(session_id)
        root = Path(output_root)
        self.session_dir = Path(session_dir) if session_dir is not None else root / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.paths = DualTaskOutputPaths(
            raw_frames_jsonl=self.session_dir / "raw_frames.jsonl",
            pinch_timeseries_csv=self.session_dir / "pinch_timeseries.csv",
            haptic_events_csv=self.session_dir / "haptic_events.csv",
            nback_events_csv=self.session_dir / "nback_events.csv",
            wrist_rotation_calibration_json=self.session_dir / "wrist_rotation_calibration.json",
            wrist_rotation_timeseries_csv=self.session_dir / "wrist_rotation_timeseries.csv",
            calibration_json=self.session_dir / "calibration.json",
            summary_json=self.session_dir / "summary.json",
        )
        self.total_raw_frames = 0
        self.total_pinch_samples = 0
        self.total_valid_pinch_samples = 0
        self.total_nback_trials = 0
        self.total_nback_responses = 0
        self.total_wrist_rotation_valid_samples = 0
        self.total_wrist_rotation_invalid_samples = 0
        self._pinch_header_written = False
        self._nback_header_written = False
        self._wrist_rotation_header_written = False

    def write_raw_frame(self, raw_frame: Any) -> None:
        """Append one raw combined JSON frame."""

        with self.paths.raw_frames_jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_json_safe(raw_frame), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        self.total_raw_frames += 1

    def write_pinch_sample(
        self,
        sample: Any,
        *,
        calibration: Any,
        zone: str,
    ) -> None:
        """Append one pinch sample row aligned to the active calibration."""

        row = {
            "session_id": getattr(sample, "session_id", self.session_id),
            "frame_index": getattr(sample, "frame_index", None),
            "wall_time_iso": getattr(sample, "wall_time_iso", ""),
            "monotonic_ms": getattr(sample, "monotonic_ms", None),
            "source_timestamp": getattr(sample, "source_timestamp", None),
            "source_frame_id": getattr(sample, "source_frame_id", None),
            "hand_valid": getattr(sample, "hand_valid", False),
            "pinch_valid": getattr(sample, "pinch_valid", False),
            "pinch_distance": getattr(sample, "pinch_distance", None),
            "min_distance": getattr(calibration, "min_distance", None),
            "max_distance": getattr(calibration, "max_distance", None),
            "threshold_a": getattr(calibration, "threshold_a", None),
            "zone": zone,
            "thumb_node_id": getattr(sample, "thumb_node_id", None),
            "target_finger_node_id": getattr(sample, "target_finger_node_id", None),
            "tracker_present": getattr(sample, "tracker_present", False),
            "note": getattr(sample, "note", ""),
        }
        mode = "a" if self._pinch_header_written else "w"
        with self.paths.pinch_timeseries_csv.open(mode, newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=PINCH_TIMESERIES_FIELDS)
            if not self._pinch_header_written:
                writer.writeheader()
                self._pinch_header_written = True
            writer.writerow({field: row.get(field, "") for field in PINCH_TIMESERIES_FIELDS})
        self.total_pinch_samples += 1
        if bool(getattr(sample, "pinch_valid", False)):
            self.total_valid_pinch_samples += 1

    def write_nback_event(self, event: Any) -> None:
        """Append one 1-back trial event row."""

        row = _record_to_row(event)
        row.setdefault("session_id", self.session_id)
        mode = "a" if self._nback_header_written else "w"
        with self.paths.nback_events_csv.open(mode, newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=NBACK_EVENT_FIELDS)
            if not self._nback_header_written:
                writer.writeheader()
                self._nback_header_written = True
            writer.writerow({field: row.get(field, "") for field in NBACK_EVENT_FIELDS})
        self.total_nback_trials += 1
        if row.get("response_key") not in (None, ""):
            self.total_nback_responses += 1

    def write_nback_events(self, events: list[Any] | tuple[Any, ...]) -> None:
        """Append 1-back event rows, creating a header even when empty."""

        if not events and not self._nback_header_written:
            with self.paths.nback_events_csv.open("w", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=NBACK_EVENT_FIELDS).writeheader()
            self._nback_header_written = True
            return
        for event in events:
            self.write_nback_event(event)

    def write_calibration(self, calibration: Any) -> None:
        """Write calibration.json."""

        if hasattr(calibration, "to_dict"):
            payload = calibration.to_dict()
        elif hasattr(calibration, "__dict__"):
            payload = dict(calibration.__dict__)
        else:
            payload = calibration
        self.paths.calibration_json.write_text(
            json.dumps(_json_safe(payload), indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def write_wrist_rotation_calibration(self, calibration: Any) -> None:
        """Write wrist_rotation_calibration.json."""

        if hasattr(calibration, "to_dict"):
            payload = calibration.to_dict()
        elif hasattr(calibration, "__dict__"):
            payload = dict(calibration.__dict__)
        else:
            payload = calibration
        self.paths.wrist_rotation_calibration_json.write_text(
            json.dumps(_json_safe(payload), indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def write_wrist_rotation_sample(self, sample: Any) -> None:
        """Append one wrist rotation sample row."""

        row = sample.to_csv_row() if hasattr(sample, "to_csv_row") else _record_to_row(sample)
        row.setdefault("session_id", self.session_id)
        mode = "a" if self._wrist_rotation_header_written else "w"
        with self.paths.wrist_rotation_timeseries_csv.open(
            mode,
            newline="",
            encoding="utf-8",
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=WRIST_ROTATION_TIMESERIES_FIELDS)
            if not self._wrist_rotation_header_written:
                writer.writeheader()
                self._wrist_rotation_header_written = True
            writer.writerow(
                {field: row.get(field, "") for field in WRIST_ROTATION_TIMESERIES_FIELDS}
            )
        if bool(row.get("wrist_rotation_valid", False)):
            self.total_wrist_rotation_valid_samples += 1
        else:
            self.total_wrist_rotation_invalid_samples += 1

    def close_wrist_rotation_writer(self) -> None:
        """Placeholder for API symmetry; wrist rows are written eagerly."""

        return None

    def write_summary(self, summary: dict[str, Any]) -> None:
        """Write summary.json."""

        payload = dict(summary)
        payload.setdefault("session_id", self.session_id)
        payload.setdefault("output_files", self.paths.to_dict())
        payload.setdefault("total_raw_frames", self.total_raw_frames)
        payload.setdefault("total_pinch_samples", self.total_pinch_samples)
        payload.setdefault("total_valid_pinch_samples", self.total_valid_pinch_samples)
        payload.setdefault("total_nback_trials", self.total_nback_trials)
        payload.setdefault("total_nback_responses", self.total_nback_responses)
        payload.setdefault(
            "wrist_rotation_valid_samples",
            self.total_wrist_rotation_valid_samples,
        )
        payload.setdefault(
            "wrist_rotation_invalid_samples",
            self.total_wrist_rotation_invalid_samples,
        )
        self.paths.summary_json.write_text(
            json.dumps(_json_safe(payload), indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )


def make_session_id(prefix: str) -> str:
    """Return a filesystem-friendly session id using local wall time."""

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix_text = str(prefix).strip() or "pinch_haptic_dry_run"
    return f"{prefix_text}_{stamp}"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    if hasattr(value, "__dict__"):
        return {str(key): _json_safe(item) for key, item in value.__dict__.items()}
    return str(value)


def _record_to_row(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_csv_row"):
        return dict(value.to_csv_row())
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    raise ValueError("event row must be a dict or object with row fields.")
