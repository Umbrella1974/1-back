"""Command-line haptic pattern learning tool."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
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

EVENT_LABELS = {
    "contact": "contact / 接触",
    "release": "release / 释放",
    "slip": "slip / 滑动",
    "left": "left / 左",
    "right": "right / 右",
    "up": "up / 前/上",
    "down": "down / 后/下",
}


@dataclass(frozen=True)
class LearningSession:
    mode_name: str
    config_path: Path
    plan_path: Path
    plan: HapticPlanConfig
    events: tuple[HapticPlanEvent, ...]
    sender_config: SimpleHapticSenderConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Learn and replay haptic patterns.")
    parser.add_argument("--config", default=None, help="Run one config directly.")
    parser.add_argument("--mode", choices=sorted(MODE_CONFIGS), default=None)
    args = parser.parse_args()

    if args.config:
        _run_session(load_learning_session(Path(args.config), mode_name=Path(args.config).stem))
        return 0
    if args.mode:
        _run_session(load_learning_session(Path(MODE_CONFIGS[args.mode]), mode_name=args.mode))
        return 0
    _run_mode_menu()
    return 0


def load_learning_session(config_path: str | Path, *, mode_name: str = "") -> LearningSession:
    target = Path(config_path)
    config = load_dualtask_config(target)
    session_config = _object_section(config, "session")
    plan_path = Path(session_config.get("haptic_plan_config", "haptic_plan_config_example.yaml"))
    plan = load_haptic_plan_config(plan_path)
    events = unique_learning_events(plan)
    return LearningSession(
        mode_name=mode_name or target.stem,
        config_path=target,
        plan_path=plan_path,
        plan=plan,
        events=events,
        sender_config=sender_config_from_learning_config(config),
    )


def unique_learning_events(plan: HapticPlanConfig) -> tuple[HapticPlanEvent, ...]:
    """Return first occurrence of each event name, preserving plan order."""

    seen: set[str] = set()
    events: list[HapticPlanEvent] = []
    for event in plan.events:
        if event.name in seen:
            continue
        seen.add(event.name)
        events.append(event)
    return tuple(events)


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


def _run_mode_menu() -> None:
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
        if _run_session(load_learning_session(Path(MODE_CONFIGS[mode]), mode_name=mode)):
            return


def _run_session(session: LearningSession) -> bool:
    print(f"\nMode: {session.mode_name}")
    print(f"Config: {session.config_path}")
    print(f"Plan: {session.plan_path} ({session.plan.plan_id})")
    print(_sender_status_text(session.sender_config))
    sender = SimpleHapticSender(session.sender_config, session_id=f"learn_{session.mode_name}")
    last_event: HapticPlanEvent | None = None
    try:
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
                _play_event(sender, last_event)
                continue
            if not choice.isdigit() or not 1 <= int(choice) <= len(session.events):
                print("Invalid choice.")
                continue
            last_event = session.events[int(choice) - 1]
            _play_event(sender, last_event)
    finally:
        sender.close()
    return False


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


def _play_event(sender: SimpleHapticSender, event: HapticPlanEvent) -> None:
    print(f"\nPlaying: {_event_menu_label(event)}")
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
    print("Done.")


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
