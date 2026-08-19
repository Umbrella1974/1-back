"""Command-line haptic pattern learning tool."""

from __future__ import annotations

import argparse
import csv
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from haptic_plan_config import HapticPlanConfig, HapticPlanEvent, load_haptic_plan_config
from run_pinch_haptic_dry_run import load_dualtask_config
from run_pinch_haptic_1back import _bool_config_value
from simple_haptic_sender import SimpleHapticSender, SimpleHapticSenderConfig


MODE_CONFIGS = {
    "dual": "dualtask_config.yaml",
    "only-motor": "only-motor.yaml",
    "only-matrix": "only-matrix.yaml",
}

MODE_PLAN_PATTERNS = {
    "dual": "haptic_plan_dual-*.yaml",
    "only-motor": "haptic-plan-only-motor-*.yaml",
    "only-matrix": "haptic-plan-only-matrix-*.yaml",
}

EVENT_LABELS = {
    "contact": "contact / 接触",
    "release": "release / 释放",
    "slip": "slip / 滑动",
    "left": "left / 左",
    "right": "right / 右",
    "up": "up /上",
    "down": "down /下",
}

LEARNING_LOG_FIELDS = [
    "timestamp",
    "session_id",
    "participant_id",
    "mode_name",
    "phase",
    "play_index",
    "event_name",
    "label",
    "modality",
    "command_label",
    "command_id",
    "channel_list",
    "matrix_sequence_step_count",
    "status",
]


@dataclass(frozen=True)
class LearningSession:
    mode_name: str
    config_path: Path
    plan_path: Path
    plan_paths: tuple[Path, ...]
    plan: HapticPlanConfig
    events: tuple[HapticPlanEvent, ...]
    sender_config: SimpleHapticSenderConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Learn and replay haptic patterns.")
    parser.add_argument("--config", default=None, help="Run one config directly.")
    parser.add_argument("--mode", choices=sorted(MODE_CONFIGS), default=None)
    parser.add_argument("--participant-id", default=None)
    args = parser.parse_args()
    participant_id = _prompt_participant_id(args.participant_id)

    if args.config:
        config_path = Path(args.config)
        mode_name = args.mode or _mode_name_for_config_path(config_path)
        _run_session(load_learning_session(config_path, mode_name=mode_name), participant_id=participant_id)
        return 0
    if args.mode:
        _run_session(
            load_learning_session(Path(MODE_CONFIGS[args.mode]), mode_name=args.mode),
            participant_id=participant_id,
        )
        return 0
    _run_mode_menu(participant_id=participant_id)
    return 0


def load_learning_session(config_path: str | Path, *, mode_name: str = "") -> LearningSession:
    target = Path(config_path)
    config = load_dualtask_config(target)
    session_config = _object_section(config, "session")
    plan_path = Path(session_config.get("haptic_plan_config", "haptic_plan_config_example.yaml"))
    plan = load_haptic_plan_config(plan_path)
    plan_paths = _learning_plan_paths(mode_name or target.stem, plan_path)
    events = unique_learning_events_from_plans(load_haptic_plan_config(path) for path in plan_paths)
    return LearningSession(
        mode_name=mode_name or target.stem,
        config_path=target,
        plan_path=plan_path,
        plan_paths=plan_paths,
        plan=plan,
        events=events,
        sender_config=sender_config_from_learning_config(config),
    )


def unique_learning_events(plan: HapticPlanConfig) -> tuple[HapticPlanEvent, ...]:
    """Return first occurrence of each event name, preserving plan order."""

    return unique_learning_events_from_plans((plan,))


def unique_learning_events_from_plans(
    plans: tuple[HapticPlanConfig, ...] | list[HapticPlanConfig] | Any,
) -> tuple[HapticPlanEvent, ...]:
    """Return first occurrence of each non-release event across learning templates."""

    seen: set[str] = set()
    events: list[HapticPlanEvent] = []
    release_event: HapticPlanEvent | None = None
    for plan in plans:
        for event in plan.events:
            if event.name == "release":
                if release_event is None:
                    release_event = event
                continue
            if event.name in seen:
                continue
            seen.add(event.name)
            events.append(event)
    if release_event is not None and "release" not in seen:
        events.append(release_event)
    return tuple(events)


def _mode_name_for_config_path(config_path: Path) -> str:
    for mode_name, configured_path in MODE_CONFIGS.items():
        if config_path.name.lower() == Path(configured_path).name.lower():
            return mode_name
    return config_path.stem


def _learning_plan_paths(mode_name: str, fallback_plan_path: Path) -> tuple[Path, ...]:
    pattern = MODE_PLAN_PATTERNS.get(mode_name)
    if not pattern:
        return (fallback_plan_path,)
    paths = tuple(sorted(Path(".").glob(pattern)))
    return paths or (fallback_plan_path,)


