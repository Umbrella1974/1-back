"""Simple haptic sender for TCP output and disabled-mode logging."""

from __future__ import annotations

import csv
import json
import socket
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vendor_exp2_abc.haptic_tcp_worker import (
    MatrixHapticConnectionError,
    MatrixTcpWorker,
)
from vendor_exp2_abc.matrix_haptic_protocol import encode_matrix_channel_packet
from vendor_exp2_abc.vibration_haptic_protocol import encode_vibration_line_command
from vendor_exp2_abc.vibration_tcp_worker import (
    VibrationHapticConnectionError,
    VibrationTcpLineWorker,
)


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
    "event_end_monotonic_ms",
    "end_command_label",
    "end_command_id",
    "end_command_due_ms",
    "end_command_sent",
    "end_command_tcp_success",
    "actual_duration_ms",
    "source_event_name",
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
    "not_sent_reason",
    "tcp_error",
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


@dataclass
class PendingVibrationEndCommand:
    due_monotonic_ms: float
    source_event_name: str
    command_label: str | None
    command_id: int
    haptic_trial_index: int
    event_index: int
    source_emit_monotonic_ms: float
    source_record: "HapticEventRecord | None" = None


@dataclass(frozen=True)
class SimpleHapticSenderConfig:
    """Haptic sender toggles for TCP output and disabled-mode logging."""

    vibration_enabled: bool = False
    matrix_enabled: bool = False
    visual_text_cue_enabled: bool = False
    disabled_mode: bool = True
    vibration_tcp_enabled: bool = False
    vibration_required: bool = False
    vibration_host: str = "127.0.0.1"
    vibration_port: int = 12346
    matrix_tcp_enabled: bool = False
    matrix_required: bool = False
    matrix_host: str = "127.0.0.1"
    matrix_port: int = 12345
    vibration_connect_timeout_s: float = 2.0
    vibration_send_timeout_s: float = 0.2
    matrix_connect_timeout_s: float = 2.0
    matrix_send_timeout_s: float = 0.2
    max_queue_size: int = 128
    matrix_latest_only: bool = True
    vibration_socket_factory: Any = socket.create_connection
    matrix_socket_factory: Any = socket.create_connection

    def __post_init__(self) -> None:
        for name in (
            "vibration_enabled",
            "matrix_enabled",
            "visual_text_cue_enabled",
            "disabled_mode",
            "vibration_tcp_enabled",
            "vibration_required",
            "matrix_tcp_enabled",
            "matrix_required",
            "matrix_latest_only",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be true or false.")
        if int(self.vibration_port) <= 0:
            raise ValueError("vibration_port must be positive.")
        if int(self.matrix_port) <= 0:
            raise ValueError("matrix_port must be positive.")
        for name in (
            "vibration_connect_timeout_s",
            "vibration_send_timeout_s",
            "matrix_connect_timeout_s",
            "matrix_send_timeout_s",
        ):
            if float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} must be non-negative.")
        if int(self.max_queue_size) <= 0:
            raise ValueError("max_queue_size must be positive.")


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
    event_end_monotonic_ms: float | None = None
    end_command_label: str | None = None
    end_command_id: int | None = None
    end_command_due_ms: float | None = None
    end_command_sent: bool = False
    end_command_tcp_success: bool | None = None
    actual_duration_ms: float | None = None
    source_event_name: str = ""
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
    not_sent_reason: str | None = None
    tcp_error: str | None = None
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
    queued_monotonic_ms: float | None = None
    sent_monotonic_ms: float | None = None

    def to_csv_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["channel_list"] = json.dumps(list(self.channel_list), separators=(",", ":"))
        row["tcp_queued"] = self.queued_monotonic_ms is not None or bool(self.tcp_queued)
        row["tcp_success"] = self.success
        row["tcp_error"] = self.error
        return row

    @property
    def success(self) -> bool | None:
        return self.tcp_success

    @success.setter
    def success(self, value: bool | None) -> None:
        self.tcp_success = value

    @property
    def error(self) -> str | None:
        return self.tcp_error

    @error.setter
    def error(self, value: str | None) -> None:
        self.tcp_error = value


