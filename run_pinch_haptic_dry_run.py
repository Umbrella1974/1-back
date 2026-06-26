"""MANUS pinch + haptic scheduler disabled dry-run."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dualtask_logger import DualTaskLogger, make_session_id
from haptic_plan_config import HapticPlanConfig, load_haptic_plan_config
from haptic_trial_scheduler import HapticTrialScheduler, HapticTrialSchedulerConfig
from manus_pinch_input import ManusOnlyPinchInput, ManusPinchInputConfig, PinchInputSample
from pinch_calibration import (
    PinchCalibrationConfig,
    PinchCalibrationResult,
    calibrate_from_samples,
    classify_pinch_zone,
)
from simple_haptic_sender import SimpleHapticSender, SimpleHapticSenderConfig
from vendor_exp2_abc.live_raw_stream import LiveRawFrame, LiveRawStreamServer


DEFAULT_MANUS_TCP_HOST = "127.0.0.1"
DEFAULT_MANUS_TCP_PORT = 8888
MANUS_CLIENT_WAIT_TIMEOUT_S = 5.0
MANUS_CLIENT_HINTS = (
    "1. 确认 SDKMinimalClient_Windows 是在本程序启动后运行的；",
    "2. 确认端口是 8888；",
    "3. 确认没有 capture_raw_jsonl.py 或其他程序占用 8888；",
    "4. 如果 C++ 之前连接失败，需要重启 C++。",
)


@dataclass(frozen=True)
class DryRunCoreResult:
    total_pinch_samples: int
    total_valid_pinch_samples: int
    total_haptic_events: int


@dataclass
class ManusTcpLogState:
    client_connected_logged: bool = False
    first_frame_logged: bool = False


def load_dualtask_config(path: str | Path) -> dict[str, Any]:
    """Load a dual-task dry-run YAML config."""

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("dualtask_config.yaml requires PyYAML.") from exc
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("dualtask config must be an object.")
    return payload


def run_pinch_haptic_dry_run_core(
    samples: Iterable[PinchInputSample],
    *,
    calibration: PinchCalibrationResult,
    plan: HapticPlanConfig,
    logger: DualTaskLogger,
    sender: SimpleHapticSender | None = None,
    scheduler_config: HapticTrialSchedulerConfig | None = None,
    digit_onsets_ms: Iterable[float] | None = None,
) -> DryRunCoreResult:
    """Drive scheduler/sender/logging from parsed pinch samples."""

    haptic_sender = sender or SimpleHapticSender(session_id=logger.session_id)
    scheduler = HapticTrialScheduler(plan, scheduler_config)
    total_haptic_events = 0
    for sample in samples:
        total_haptic_events += _process_dry_run_sample(
            sample,
            calibration=calibration,
            scheduler=scheduler,
            logger=logger,
            sender=haptic_sender,
            digit_onsets_ms=digit_onsets_ms,
        )
    haptic_sender.write_csv(logger.paths.haptic_events_csv)
    return DryRunCoreResult(
        total_pinch_samples=logger.total_pinch_samples,
        total_valid_pinch_samples=logger.total_valid_pinch_samples,
        total_haptic_events=total_haptic_events,
    )


def run_live_pinch_haptic_dry_run(config_path: str | Path) -> Path:
    """Run the interactive live MANUS dry-run and return the session directory."""

    config = load_dualtask_config(config_path)
    session_config = _object_section(config, "session")
    manus_config = _object_section(config, "manus")
    pinch_config = _object_section(config, "pinch")
    calibration_config_payload = _object_section(config, "calibration")
    haptic_config = _object_section(config, "haptic")
    sync_config = _object_section(config, "sync")

    session_id = make_session_id(session_config.get("session_id_prefix", "pinch_haptic_dry_run"))
    logger = DualTaskLogger(
        session_id=session_id,
        output_root=session_config.get("output_root", "outputs"),
    )
    plan_path = Path(session_config.get("haptic_plan_config", "haptic_plan_config_example.yaml"))
    plan = load_haptic_plan_config(plan_path)
    parser = ManusOnlyPinchInput(
        ManusPinchInputConfig(
            thumb_node_id=pinch_config.get("thumb_node_id", 4),
            target_finger_node_id=pinch_config.get("target_finger_node_id", 14),
            require_tracker=bool(manus_config.get("require_tracker", False)),
        )
    )
    calibration_config = PinchCalibrationConfig(
        open_hand_duration_s=calibration_config_payload.get("open_hand_duration_s", 3.0),
        pinch_hand_duration_s=calibration_config_payload.get("pinch_hand_duration_s", 3.0),
        threshold_ratio=calibration_config_payload.get("threshold_ratio", 0.65),
        min_valid_frames=calibration_config_payload.get("min_valid_frames", 30),
    )
    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(
            vibration_enabled=bool(haptic_config.get("vibration_enabled", False)),
            matrix_enabled=bool(haptic_config.get("matrix_enabled", False)),
            visual_text_cue_enabled=bool(haptic_config.get("visual_text_cue_enabled", False)),
        ),
        session_id=session_id,
    )
    scheduler_config = HapticTrialSchedulerConfig(
        avoid_haptic_on_digit_onset=bool(sync_config.get("avoid_haptic_on_digit_onset", False)),
        digit_onset_guard_ms=sync_config.get("digit_onset_guard_ms", 150),
        max_haptic_delay_ms=sync_config.get("max_haptic_delay_ms", 500),
        if_cannot_avoid=str(sync_config.get("if_cannot_avoid", "log_warning_and_send")),
    )

    warnings: list[str] = []
    errors: list[str] = []
    start_wall = _now_iso()
    server = _make_manus_tcp_server(manus_config)
    manus_tcp_log_state = ManusTcpLogState()
    try:
        print(f"Session: {session_id}")
        print(f"Output: {logger.session_dir}")
        server.start()
        _log_manus_listening(server)
        print("Waiting for manus_vive_com combined JSON TCP client...")
        _wait_for_manus_client(
            server,
            timeout_s=MANUS_CLIENT_WAIT_TIMEOUT_S,
            log_state=manus_tcp_log_state,
        )

        input("Open hand calibration: press Enter, then keep hand open...")
        open_samples = _collect_live_samples(
            server,
            parser,
            logger,
            session_id=session_id,
            duration_s=calibration_config.open_hand_duration_s,
            save_raw_frames=bool(manus_config.get("save_raw_frames", True)),
            tcp_log_state=manus_tcp_log_state,
        )
        input("Pinch calibration: press Enter, then pinch thumb and target finger...")
        pinch_samples = _collect_live_samples(
            server,
            parser,
            logger,
            session_id=session_id,
            duration_s=calibration_config.pinch_hand_duration_s,
            save_raw_frames=bool(manus_config.get("save_raw_frames", True)),
            tcp_log_state=manus_tcp_log_state,
        )
        calibration = calibrate_from_samples(
            open_samples,
            pinch_samples,
            config=calibration_config,
            thumb_node_id=pinch_config.get("thumb_node_id", 4),
            target_finger_node_id=pinch_config.get("target_finger_node_id", 14),
        )
        logger.write_calibration(calibration)
        print(f"Calibration threshold_a={calibration.threshold_a:.6f}")
        input("Calibration complete. Press Enter to start dry-run...")

        result = _run_live_formal_phase(
            server,
            parser,
            logger,
            calibration=calibration,
            plan=plan,
            sender=sender,
            scheduler_config=scheduler_config,
            session_id=session_id,
            duration_s=float(session_config.get("duration_s", 60)),
            save_raw_frames=bool(manus_config.get("save_raw_frames", True)),
            tcp_log_state=manus_tcp_log_state,
        )
        total_haptic_events = result.total_haptic_events
    except Exception as exc:
        errors.append(str(exc))
        raise
    finally:
        server.stop("dry_run_finished")
        server.join(timeout=1.0)
        end_wall = _now_iso()
        logger.write_summary(
            {
                "session_id": session_id,
                "participant_id": session_config.get("participant_id", ""),
                "condition_id": session_config.get("condition_id", ""),
                "config_path": str(config_path),
                "haptic_plan_config_path": str(plan_path),
                "start_wall_time_iso": start_wall,
                "end_wall_time_iso": end_wall,
                "duration_s": session_config.get("duration_s", 60),
                "output_files": logger.paths.to_dict(),
                "total_haptic_events": len(sender.records),
                "warnings": warnings,
                "errors": errors,
            }
        )
    print(f"Dry-run complete. Haptic events: {total_haptic_events}")
    return logger.session_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="MANUS pinch+haptic disabled dry-run.")
    parser.add_argument("--config", default="dualtask_config.yaml")
    args = parser.parse_args()
    run_live_pinch_haptic_dry_run(args.config)
    return 0


def _advance_scheduler_for_sample(
    scheduler: HapticTrialScheduler,
    *,
    sample: PinchInputSample,
    zone: str,
    digit_onsets_ms: Iterable[float] | None,
) -> list[Any]:
    events: list[Any] = []
    now_ms = float(getattr(sample, "monotonic_ms"))
    # Drain immediate pending events at this sample time, including zero-delay plans.
    for _ in range(64):
        emitted = scheduler.update(
            zone=zone,
            now_ms=now_ms,
            pinch_distance=getattr(sample, "pinch_distance", None),
            frame_index=getattr(sample, "frame_index", None),
            digit_onsets_ms=digit_onsets_ms,
        )
        events.extend(emitted)
        pending_onset = _pending_onset_ms(scheduler)
        if pending_onset is None or pending_onset > now_ms:
            break
    return events


def _process_dry_run_sample(
    sample: PinchInputSample,
    *,
    calibration: PinchCalibrationResult,
    scheduler: HapticTrialScheduler,
    logger: DualTaskLogger,
    sender: SimpleHapticSender,
    digit_onsets_ms: Iterable[float] | None,
) -> int:
    zone = classify_pinch_zone(getattr(sample, "pinch_distance", None), calibration)
    logger.write_pinch_sample(sample, calibration=calibration, zone=zone)
    events = _advance_scheduler_for_sample(
        scheduler,
        sample=sample,
        zone=zone,
        digit_onsets_ms=digit_onsets_ms,
    )
    for event in events:
        sender.record_scheduled_event(event)
    return len(events)


def _run_live_formal_phase(
    server: LiveRawStreamServer,
    parser: ManusOnlyPinchInput,
    logger: DualTaskLogger,
    *,
    calibration: PinchCalibrationResult,
    plan: HapticPlanConfig,
    sender: SimpleHapticSender,
    scheduler_config: HapticTrialSchedulerConfig,
    session_id: str,
    duration_s: float,
    save_raw_frames: bool,
    tcp_log_state: ManusTcpLogState | None = None,
) -> DryRunCoreResult:
    scheduler = HapticTrialScheduler(plan, scheduler_config)
    deadline = time.monotonic() + float(duration_s)
    total_haptic_events = 0
    while time.monotonic() < deadline:
        frame = _get_manus_frame(server, timeout=0.1, log_state=tcp_log_state)
        if frame is None:
            continue
        raw = _raw_from_live_frame(frame)
        if save_raw_frames:
            logger.write_raw_frame(raw)
        sample = parser.parse_sample(frame, session_id=session_id)
        total_haptic_events += _process_dry_run_sample(
            sample,
            calibration=calibration,
            scheduler=scheduler,
            logger=logger,
            sender=sender,
            digit_onsets_ms=None,
        )
    sender.write_csv(logger.paths.haptic_events_csv)
    return DryRunCoreResult(
        total_pinch_samples=logger.total_pinch_samples,
        total_valid_pinch_samples=logger.total_valid_pinch_samples,
        total_haptic_events=total_haptic_events,
    )


def _collect_live_samples(
    server: LiveRawStreamServer,
    parser: ManusOnlyPinchInput,
    logger: DualTaskLogger,
    *,
    session_id: str,
    duration_s: float,
    save_raw_frames: bool,
    tcp_log_state: ManusTcpLogState | None = None,
) -> list[PinchInputSample]:
    deadline = time.monotonic() + float(duration_s)
    samples: list[PinchInputSample] = []
    while time.monotonic() < deadline:
        frame = _get_manus_frame(server, timeout=0.1, log_state=tcp_log_state)
        if frame is None:
            continue
        raw = _raw_from_live_frame(frame)
        if save_raw_frames:
            logger.write_raw_frame(raw)
        samples.append(parser.parse_sample(frame, session_id=session_id))
    return samples


def _make_manus_tcp_server(manus_config: dict[str, Any]) -> LiveRawStreamServer:
    """Create the MANUS newline-JSON TCP server used by the dry-run."""

    return LiveRawStreamServer(
        host=str(manus_config.get("tcp_host", DEFAULT_MANUS_TCP_HOST)),
        port=int(manus_config.get("tcp_port", DEFAULT_MANUS_TCP_PORT)),
    )


def _log_manus_listening(
    server: LiveRawStreamServer,
    *,
    print_fn: Any = print,
) -> None:
    print_fn(f"[MANUS TCP] listening on {server.host}:{server.port}")


def _wait_for_manus_client(
    server: LiveRawStreamServer,
    *,
    timeout_s: float = MANUS_CLIENT_WAIT_TIMEOUT_S,
    log_state: ManusTcpLogState | None = None,
    print_fn: Any = print,
    poll_s: float = 0.05,
) -> bool:
    """Wait briefly for the C++ TCP client and print operator-facing hints."""

    state = log_state or ManusTcpLogState()
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while time.monotonic() < deadline:
        if _log_manus_client_connected_if_needed(server, state, print_fn=print_fn):
            return True
        time.sleep(max(0.001, float(poll_s)))
    if _log_manus_client_connected_if_needed(server, state, print_fn=print_fn):
        return True
    print_fn("[MANUS TCP] no client connected after 5 seconds.")
    for hint in MANUS_CLIENT_HINTS:
        print_fn(f"[MANUS TCP] {hint}")
    return False


def _get_manus_frame(
    server: LiveRawStreamServer,
    *,
    timeout: float | None = 0.1,
    log_state: ManusTcpLogState | None = None,
    print_fn: Any = print,
) -> LiveRawFrame | None:
    """Read one frame while emitting connection and first-frame diagnostics."""

    state = log_state or ManusTcpLogState()
    _log_manus_client_connected_if_needed(server, state, print_fn=print_fn)
    frame = server.get_frame(timeout=timeout)
    _log_manus_client_connected_if_needed(server, state, print_fn=print_fn)
    if frame is not None and not state.first_frame_logged:
        print_fn("[MANUS TCP] first frame received")
        state.first_frame_logged = True
    return frame


def _log_manus_client_connected_if_needed(
    server: LiveRawStreamServer,
    log_state: ManusTcpLogState,
    *,
    print_fn: Any = print,
) -> bool:
    connected = bool(server.stats_snapshot().client_connected)
    if connected and not log_state.client_connected_logged:
        print_fn("[MANUS TCP] client connected")
        log_state.client_connected_logged = True
    return connected


def _raw_from_live_frame(frame: LiveRawFrame | Any) -> Any:
    return getattr(frame, "raw_frame", frame)


def _pending_onset_ms(scheduler: HapticTrialScheduler) -> float | None:
    pending = getattr(scheduler, "_pending", None)
    adjustment = getattr(pending, "adjustment", None)
    value = getattr(adjustment, "adjusted_onset_ms", None)
    return float(value) if value is not None else None


def _object_section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} section must be an object.")
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