def sender_config_from_learning_config(config: dict[str, Any]) -> SimpleHapticSenderConfig:
    haptic_config = _object_section(config, "haptic")
    vibration_tcp_config = _object_section(config, "vibration_tcp")
    matrix_tcp_config = _object_section(config, "matrix_tcp")
    vibration_enabled = _bool_config_value(
        haptic_config.get("vibration_enabled", False),
        "haptic.vibration_enabled",
    )
    matrix_enabled = _bool_config_value(
        haptic_config.get("matrix_enabled", False),
        "haptic.matrix_enabled",
    )
    vibration_tcp_enabled = vibration_enabled and _bool_config_value(
        vibration_tcp_config.get("enabled", False),
        "vibration_tcp.enabled",
    )
    matrix_tcp_enabled = matrix_enabled and _bool_config_value(
        matrix_tcp_config.get("enabled", False),
        "matrix_tcp.enabled",
    )
    return SimpleHapticSenderConfig(
        vibration_enabled=vibration_enabled,
        matrix_enabled=matrix_enabled,
        visual_text_cue_enabled=False,
        disabled_mode=not (vibration_tcp_enabled or matrix_tcp_enabled),
        vibration_tcp_enabled=vibration_tcp_enabled,
        vibration_required=vibration_tcp_enabled,
        vibration_host=str(vibration_tcp_config.get("host", "127.0.0.1")),
        vibration_port=int(vibration_tcp_config.get("port", 12346)),
        vibration_handshake_enabled=_bool_config_value(
            vibration_tcp_config.get("handshake_enabled", True),
            "vibration_tcp.handshake_enabled",
        ),
        vibration_handshake_command=str(
            vibration_tcp_config.get("handshake_command", "PING")
        ),
        vibration_handshake_expected_response=str(
            vibration_tcp_config.get("handshake_expected_response", "OK")
        ),
        vibration_handshake_timeout_s=float(
            vibration_tcp_config.get("handshake_timeout_s", 1.0)
        ),
        matrix_tcp_enabled=matrix_tcp_enabled,
        matrix_required=matrix_tcp_enabled,
        matrix_host=str(matrix_tcp_config.get("host", "127.0.0.1")),
        matrix_port=int(matrix_tcp_config.get("port", 12345)),
        vibration_connect_timeout_s=float(vibration_tcp_config.get("connect_timeout_s", 2.0)),
        vibration_send_timeout_s=float(vibration_tcp_config.get("send_timeout_s", 0.2)),
        matrix_connect_timeout_s=float(matrix_tcp_config.get("connect_timeout_s", 2.0)),
        matrix_send_timeout_s=float(matrix_tcp_config.get("send_timeout_s", 0.2)),
        max_queue_size=int(haptic_config.get("max_queue_size", 128)),
        matrix_latest_only=False,
    )


def _run_mode_menu(*, participant_id: str) -> None:
    choices = list(MODE_CONFIGS)
    while True:
        print("\nSelect learning mode:")
        for index, mode in enumerate(choices, start=1):
            print(f"  [{index}] {mode} ({MODE_CONFIGS[mode]})")
        print("  [q] quit")
        choice = input("> ").strip().lower()
        if choice == "q":
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(choices):
            print("Invalid choice.")
            continue
        mode = choices[int(choice) - 1]
        if _run_session(
            load_learning_session(Path(MODE_CONFIGS[mode]), mode_name=mode),
            participant_id=participant_id,
        ):
            return


def _run_session(session: LearningSession, *, participant_id: str) -> bool:
    print(f"\nMode: {session.mode_name}")
    print(f"Config: {session.config_path}")
    print(f"Plan: {session.plan_path} ({session.plan.plan_id})")
    if len(session.plan_paths) > 1:
        print(f"Learning templates: {len(session.plan_paths)}")
    print(_sender_status_text(session.sender_config))
    session_id = _learning_session_id(participant_id, session.mode_name)
    sender = SimpleHapticSender(session.sender_config, session_id=session_id)
    log_path = _learning_log_path(participant_id, session.mode_name)
    play_index = 0
    last_event: HapticPlanEvent | None = None
    try:
        play_index, last_event, quit_requested = _run_ordered_learning(
            session,
            sender,
            log_path=log_path,
            participant_id=participant_id,
            session_id=session_id,
            start_play_index=play_index,
        )
        if quit_requested:
            print(f"Learning log: {log_path}")
            return True
        while True:
            _print_event_menu(session.events)
            choice = input("> ").strip().lower()
            if choice == "q":
                return True
            if choice == "m":
                return False
            if choice == "r":
                if last_event is None:
                    print("No previous haptic.")
                    continue
                play_index += 1
                _play_event(
                    sender,
                    last_event,
                    log_path=log_path,
                    session=session,
                    participant_id=participant_id,
                    session_id=session_id,
                    phase="free_replay",
                    play_index=play_index,
                )
                continue
            if not choice.isdigit() or not 1 <= int(choice) <= len(session.events):
                print("Invalid choice.")
                continue
            last_event = session.events[int(choice) - 1]
            play_index += 1
            _play_event(
                sender,
                last_event,
                log_path=log_path,
                session=session,
                participant_id=participant_id,
                session_id=session_id,
                phase="free_select",
                play_index=play_index,
            )
    finally:
        sender.close()
    return False