class SimpleHapticSender:
    """Send haptic events over TCP or record them in disabled mode."""

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
        self._vibration_worker: VibrationTcpLineWorker | None = None
        self._matrix_worker: MatrixTcpWorker | None = None
        self._connect_warnings: list[str] = []
        self._pending_end_commands: list[PendingVibrationEndCommand] = []
        self._start_tcp_workers()

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
            event_end_monotonic_ms=getattr(scheduled, "event_end_monotonic_ms", None),
            end_command_label=getattr(scheduled, "end_command_label", None),
            end_command_id=getattr(scheduled, "end_command_id", None),
            end_command_due_ms=getattr(scheduled, "event_end_monotonic_ms", None),
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
            record = self.send_contact(**kwargs)
            self._schedule_vibration_end_command(scheduled, record)
            return record
        if event_name == "release":
            record = self.send_release(**kwargs)
            self._schedule_vibration_end_command(scheduled, record)
            return record
        if event_name == "slip":
            record = self.send_slip(**kwargs)
            self._schedule_vibration_end_command(scheduled, record)
            return record
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
            record = self._record_event(event_name, "vibration", **kwargs)
            self._schedule_vibration_end_command(scheduled, record)
            return record
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
            end_command_label=getattr(event, "end_command_label", None),
            end_command_id=getattr(event, "end_command_id", None),
            **kwargs,
        )

    def poll_due_control_commands(self, now_ms: float) -> list[HapticEventRecord]:
        """Send pending vibration end commands whose due time has passed."""

        now = float(now_ms)
        due: list[PendingVibrationEndCommand] = []
        pending: list[PendingVibrationEndCommand] = []
        for command in self._pending_end_commands:
            if command.due_monotonic_ms <= now:
                due.append(command)
            else:
                pending.append(command)
        self._pending_end_commands = pending

        records: list[HapticEventRecord] = []
        for command in due:
            record = self._record_event(
                f"{command.source_event_name}_end",
                "vibration",
                haptic_trial_index=command.haptic_trial_index,
                event_index=command.event_index,
                command_label=command.command_label,
                command_id=command.command_id,
                monotonic_ms=now,
                source_event_name=command.source_event_name,
                end_command_due_ms=command.due_monotonic_ms,
                note="vibration_end_command",
            )
            record.actual_duration_ms = max(0.0, float(record.monotonic_ms) - command.source_emit_monotonic_ms)
            if command.source_record is not None:
                command.source_record.end_command_sent = True
                command.source_record.end_command_tcp_success = record.tcp_success
                command.source_record.actual_duration_ms = record.actual_duration_ms
            print(
                "[HAPTIC] "
                f"end_command source={command.source_event_name} "
                f"command_id={command.command_id} "
                f"tcp={'queued' if record.tcp_queued else record.send_status}"
            )
            records.append(record)
        return records

    def write_csv(self, path: str | Path) -> Path:
        self.poll_due_control_commands(float("inf"))
        self.close()
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=HAPTIC_EVENT_FIELDS)
            writer.writeheader()
            for record in self.records:
                row = record.to_csv_row()
                writer.writerow({field: row.get(field, "") for field in HAPTIC_EVENT_FIELDS})
        return target

    def close(self) -> None:
        if self._vibration_worker is not None:
            self._vibration_worker.stop()
            self._vibration_worker = None
        if self._matrix_worker is not None:
            self._matrix_worker.stop()
            self._matrix_worker = None

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
        event_end_monotonic_ms: float | None = None,
        end_command_label: str | None = None,
        end_command_id: int | None = None,
        end_command_due_ms: float | None = None,
        end_command_sent: bool = False,
        end_command_tcp_success: bool | None = None,
        actual_duration_ms: float | None = None,
        source_event_name: str = "",
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
        tcp_enabled = self._tcp_enabled_for_modality(modality, target_enabled)
        status = "planned"
        tcp_queued = False
        tcp_success: bool | None = None
        notes = [item for item in (note,) if item]
        if not tcp_enabled:
            status = "disabled"
            tcp_success = False
            notes.append(_disabled_note_for_modality(self.config, modality))
        elif modality == "vibration" and self._vibration_worker is None:
            status = "not_connected"
            tcp_success = False
            notes.append("vibration_tcp_not_connected")
        elif modality == "matrix" and self._matrix_worker is None:
            status = "not_connected"
            tcp_success = False
            notes.append("matrix_tcp_not_connected")
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
            event_end_monotonic_ms=(
                float(event_end_monotonic_ms) if event_end_monotonic_ms is not None else None
            ),
            end_command_label=end_command_label,
            end_command_id=int(end_command_id) if end_command_id is not None else None,
            end_command_due_ms=(
                float(end_command_due_ms) if end_command_due_ms is not None else None
            ),
            end_command_sent=bool(end_command_sent),
            end_command_tcp_success=end_command_tcp_success,
            actual_duration_ms=(
                float(actual_duration_ms) if actual_duration_ms is not None else None
            ),
            source_event_name=str(source_event_name or ""),
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
            not_sent_reason=None if tcp_enabled else _disabled_note_for_modality(self.config, modality),
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
        if tcp_enabled:
            self._submit_tcp(record, modality=modality)
            print(
                _haptic_console_line(record)
            )
        self.records.append(record)
        return record

    def _start_tcp_workers(self) -> None:
        if self.config.disabled_mode:
            return
        if self.config.vibration_enabled and self.config.vibration_tcp_enabled:
            self._vibration_worker = self._start_vibration_worker()
        if self.config.matrix_enabled and self.config.matrix_tcp_enabled:
            self._matrix_worker = self._start_matrix_worker()

    def _start_vibration_worker(self) -> VibrationTcpLineWorker | None:
        worker = VibrationTcpLineWorker(
            host=self.config.vibration_host,
            port=self.config.vibration_port,
            connect_timeout_s=self.config.vibration_connect_timeout_s,
            send_timeout_s=self.config.vibration_send_timeout_s,
            max_queue_size=self.config.max_queue_size,
            socket_factory=self.config.vibration_socket_factory,
        )
        try:
            worker.start()
            return worker
        except VibrationHapticConnectionError as exc:
            if self.config.vibration_required:
                raise
            self._connect_warnings.append(str(exc))
            print(f"[TCP HAPTIC WARNING] {exc}")
            return None

    def _start_matrix_worker(self) -> MatrixTcpWorker | None:
        worker = MatrixTcpWorker(
            host=self.config.matrix_host,
            port=self.config.matrix_port,
            connect_timeout_s=self.config.matrix_connect_timeout_s,
            send_timeout_s=self.config.matrix_send_timeout_s,
            max_queue_size=self.config.max_queue_size,
            latest_only=self.config.matrix_latest_only,
            socket_factory=self.config.matrix_socket_factory,
        )
        try:
            worker.start()
            return worker
        except MatrixHapticConnectionError as exc:
            if self.config.matrix_required:
                raise
            self._connect_warnings.append(str(exc))
            print(f"[TCP HAPTIC WARNING] {exc}")
            return None

    def _submit_tcp(self, record: HapticEventRecord, *, modality: str) -> None:
        if modality == "vibration":
            worker = self._vibration_worker
            if worker is None:
                record.success = False
                record.send_status = "not_connected"
                record.not_sent_reason = "not_connected"
                return
            payload = encode_vibration_line_command(_vibration_command_id(record))
            queued = worker.submit(record, payload)
            record.tcp_queued = bool(queued)
            return
        if modality == "matrix":
            worker = self._matrix_worker
            if worker is None:
                record.success = False
                record.send_status = "not_connected"
                record.not_sent_reason = "not_connected"
                return
            packet = encode_matrix_channel_packet(record.channel_list)
            queued = worker.submit(record, packet)
            record.tcp_queued = bool(queued)
            return

    def _tcp_enabled_for_modality(self, modality: str, target_enabled: bool) -> bool:
        if not target_enabled or self.config.disabled_mode:
            return False
        if modality == "vibration":
            return bool(self.config.vibration_tcp_enabled)
        if modality == "matrix":
            return bool(self.config.matrix_tcp_enabled)
        return False

    def _schedule_vibration_end_command(
        self,
        scheduled: Any,
        record: HapticEventRecord,
    ) -> None:
        if str(getattr(scheduled, "modality", "")) != "vibration":
            return
        end_command_id = getattr(scheduled, "end_command_id", None)
        if end_command_id is None:
            return
        due_ms = getattr(scheduled, "event_end_monotonic_ms", None)
        if due_ms is None:
            due_ms = float(record.monotonic_ms) + float(record.sampled_duration_ms or record.duration_ms or 0)
        record.end_command_due_ms = float(due_ms)
        self._pending_end_commands.append(
            PendingVibrationEndCommand(
                due_monotonic_ms=float(due_ms),
                source_event_name=str(getattr(scheduled, "event_name", record.event_name)),
                command_label=getattr(scheduled, "end_command_label", None),
                command_id=int(end_command_id),
                haptic_trial_index=int(getattr(scheduled, "haptic_trial_index", record.haptic_trial_index)),
                event_index=int(getattr(scheduled, "event_index", record.event_index)),
                source_emit_monotonic_ms=float(record.monotonic_ms),
                source_record=record,
            )
        )


