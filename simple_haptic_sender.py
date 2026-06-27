"""Simple disabled-mode haptic sender for plan dry-runs and logging."""

from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HAPTIC_EVENT_FIELDS = [
    "session_id",
    "haptic_trial_index",
    "event_index",
    "wall_time_iso",
    "monotonic_ms",
    "event_name",
    "modality",
    "command_label",
    "command_id",
    "channel_list",
    "duration_ms",
    "sampled_duration_ms",
    "global_default_used",
    "trigger_zone",
    "actual_zone_at_emit",
    "trigger_pinch_distance",
    "trigger_frame_index",
    "vibration_enabled",
    "matrix_enabled",
    "tcp_enabled",
    "tcp_queued",
    "tcp_success",
    "send_status",
    "visual_text_cue_enabled",
    "original_planned_onset_ms",
    "adjusted_onset_ms",
    "nearest_digit_onset_ms",
    "digit_onset_delta_ms",
    "onset_was_delayed",
    "sync_warning",
    "sampled_delay_ms",
    "sampled_gap_ms",
    "timing_note",
    "end_reason",
    "haptic_episode_completed",
    "note",
]


@dataclass(frozen=True)
class SimpleHapticSenderConfig:
    """Haptic sender toggles for the phase-one disabled sender."""

    vibration_enabled: bool = False
    matrix_enabled: bool = False
    visual_text_cue_enabled: bool = False
    disabled_mode: bool = True

    def __post_init__(self) -> None:
        for name in (
            "vibration_enabled",
            "matrix_enabled",
            "visual_text_cue_enabled",
            "disabled_mode",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be true or false.")
        if not self.disabled_mode:
            raise NotImplementedError("SimpleHapticSender currently implements disabled mode only.")


@dataclass
class HapticEventRecord:
    """One haptic event log row."""

    session_id: str
    haptic_trial_index: int
    event_index: int
    wall_time_iso: str
    monotonic_ms: float
    event_name: str
    modality: str
    command_label: str | None = None
    command_id: int | None = None
    channel_list: list[int] = field(default_factory=list)
    duration_ms: int | None = None
    sampled_duration_ms: int | None = None
    global_default_used: bool = False
    trigger_zone: str | None = None
    actual_zone_at_emit: str | None = None
    trigger_pinch_distance: float | None = None
    trigger_frame_index: int | None = None
    vibration_enabled: bool = False
    matrix_enabled: bool = False
    tcp_enabled: bool = False
    tcp_queued: bool = False
    tcp_success: bool | None = None
    send_status: str = "planned"
    visual_text_cue_enabled: bool = False
    original_planned_onset_ms: float | None = None
    adjusted_onset_ms: float | None = None
    nearest_digit_onset_ms: float | None = None
    digit_onset_delta_ms: float | None = None
    onset_was_delayed: bool = False
    sync_warning: str = ""
    sampled_delay_ms: int | None = None
    sampled_gap_ms: int | None = None
    timing_note: str = ""
    end_reason: str = ""
    haptic_episode_completed: bool = False
    note: str = ""

    def to_csv_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["channel_list"] = json.dumps(list(self.channel_list), separators=(",", ":"))
        return row


class SimpleHapticSender:
    """Record haptic events without opening TCP connections."""

    def __init__(
        self,
        config: SimpleHapticSenderConfig | None = None,
        *,
        session_id: str = "",
        monotonic_ms_fn: Any | None = None,
        wall_time_fn: Any | None = None,
    ) -> None:
        self.config = config or SimpleHapticSenderConfig()
        self.session_id = str(session_id)
        self.monotonic_ms_fn = monotonic_ms_fn or (lambda: time.monotonic() * 1000.0)
        self.wall_time_fn = wall_time_fn or time.time
        self.records: list[HapticEventRecord] = []

    def send_contact(self, **kwargs: Any) -> HapticEventRecord:
        return self._record_event("contact", "vibration", **kwargs)

    def send_release(self, **kwargs: Any) -> HapticEventRecord:
        return self._record_event("release", "vibration", **kwargs)

    def send_slip(self, **kwargs: Any) -> HapticEventRecord:
        return self._record_event("slip", "vibration", **kwargs)

    def send_matrix_left(self, channel_list: list[int] | tuple[int, ...], **kwargs: Any) -> HapticEventRecord:
        return self._record_event("left", "matrix", channel_list=channel_list, **kwargs)

    def send_matrix_right(self, channel_list: list[int] | tuple[int, ...], **kwargs: Any) -> HapticEventRecord:
        return self._record_event("right", "matrix", channel_list=channel_list, **kwargs)

    def send_off(self, **kwargs: Any) -> HapticEventRecord:
        return self._record_event("off", "none", **kwargs)

    def record_scheduled_event(self, scheduled: Any) -> HapticEventRecord:
        """Record one ScheduledHapticEvent-like object in disabled sender format."""

        event_name = str(getattr(scheduled, "event_name"))
        kwargs = dict(
            haptic_trial_index=getattr(scheduled, "haptic_trial_index"),
            event_index=getattr(scheduled, "event_index"),
            command_label=getattr(scheduled, "command_label", None),
            command_id=getattr(scheduled, "command_id", None),
            duration_ms=getattr(scheduled, "duration_ms", None),
            sampled_duration_ms=getattr(scheduled, "sampled_duration_ms", None),
            global_default_used=getattr(scheduled, "global_default_used", False),
            trigger_zone=getattr(scheduled, "trigger_zone", None),
            actual_zone_at_emit=getattr(scheduled, "actual_zone_at_emit", None),
            trigger_pinch_distance=getattr(scheduled, "trigger_pinch_distance", None),
            trigger_frame_index=getattr(scheduled, "trigger_frame_index", None),
            monotonic_ms=getattr(scheduled, "actual_emit_monotonic_ms", None),
            original_planned_onset_ms=getattr(
                scheduled,
                "original_planned_onset_ms",
                None,
            ),
            adjusted_onset_ms=getattr(scheduled, "adjusted_onset_ms", None),
            nearest_digit_onset_ms=getattr(scheduled, "nearest_digit_onset_ms", None),
            digit_onset_delta_ms=getattr(scheduled, "digit_onset_delta_ms", None),
            onset_was_delayed=getattr(scheduled, "onset_was_delayed", False),
            sync_warning=getattr(scheduled, "sync_warning", ""),
            sampled_delay_ms=getattr(scheduled, "sampled_delay_ms", None),
            sampled_gap_ms=getattr(scheduled, "sampled_gap_ms", None),
            timing_note=getattr(scheduled, "timing_note", ""),
            end_reason=getattr(scheduled, "end_reason", ""),
            haptic_episode_completed=getattr(scheduled, "haptic_episode_completed", False),
        )
        if event_name == "contact":
            return self.send_contact(**kwargs)
        if event_name == "release":
            return self.send_release(**kwargs)
        if event_name == "slip":
            return self.send_slip(**kwargs)
        if event_name == "left":
            return self.send_matrix_left(
                list(getattr(scheduled, "channel_list", ()) or ()),
                **kwargs,
            )
        if event_name == "right":
            return self.send_matrix_right(
                list(getattr(scheduled, "channel_list", ()) or ()),
                **kwargs,
            )
        modality = str(getattr(scheduled, "modality", ""))
        if modality == "vibration":
            return self._record_event(event_name, "vibration", **kwargs)
        if modality == "matrix":
            return self._record_event(
                event_name,
                "matrix",
                channel_list=list(getattr(scheduled, "channel_list", ()) or ()),
                **kwargs,
            )
        raise ValueError(f"unsupported scheduled haptic event: {event_name}")

    def record_plan_event(self, event: Any, **kwargs: Any) -> HapticEventRecord:
        """Record a parsed HapticPlanEvent-like object."""

        return self._record_event(
            getattr(event, "name"),
            getattr(event, "modality"),
            command_label=getattr(event, "command_label", None),
            command_id=getattr(event, "command_id", None),
            channel_list=list(getattr(event, "channel_list", ()) or ()),
            duration_ms=getattr(event, "duration_ms", None),
            trigger_zone=getattr(event, "trigger_zone", None),
            **kwargs,
        )

    def write_csv(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=HAPTIC_EVENT_FIELDS)
            writer.writeheader()
            for record in self.records:
                row = record.to_csv_row()
                writer.writerow({field: row.get(field, "") for field in HAPTIC_EVENT_FIELDS})
        return target

    def _record_event(
        self,
        event_name: str,
        modality: str,
        *,
        haptic_trial_index: int = 0,
        event_index: int | None = None,
        command_label: str | None = None,
        command_id: int | None = None,
        channel_list: list[int] | tuple[int, ...] | None = None,
        duration_ms: int | None = None,
        sampled_duration_ms: int | None = None,
        global_default_used: bool = False,
        trigger_zone: str | None = None,
        actual_zone_at_emit: str | None = None,
        trigger_pinch_distance: float | None = None,
        trigger_frame_index: int | None = None,
        monotonic_ms: float | None = None,
        original_planned_onset_ms: float | None = None,
        adjusted_onset_ms: float | None = None,
        nearest_digit_onset_ms: float | None = None,
        digit_onset_delta_ms: float | None = None,
        onset_was_delayed: bool = False,
        sync_warning: str = "",
        sampled_delay_ms: int | None = None,
        sampled_gap_ms: int | None = None,
        timing_note: str = "",
        end_reason: str = "",
        haptic_episode_completed: bool = False,
        note: str = "",
    ) -> HapticEventRecord:
        index = len(self.records) if event_index is None else int(event_index)
        target_enabled = (
            self.config.vibration_enabled
            if modality == "vibration"
            else self.config.matrix_enabled
            if modality == "matrix"
            else False
        )
        tcp_enabled = bool(target_enabled and not self.config.disabled_mode)
        status = "planned"
        tcp_queued = False
        tcp_success: bool | None = None
        notes = [item for item in (note,) if item]
        if not tcp_enabled:
            status = "disabled"
            tcp_success = False
            notes.append("disabled_mode_no_tcp")
        record = HapticEventRecord(
            session_id=self.session_id,
            haptic_trial_index=int(haptic_trial_index),
            event_index=index,
            wall_time_iso=datetime.fromtimestamp(float(self.wall_time_fn()), timezone.utc).isoformat(),
            monotonic_ms=(
                float(monotonic_ms)
                if monotonic_ms is not None
                else float(self.monotonic_ms_fn())
            ),
            event_name=str(event_name),
            modality=str(modality),
            command_label=command_label,
            command_id=int(command_id) if command_id is not None else None,
            channel_list=_validate_channel_list(channel_list or ()),
            duration_ms=int(duration_ms) if duration_ms is not None else None,
            sampled_duration_ms=(
                int(sampled_duration_ms) if sampled_duration_ms is not None else None
            ),
            global_default_used=bool(global_default_used),
            trigger_zone=trigger_zone,
            actual_zone_at_emit=actual_zone_at_emit,
            trigger_pinch_distance=(
                float(trigger_pinch_distance)
                if trigger_pinch_distance is not None
                else None
            ),
            trigger_frame_index=(
                int(trigger_frame_index) if trigger_frame_index is not None else None
            ),
            vibration_enabled=self.config.vibration_enabled,
            matrix_enabled=self.config.matrix_enabled,
            tcp_enabled=tcp_enabled,
            tcp_queued=tcp_queued,
            tcp_success=tcp_success,
            send_status=status,
            visual_text_cue_enabled=self.config.visual_text_cue_enabled,
            original_planned_onset_ms=original_planned_onset_ms,
            adjusted_onset_ms=adjusted_onset_ms,
            nearest_digit_onset_ms=nearest_digit_onset_ms,
            digit_onset_delta_ms=digit_onset_delta_ms,
            onset_was_delayed=bool(onset_was_delayed),
            sync_warning=sync_warning,
            sampled_delay_ms=int(sampled_delay_ms) if sampled_delay_ms is not None else None,
            sampled_gap_ms=int(sampled_gap_ms) if sampled_gap_ms is not None else None,
            timing_note=timing_note,
            end_reason=end_reason,
            haptic_episode_completed=bool(haptic_episode_completed),
            note=";".join(notes),
        )
        self.records.append(record)
        return record


def _validate_channel_list(channels: list[int] | tuple[int, ...]) -> list[int]:
    result: list[int] = []
    for channel in channels:
        if isinstance(channel, bool) or not isinstance(channel, int):
            raise ValueError("matrix channels must be integers.")
        if channel < 0 or channel > 127:
            raise ValueError("matrix channel must be in 0..127.")
        result.append(int(channel))
    return result