def _run_ordered_learning(
    session: LearningSession,
    sender: SimpleHapticSender,
    *,
    log_path: Path,
    participant_id: str,
    session_id: str,
    start_play_index: int = 0,
) -> tuple[int, HapticPlanEvent | None, bool]:
    print("\nOrdered learning / 顺序学习")
    print("Press Enter to play each cue, r to replay current cue, s to skip, q to quit.")
    play_index = int(start_play_index)
    last_event: HapticPlanEvent | None = None
    for index, event in enumerate(session.events, start=1):
        while True:
            choice = input(f"[{index}/{len(session.events)}] {_event_menu_label(event)} > ").strip().lower()
            if choice == "q":
                return play_index, last_event, True
            if choice == "s":
                _append_learning_log(
                    log_path,
                    session=session,
                    participant_id=participant_id,
                    session_id=session_id,
                    event=event,
                    phase="ordered_skip",
                    play_index=play_index,
                    status="skipped",
                )
                break
            if choice == "r":
                play_index += 1
                last_event = event
                _play_event(
                    sender,
                    event,
                    log_path=log_path,
                    session=session,
                    participant_id=participant_id,
                    session_id=session_id,
                    phase="ordered_replay",
                    play_index=play_index,
                )
                continue
            if choice:
                print("Invalid choice.")
                continue
            play_index += 1
            last_event = event
            _play_event(
                sender,
                event,
                log_path=log_path,
                session=session,
                participant_id=participant_id,
                session_id=session_id,
                phase="ordered",
                play_index=play_index,
            )
            break
    print(f"Ordered learning complete. Log: {log_path}")
    return play_index, last_event, False


def _print_event_menu(events: tuple[HapticPlanEvent, ...]) -> None:
    print("\nSelect haptic to play:")
    for index, event in enumerate(events, start=1):
        print(f"  [{index}] {_event_menu_label(event)}")
    print("  [r] replay last")
    print("  [m] mode menu / back")
    print("  [q] quit")


def _event_menu_label(event: HapticPlanEvent) -> str:
    base = EVENT_LABELS.get(event.name, event.name)
    detail = event.modality
    if event.matrix_sequence:
        detail += f", sequence {len(event.matrix_sequence)} steps"
    elif event.channel_list:
        detail += f", channels {list(event.channel_list)}"
    elif event.command_id is not None:
        detail += f", command {event.command_id}"
    return f"{base} ({detail})"


def _play_event(
    sender: SimpleHapticSender,
    event: HapticPlanEvent,
    *,
    log_path: Path | None = None,
    session: LearningSession | None = None,
    participant_id: str = "",
    session_id: str = "",
    phase: str = "",
    play_index: int = 0,
) -> None:
    print(f"\nPlaying: {_event_menu_label(event)}")
    start_ms = time.monotonic() * 1000.0
    status = "played"
    try:
        sender.record_scheduled_event(
            _scheduled_event_for_learning(
                event,
                event_index=len(sender.records),
                start_ms=start_ms,
            )
        )
        if event.modality == "matrix" and event.matrix_sequence:
            time.sleep(float(event.matrix_sequence[-1].offset_ms) / 1000.0)
        if event.modality == "vibration":
            sender.poll_due_control_commands(start_ms + float(event.duration_ms or 0))
    except Exception:
        status = "send_failed"
        raise
    finally:
        if log_path is not None and session is not None:
            _append_learning_log(
                log_path,
                session=session,
                participant_id=participant_id,
                session_id=session_id,
                event=event,
                phase=phase,
                play_index=play_index,
                status=status,
            )
    print("Done.")


def play_event_once_for_test(sender: SimpleHapticSender, event: HapticPlanEvent) -> None:
    """Replay one haptic event for non-interactive callers."""

    start_ms = time.monotonic() * 1000.0
    sender.record_scheduled_event(
        _scheduled_event_for_learning(
            event,
            event_index=len(sender.records),
            start_ms=start_ms,
        )
    )
    if event.modality == "matrix" and event.matrix_sequence:
        time.sleep(float(event.matrix_sequence[-1].offset_ms) / 1000.0)
    if event.modality == "vibration":
        sender.poll_due_control_commands(start_ms + float(event.duration_ms or 0))