def _validate_channel_list(channels: list[int] | tuple[int, ...]) -> list[int]:
    result: list[int] = []
    for channel in channels:
        if isinstance(channel, bool) or not isinstance(channel, int):
            raise ValueError("matrix channels must be integers.")
        if channel < 0 or channel > 127:
            raise ValueError("matrix channel must be in 0..127.")
        result.append(int(channel))
    return result


def _vibration_command_id(record: HapticEventRecord) -> int:
    if record.command_id is not None:
        return int(record.command_id)
    label_map = {
        "contact": 1,
        "contact_enter": 1,
        "release": 2,
        "contact_exit": 2,
        "slip": 3,
        "slip_start": 3,
    }
    command = label_map.get(str(record.command_label or record.event_name or ""))
    if command is None:
        raise ValueError(
            f"vibration event {record.event_name} requires command_id for real TCP."
        )
    return command


def _tcp_payload_preview(record: HapticEventRecord) -> str:
    if record.modality == "matrix":
        return json.dumps(record.channel_list, separators=(",", ":"))
    try:
        return str(_vibration_command_id(record))
    except ValueError:
        return str(record.command_label or "")


def _disabled_note_for_modality(config: SimpleHapticSenderConfig, modality: str) -> str:
    if config.disabled_mode:
        return "disabled_mode_no_tcp"
    if modality == "vibration" and not config.vibration_tcp_enabled:
        return "vibration_tcp_disabled"
    if modality == "matrix" and not config.matrix_tcp_enabled:
        return "matrix_tcp_disabled"
    return "haptic_modality_disabled"


def _haptic_console_line(record: HapticEventRecord) -> str:
    tcp_status = "queued" if record.tcp_queued else record.send_status
    if record.modality == "vibration":
        return (
            "[HAPTIC] "
            f"event={record.event_name} modality=vibration "
            f"command_id={_vibration_command_id(record)} tcp={tcp_status}"
        )
    if record.modality == "matrix":
        return (
            "[HAPTIC] "
            f"event={record.event_name} modality=matrix "
            f"channels={record.channel_list} tcp={tcp_status}"
        )
    return f"[HAPTIC] event={record.event_name} modality={record.modality} tcp={tcp_status}"