def _learning_log_path(participant_id: str, mode_name: str) -> Path:
    root = Path("outputs") / "haptic_learning_logs"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return root / f"learn_{_safe_text(participant_id)}_{_safe_text(mode_name)}_{stamp}.csv"


def _append_learning_log(
    path: Path,
    *,
    session: LearningSession,
    participant_id: str,
    session_id: str,
    event: HapticPlanEvent,
    phase: str,
    play_index: int,
    status: str,
) -> None:
    row = _learning_log_row(
        session=session,
        participant_id=participant_id,
        session_id=session_id,
        event=event,
        phase=phase,
        play_index=play_index,
        status=status,
    )
    mode = "a" if path.exists() else "w"
    with path.open(mode, newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEARNING_LOG_FIELDS)
        if mode == "w":
            writer.writeheader()
        writer.writerow(row)


def _learning_log_row(
    *,
    session: LearningSession,
    participant_id: str = "",
    session_id: str = "",
    event: HapticPlanEvent,
    phase: str,
    play_index: int,
    status: str,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "session_id": session_id or _learning_session_id(participant_id, session.mode_name),
        "participant_id": participant_id,
        "mode_name": session.mode_name,
        "phase": phase,
        "play_index": int(play_index),
        "event_name": event.name,
        "label": EVENT_LABELS.get(event.name, event.name),
        "modality": event.modality,
        "command_label": event.command_label or "",
        "command_id": event.command_id if event.command_id is not None else "",
        "channel_list": list(event.channel_list or ()),
        "matrix_sequence_step_count": len(event.matrix_sequence or ()),
        "status": status,
    }


def _safe_text(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    return "".join(ch if ch in allowed else "_" for ch in str(value)) or "session"


def _prompt_participant_id(value: str | None = None) -> str:
    if value is not None and str(value).strip():
        return _safe_text(str(value).strip())
    entered = input("Participant ID / 参与者ID（可直接回车 anonymous）: ").strip()
    return _safe_text(entered or "anonymous")


def _learning_session_id(participant_id: str, mode_name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"learn_{_safe_text(participant_id)}_{_safe_text(mode_name)}_{stamp}"


def _scheduled_event_for_learning(
    event: HapticPlanEvent,
    *,
    event_index: int,
    start_ms: float,
) -> Any:
    duration_ms = int(event.duration_ms or 0)
    return SimpleNamespace(
        haptic_trial_index=0,
        event_index=event_index,
        event_name=event.name,
        simultaneous_group=event.simultaneous_group,
        modality=event.modality,
        command_label=event.command_label,
        command_id=event.command_id,
        end_command_label=event.end_command_label,
        end_command_id=event.end_command_id,
        channel_list=event.channel_list,
        matrix_sequence=event.matrix_sequence,
        duration_ms=duration_ms,
        sampled_duration_ms=duration_ms,
        event_end_monotonic_ms=start_ms + duration_ms,
        global_default_used=False,
        trigger_zone=event.trigger_zone,
        actual_zone_at_emit="learning",
        trigger_pinch_distance=None,
        trigger_frame_index=None,
        actual_emit_monotonic_ms=start_ms,
        original_planned_onset_ms=start_ms,
        adjusted_onset_ms=start_ms,
        nearest_digit_onset_ms=None,
        digit_onset_delta_ms=None,
        onset_was_delayed=False,
        sync_warning="",
        sampled_delay_ms=None,
        sampled_gap_ms=None,
        time_ready_ms=start_ms,
        actual_emit_ms=start_ms,
        planned_emit_trial_number=None,
        emit_trial_number=None,
        trial_gate_window=None,
        trial_gate_open_trial=None,
        held_by_trial_gate=False,
        late_window_warning="",
        wrist_neutral_gate_required=False,
        held_by_wrist_neutral_gate=False,
        wrist_neutral_gate_passed=None,
        wrist_neutral_wait_ms=None,
        wrist_lr_class_at_emit="",
        wrist_up_down_class_at_emit="",
        timing_note="learning_replay",
        end_reason="",
        haptic_episode_completed=False,
    )


def _sender_status_text(config: SimpleHapticSenderConfig) -> str:
    parts: list[str] = []
    if config.vibration_enabled:
        parts.append(
            f"vibration={config.vibration_host}:{config.vibration_port} "
            f"tcp={config.vibration_tcp_enabled}"
        )
    if config.matrix_enabled:
        parts.append(
            f"matrix={config.matrix_host}:{config.matrix_port} "
            f"tcp={config.matrix_tcp_enabled}"
        )
    return "Connections: " + (", ".join(parts) if parts else "disabled")


def _object_section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} section must be an object.")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
