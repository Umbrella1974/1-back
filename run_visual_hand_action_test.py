"""Visual semantic cue -> MANUS hand-action recording and offline analysis."""

from __future__ import annotations

import argparse
import csv
import random
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from analyze_cue_response_metrics import analyze_root
from dualtask_logger import DualTaskLogger, make_session_id
from manus_pinch_input import ManusOnlyPinchInput, ManusPinchInputConfig
from pinch_calibration import PinchCalibrationConfig, PinchCalibrationResult, classify_pinch_zone
from run_pinch_haptic_dry_run import (
    MANUS_CLIENT_WAIT_TIMEOUT_S,
    ManusTcpLogState,
    _get_manus_frame,
    _log_manus_listening,
    _make_manus_tcp_server,
    _object_section,
    _raw_from_live_frame,
    _wait_for_manus_client,
    load_dualtask_config,
)
from run_pinch_haptic_1back import (
    CalibrationBundle,
    _active_calibration_id,
    _calibration_reuse_block_reason,
    _calibration_reuse_config_from_dict,
    _calibration_summary_fields,
    _load_calibration_bundle,
    _run_live_pinch_calibration,
    _run_live_wrist_rotation_calibration,
    _save_calibration_bundle,
    _should_enter_formal_phase,
)
from simple_haptic_sender import SimpleHapticSender, SimpleHapticSenderConfig
from wrist_rotation import (
    WristRotationCalibrationResult,
    WristRotationConfig,
    classify_wrist_rotation_frame,
    wrist_rotation_config_from_dict,
)


DEFAULT_MIDDLE_EVENTS = ("slip", "up", "right", "left", "down")
CUE_LABELS_ZH = {
    "contact": "接触",
    "slip": "滑动",
    "up": "上",
    "right": "右",
    "left": "左",
    "down": "下",
    "release": "释放",
}


@dataclass(frozen=True)
class VisualActionTestConfig:
    cue_plan_id: str = "visual-action-1"
    episode_count: int = 3
    middle_events_per_episode: tuple[int, int] = (3, 6)
    cue_duration_ms: int = 1000
    fixation_ms: int = 500
    inter_cue_interval_ms: tuple[int, int] = (3000, 5000)
    random_seed: int | None = None
    middle_events: tuple[str, ...] = DEFAULT_MIDDLE_EVENTS
    run_analysis: bool = True
    analysis_output_root: Path = Path("analysis_outputs")


@dataclass(frozen=True)
class VisualActionIssue:
    event_position: int
    episode_index: int
    episode_position: int
    event_name: str
    category: str
    detected_response: str
    reason: str


@dataclass(frozen=True)
class VisualActionResult:
    total_count: int
    passed_count: int
    issues: tuple[VisualActionIssue, ...]


def run_visual_hand_action_test(config_path: str | Path) -> Path:
    """Run the visual cue action test and return the session directory."""

    config_path = Path(config_path)
    config = load_dualtask_config(config_path)
    session_config = _object_section(config, "session")
    manus_config = _object_section(config, "manus")
    pinch_config = _object_section(config, "pinch")
    visual_config = _visual_action_test_config_from_dict(
        config.get("visual_action_test"),
        base_dir=config_path.resolve().parent,
    )
    wrist_rotation_config = wrist_rotation_config_from_dict(config.get("wrist_rotation"))
    calibration_config = _pinch_calibration_config_from_dict(
        _object_section(config, "calibration")
    )
    reuse_config = _calibration_reuse_config_from_dict(
        config.get("calibration_reuse"),
        config_path=config_path,
    )
    seed = (
        int(visual_config.random_seed)
        if visual_config.random_seed is not None
        else int(session_config.get("run_seed", session_config.get("random_seed", 12345)))
    )
    session_id = make_session_id(
        session_config.get("session_id_prefix", "visual_hand_action_test")
    )
    logger = DualTaskLogger(
        session_id=session_id,
        output_root=session_config.get("output_root", "outputs"),
    )
    cue_events = _visual_events(visual_config.middle_events)
    trial_events = _randomized_visual_trials(
        cue_events,
        episode_count=visual_config.episode_count,
        middle_events_per_episode=visual_config.middle_events_per_episode,
        seed=seed,
    )
    parser = ManusOnlyPinchInput(
        ManusPinchInputConfig(
            thumb_node_id=pinch_config.get("thumb_node_id", 4),
            target_finger_node_id=pinch_config.get("target_finger_node_id", 14),
            require_tracker=bool(manus_config.get("require_tracker", False)),
        )
    )
    sender = SimpleHapticSender(
        SimpleHapticSenderConfig(
            vibration_enabled=False,
            matrix_enabled=False,
            visual_text_cue_enabled=True,
            disabled_mode=True,
            console_logging_enabled=False,
        ),
        session_id=session_id,
    )
    server = _make_manus_tcp_server(manus_config)
    manus_tcp_log_state = ManusTcpLogState()
    warnings: list[str] = []
    errors: list[str] = []
    calibration: PinchCalibrationResult | None = None
    wrist_calibration: WristRotationCalibrationResult | None = None
    calibration_bundle: CalibrationBundle | None = None
    calibration_loaded = False
    saved_calibration_path = ""
    analysis_outputs: dict[str, str] = {}
    start_wall = _now_iso()
    display: _VisualCueDisplay | None = None

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

        if reuse_config.calibration_in is not None:
            calibration_bundle = _load_calibration_bundle(reuse_config.calibration_in)
            block_reason = _calibration_reuse_block_reason(
                calibration_bundle.pinch_calibration
            )
            if block_reason:
                warnings.append("loaded_calibration_blocked:" + block_reason)
                print("[CALIBRATION] loaded calibration cannot be reused: " + block_reason)
            else:
                calibration = calibration_bundle.pinch_calibration
                wrist_calibration = calibration_bundle.wrist_rotation_calibration
                calibration_loaded = True
                print("[CALIBRATION] loaded calibration reused.")

        if calibration is None:
            calibration = _run_live_pinch_calibration(
                server,
                parser,
                logger,
                calibration_config=calibration_config,
                pinch_config=pinch_config,
                manus_config=manus_config,
                session_id=session_id,
                tcp_log_state=manus_tcp_log_state,
            )

        logger.write_calibration(calibration)
        if not _should_enter_formal_phase(calibration):
            raise RuntimeError(
                "pinch calibration failed: "
                + str(calibration.calibration_failure_reason or calibration.full_calibration_qc_reasons)
            )

        if wrist_rotation_config.enabled and wrist_calibration is None:
            wrist_calibration = _run_live_wrist_rotation_calibration(
                server,
                logger,
                config=wrist_rotation_config,
                session_id=session_id,
                save_raw_frames=bool(manus_config.get("save_raw_frames", True)),
                tcp_log_state=manus_tcp_log_state,
            )
        if wrist_rotation_config.enabled and wrist_calibration is not None:
            logger.write_wrist_rotation_calibration(wrist_calibration)
            if not wrist_calibration.calibration_passed and wrist_rotation_config.required:
                raise RuntimeError(
                    "wrist rotation calibration failed: "
                    + str(wrist_calibration.failure_reason)
                )
        if not calibration_loaded:
            saved = _save_calibration_bundle(
                calibration,
                wrist_calibration,
                reuse_config=reuse_config,
                fallback_base_path=reuse_config.calibration_out,
            )
            saved_calibration_path = str(saved) if saved is not None else ""

        display = _VisualCueDisplay()
        display.show_text_and_wait("按 Enter 开始\n根据屏幕提示做对应手部动作", wait_key_name="enter")
        _run_visual_trials(
            server,
            parser,
            logger,
            sender,
            display,
            trial_events,
            calibration=calibration,
            wrist_calibration=wrist_calibration,
            wrist_rotation_config=wrist_rotation_config,
            session_id=session_id,
            save_raw_frames=bool(manus_config.get("save_raw_frames", True)),
            tcp_log_state=manus_tcp_log_state,
            visual_config=visual_config,
            random_seed=seed,
        )
        sender.write_csv(logger.paths.haptic_events_csv)
        logger.write_nback_events(())

        logger.write_summary(
            _summary_payload(
                session_id=session_id,
                config_path=config_path,
                seed=seed,
                session_config=session_config,
                visual_config=visual_config,
                calibration=calibration,
                calibration_bundle=calibration_bundle,
                reuse_config=reuse_config,
                saved_calibration_path=saved_calibration_path,
                calibration_loaded=calibration_loaded,
                logger=logger,
                sender=sender,
                start_wall=start_wall,
                end_wall=_now_iso(),
                warnings=warnings,
                errors=errors,
                analysis_outputs=analysis_outputs,
            )
        )
        if visual_config.run_analysis:
            analysis_dir = visual_config.analysis_output_root / session_id
            metrics, wrist, up, summary = analyze_root(
                logger.session_dir,
                output_dir=analysis_dir,
            )
            analysis_outputs = {
                "cue_response_metrics_csv": str(metrics),
                "wrist_neutral_reclass_csv": str(wrist),
                "up_diagnostics_csv": str(up),
                "cue_response_summary_json": str(summary),
                "cue_response_diagnostics_csv": str(metrics.parent / "cue_response_diagnostics.csv"),
            }
            logger.write_summary(
                _summary_payload(
                    session_id=session_id,
                    config_path=config_path,
                    seed=seed,
                    session_config=session_config,
                    visual_config=visual_config,
                    calibration=calibration,
                    calibration_bundle=calibration_bundle,
                    reuse_config=reuse_config,
                    saved_calibration_path=saved_calibration_path,
                    calibration_loaded=calibration_loaded,
                    logger=logger,
                    sender=sender,
                    start_wall=start_wall,
                    end_wall=_now_iso(),
                    warnings=warnings,
                    errors=errors,
                    analysis_outputs=analysis_outputs,
                )
            )
            result = _read_visual_action_result(metrics, trial_events)
            print(f"[ANALYSIS] wrote {metrics}")
            print(f"[ANALYSIS] wrote {summary}")
            _print_visual_action_result(result)
            display.show_result(result)
    except Exception as exc:
        errors.append(str(exc))
        raise
    finally:
        if display is not None:
            display.close()
        sender.write_csv(logger.paths.haptic_events_csv)
        server.stop("visual_action_test_finished")
        server.join(timeout=1.0)

    print(f"Visual hand action test complete. Events: {len(sender.records)}")
    return logger.session_dir


def _visual_action_test_config_from_dict(
    payload: Any,
    *,
    base_dir: Path,
) -> VisualActionTestConfig:
    value = payload or {}
    if not isinstance(value, dict):
        raise ValueError("visual_action_test section must be an object.")
    interval = value.get("inter_cue_interval_ms", (3000, 5000))
    if not isinstance(interval, (list, tuple)) or len(interval) != 2:
        raise ValueError("visual_action_test.inter_cue_interval_ms must have two items.")
    middle_count = value.get("middle_events_per_episode", (3, 6))
    if not isinstance(middle_count, (list, tuple)) or len(middle_count) != 2:
        raise ValueError(
            "visual_action_test.middle_events_per_episode must have two items."
        )
    middle_events = value.get("middle_events")
    if middle_events is None:
        legacy_events = value.get("events", DEFAULT_MIDDLE_EVENTS)
        middle_events = [
            item
            for item in legacy_events
            if str(item).strip().lower() not in {"contact", "release"}
        ]
    if not isinstance(middle_events, (list, tuple)):
        raise ValueError("visual_action_test.middle_events must be a list.")
    analysis_root = Path(value.get("analysis_output_root", "analysis_outputs"))
    if not analysis_root.is_absolute():
        analysis_root = base_dir / analysis_root
    seed_value = value.get("random_seed")
    return VisualActionTestConfig(
        cue_plan_id=str(value.get("cue_plan_id", "visual-action-1") or "visual-action-1"),
        episode_count=_positive_int(
            value.get("episode_count", value.get("repetitions_per_event", 3)),
            "visual_action_test.episode_count",
        ),
        middle_events_per_episode=(
            _positive_int(
                middle_count[0],
                "visual_action_test.middle_events_per_episode[0]",
            ),
            _positive_int(
                middle_count[1],
                "visual_action_test.middle_events_per_episode[1]",
            ),
        ),
        cue_duration_ms=_positive_int(
            value.get("cue_duration_ms", 1000),
            "visual_action_test.cue_duration_ms",
        ),
        fixation_ms=_non_negative_int(
            value.get("fixation_ms", 500),
            "visual_action_test.fixation_ms",
        ),
        inter_cue_interval_ms=(
            _non_negative_int(interval[0], "visual_action_test.inter_cue_interval_ms[0]"),
            _non_negative_int(interval[1], "visual_action_test.inter_cue_interval_ms[1]"),
        ),
        random_seed=int(seed_value) if seed_value not in (None, "") else None,
        middle_events=tuple(
            str(item).strip().lower()
            for item in middle_events
            if str(item).strip()
        ),
        run_analysis=bool(value.get("run_analysis", True)),
        analysis_output_root=analysis_root,
    )


def _pinch_calibration_config_from_dict(payload: dict[str, Any]) -> PinchCalibrationConfig:
    return PinchCalibrationConfig(
        open_hand_duration_s=payload.get("open_hand_duration_s", 3.0),
        contact_hand_duration_s=payload.get("contact_hand_duration_s", 3.0),
        pinch_hand_duration_s=payload.get("pinch_hand_duration_s", 3.0),
        threshold_ratio=payload.get("threshold_ratio", 0.65),
        min_valid_frames=payload.get("min_valid_frames", 30),
        min_distance_range=payload.get("min_distance_range", 0.02),
        min_distance_range_ratio=payload.get("min_distance_range_ratio", 0.15),
        repetition_count=payload.get("repetition_count", 3),
        stability_window_s=payload.get("stability_window_s", 0.5),
        stability_dwell_s=payload.get("stability_dwell_s", 0.4),
        stable_recording_duration_s=payload.get("stable_recording_duration_s", 1.5),
        quick_check_recording_duration_s=payload.get("quick_check_recording_duration_s", 0.75),
        stability_valid_ratio_min=payload.get("stability_valid_ratio_min", 0.8),
        stability_mad_max=payload.get("stability_mad_max", 0.004),
        stability_range_max=payload.get("stability_range_max", 0.015),
        stability_timeout_s=payload.get("stability_timeout_s", 8.0),
        max_acquisition_attempts=payload.get("max_acquisition_attempts", 3),
        min_state_gap_ratio=payload.get("min_state_gap_ratio", 0.10),
        max_contact_rep_position_range=payload.get("max_contact_rep_position_range", 0.25),
        max_state_rep_median_range_ratio=payload.get("max_state_rep_median_range_ratio", 0.20),
        contact_position_min=payload.get("contact_position_min"),
        contact_position_max=payload.get("contact_position_max"),
    )


def _visual_events(requested_names: Iterable[str]) -> tuple[Any, ...]:
    result = []
    for name in requested_names:
        key = str(name).strip().lower()
        if not key:
            continue
        if key not in DEFAULT_MIDDLE_EVENTS:
            raise ValueError(f"unsupported middle visual event: {key}")
        result.append(_display_only_event(key))
    if not result:
        raise ValueError("visual action test needs at least one event.")
    return tuple(result)


def _display_only_event(name: str) -> Any:
    modality = "matrix" if name in {"up", "right", "left", "down"} else "vibration"
    return SimpleNamespace(
        name=name,
        modality=modality,
        command_label=None,
        command_id=None,
        channel_list=(),
        matrix_sequence=(),
        duration_ms=None,
        trigger_zone="",
        end_command_label=None,
        end_command_id=None,
    )


def _randomized_visual_trials(
    middle_events: tuple[Any, ...],
    *,
    episode_count: int,
    middle_events_per_episode: tuple[int, int],
    seed: int,
) -> tuple[Any, ...]:
    if not middle_events:
        raise ValueError("visual action test needs at least one middle event.")
    low, high = middle_events_per_episode
    if high < low:
        raise ValueError(
            "visual_action_test.middle_events_per_episode lower bound must be <= upper bound."
        )
    rng = random.Random(seed)
    trials: list[Any] = []
    for episode_index in range(1, int(episode_count) + 1):
        middle_count = rng.randint(low, high) if high > low else low
        names = ["contact"]
        names.extend(rng.choice(middle_events).name for _ in range(middle_count))
        names.append("release")
        for episode_position, name in enumerate(names, start=1):
            event = _display_only_event(name)
            event.visual_episode_index = episode_index
            event.visual_episode_position = episode_position
            trials.append(event)
    return tuple(trials)


def _run_visual_trials(
    server: Any,
    parser: ManusOnlyPinchInput,
    logger: DualTaskLogger,
    sender: SimpleHapticSender,
    display: "_VisualCueDisplay",
    trial_events: tuple[Any, ...],
    *,
    calibration: PinchCalibrationResult,
    wrist_calibration: WristRotationCalibrationResult | None,
    wrist_rotation_config: WristRotationConfig,
    session_id: str,
    save_raw_frames: bool,
    tcp_log_state: ManusTcpLogState,
    visual_config: VisualActionTestConfig,
    random_seed: int,
) -> None:
    rng = random.Random(random_seed)
    low, high = visual_config.inter_cue_interval_ms
    if high < low:
        raise ValueError("visual_action_test.inter_cue_interval_ms lower bound must be <= upper bound.")
    for index, event in enumerate(trial_events, start=1):
        display.draw_fixation()
        _record_until(
            server,
            parser,
            logger,
            display=display,
            calibration=calibration,
            wrist_calibration=wrist_calibration,
            wrist_rotation_config=wrist_rotation_config,
            session_id=session_id,
            save_raw_frames=save_raw_frames,
            tcp_log_state=tcp_log_state,
            deadline_ms=time.monotonic() * 1000.0 + visual_config.fixation_ms,
        )

        cue_onset_ms = time.monotonic() * 1000.0
        label = CUE_LABELS_ZH.get(str(event.name).lower(), str(event.name))
        display.draw_cue(label)
        sender.record_plan_event(
            event,
            haptic_trial_index=int(event.visual_episode_index) - 1,
            event_index=index - 1,
            sampled_duration_ms=visual_config.cue_duration_ms,
            event_end_monotonic_ms=cue_onset_ms + visual_config.cue_duration_ms,
            monotonic_ms=cue_onset_ms,
            actual_emit_ms=cue_onset_ms,
            planned_emit_trial_number=index,
            emit_trial_number=index,
            trial_gate_enabled=False,
            trial_gate_ignored=True,
            haptic_episode_completed=True,
            note="visual_screen_cue",
        )
        _record_until(
            server,
            parser,
            logger,
            display=display,
            calibration=calibration,
            wrist_calibration=wrist_calibration,
            wrist_rotation_config=wrist_rotation_config,
            session_id=session_id,
            save_raw_frames=save_raw_frames,
            tcp_log_state=tcp_log_state,
            deadline_ms=cue_onset_ms + visual_config.cue_duration_ms,
        )

        display.draw_blank()
        gap_ms = rng.randint(low, high) if high > low else low
        _record_until(
            server,
            parser,
            logger,
            display=display,
            calibration=calibration,
            wrist_calibration=wrist_calibration,
            wrist_rotation_config=wrist_rotation_config,
            session_id=session_id,
            save_raw_frames=save_raw_frames,
            tcp_log_state=tcp_log_state,
            deadline_ms=time.monotonic() * 1000.0 + gap_ms,
        )


def _record_until(
    server: Any,
    parser: ManusOnlyPinchInput,
    logger: DualTaskLogger,
    *,
    display: "_VisualCueDisplay",
    calibration: PinchCalibrationResult,
    wrist_calibration: WristRotationCalibrationResult | None,
    wrist_rotation_config: WristRotationConfig,
    session_id: str,
    save_raw_frames: bool,
    tcp_log_state: ManusTcpLogState,
    deadline_ms: float,
) -> None:
    while time.monotonic() * 1000.0 < float(deadline_ms):
        display.pump_events()
        frame = _get_manus_frame(server, timeout=0.0, log_state=tcp_log_state)
        while frame is not None:
            raw = _raw_from_live_frame(frame)
            if save_raw_frames:
                logger.write_raw_frame(raw)
            sample = parser.parse_sample(frame, session_id=session_id)
            zone = classify_pinch_zone(sample.pinch_distance, calibration)
            logger.write_pinch_sample(
                sample,
                calibration=calibration,
                zone=zone,
                phase="visual_action_test",
            )
            if wrist_rotation_config.enabled and wrist_calibration is not None:
                wrist_sample = classify_wrist_rotation_frame(
                    frame,
                    wrist_calibration,
                    session_id=session_id,
                )
                logger.write_wrist_rotation_sample(wrist_sample)
            frame = _get_manus_frame(server, timeout=0.0, log_state=tcp_log_state)
        display.tick(60)


def _summary_payload(
    *,
    session_id: str,
    config_path: Path,
    seed: int,
    session_config: dict[str, Any],
    visual_config: VisualActionTestConfig,
    calibration: PinchCalibrationResult | None,
    calibration_bundle: CalibrationBundle | None,
    reuse_config: Any,
    saved_calibration_path: str,
    calibration_loaded: bool,
    logger: DualTaskLogger,
    sender: SimpleHapticSender,
    start_wall: str,
    end_wall: str,
    warnings: list[str],
    errors: list[str],
    analysis_outputs: dict[str, str],
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "participant_id": session_config.get("participant_id", ""),
        "condition_id": session_config.get("condition_id", ""),
        "task_type": "visual_action_test",
        "nback_enabled": False,
        "config_path": str(config_path),
        "visual_cue_plan_id": visual_config.cue_plan_id,
        "haptic_plan_id": "",
        "visual_cue_random_seed": seed,
        "visual_action_test": {
            "cue_plan_id": visual_config.cue_plan_id,
            "episode_count": visual_config.episode_count,
            "middle_events": list(visual_config.middle_events),
            "middle_events_per_episode": list(
                visual_config.middle_events_per_episode
            ),
            "cue_duration_ms": visual_config.cue_duration_ms,
            "fixation_ms": visual_config.fixation_ms,
            "inter_cue_interval_ms": list(visual_config.inter_cue_interval_ms),
            "run_analysis": visual_config.run_analysis,
        },
        "calibration_loaded_from_bundle": calibration_loaded,
        "calibration_bundle_path": (
            str(calibration_bundle.path) if calibration_bundle is not None else ""
        ),
        "saved_calibration_path": saved_calibration_path,
        "active_calibration_id": _active_calibration_id(
            calibration_bundle=calibration_bundle,
            reuse_config=reuse_config,
            saved_path=saved_calibration_path,
            loaded=calibration_loaded,
        ),
        **_calibration_summary_fields(calibration),
        "start_wall_time_iso": start_wall,
        "end_wall_time_iso": end_wall,
        "duration_s": None,
        "output_files": logger.paths.to_dict(),
        "analysis_outputs": analysis_outputs,
        "total_visual_cue_events": len(sender.records),
        "total_haptic_events": 0,
        "visual_text_cue_enabled": True,
        "warnings": warnings,
        "errors": errors,
    }


def _read_visual_action_result(
    metrics_path: Path,
    trial_events: tuple[Any, ...],
) -> VisualActionResult:
    with Path(metrics_path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    issues: list[VisualActionIssue] = []
    for row_index, row in enumerate(rows, start=1):
        event_position = _int_or_default(row.get("event_position"), row_index)
        trial = (
            trial_events[event_position - 1]
            if 1 <= event_position <= len(trial_events)
            else None
        )
        episode_index = int(getattr(trial, "visual_episode_index", 0))
        episode_position = int(getattr(trial, "visual_episode_position", 0))
        issue = _visual_action_issue_from_metric(
            row,
            event_position=event_position,
            episode_index=episode_index,
            episode_position=episode_position,
        )
        if issue is not None:
            issues.append(issue)

    return VisualActionResult(
        total_count=len(rows),
        passed_count=len(rows) - len(issues),
        issues=tuple(issues),
    )


def _visual_action_issue_from_metric(
    row: dict[str, str],
    *,
    event_position: int,
    episode_index: int,
    episode_position: int,
) -> VisualActionIssue | None:
    event_name = str(row.get("event_name", "")).strip().lower()
    first_response = str(row.get("first_response", "")).strip().lower()
    first_correct = _csv_bool(row.get("first_response_correct"))
    eventual_correct = _csv_bool(row.get("eventual_correct"))
    trial_quality = str(row.get("trial_quality", "")).strip().lower()
    response_reason = str(row.get("response_quality_reason", "")).strip()
    cycle_quality = str(row.get("cycle_quality", "")).strip().lower()
    cycle_reason = str(row.get("cycle_quality_reason", "")).strip()
    quality_reason = str(row.get("quality_reason", "")).strip()

    category = ""
    reason = quality_reason or response_reason or cycle_reason
    if trial_quality.startswith("insufficient"):
        category = "数据不足"
    elif response_reason == "pre_existing_correct_action_at_cue":
        category = "未检测到新动作"
    elif first_correct is False:
        category = "首次动作不一致"
    elif eventual_correct is not True:
        category = "未判定" if not first_response else "动作不完整"
    elif cycle_quality.startswith("incomplete"):
        category = "动作不完整"
        reason = cycle_reason or reason

    if not category:
        return None
    return VisualActionIssue(
        event_position=event_position,
        episode_index=episode_index,
        episode_position=episode_position,
        event_name=event_name,
        category=category,
        detected_response=first_response,
        reason=_result_reason_zh(reason),
    )


def _visual_action_result_pages(
    result: VisualActionResult,
    *,
    issues_per_page: int = 8,
) -> tuple[tuple[str, ...], ...]:
    header = (
        "动作判定完成",
        f"总计 {result.total_count} 项  通过 {result.passed_count} 项  需检查 {len(result.issues)} 项",
        "",
    )
    if not result.issues:
        return (header + ("所有动作均与语义一致", "", "按 Enter 结束"),)

    issue_lines = [_visual_action_issue_line(issue) for issue in result.issues]
    chunks = [
        issue_lines[index : index + issues_per_page]
        for index in range(0, len(issue_lines), issues_per_page)
    ]
    pages: list[tuple[str, ...]] = []
    for page_index, chunk in enumerate(chunks, start=1):
        footer = (
            "",
            f"第 {page_index}/{len(chunks)} 页  左右键或空格翻页  Enter 结束",
        )
        pages.append(header + tuple(chunk) + footer)
    return tuple(pages)


def _visual_action_issue_line(issue: VisualActionIssue) -> str:
    location = (
        f"第{issue.episode_index}组第{issue.episode_position}项"
        if issue.episode_index and issue.episode_position
        else f"第{issue.event_position}项"
    )
    expected = CUE_LABELS_ZH.get(issue.event_name, issue.event_name)
    detected = _response_label_zh(issue.detected_response)
    detail = f"，检测到{detected}" if detected else ""
    reason = f"（{issue.reason}）" if issue.reason else ""
    return f"{location} {expected}：{issue.category}{detail}{reason}"


def _print_visual_action_result(result: VisualActionResult) -> None:
    print(
        "[RESULT] "
        f"total={result.total_count} passed={result.passed_count} issues={len(result.issues)}"
    )
    for issue in result.issues:
        print("[RESULT] " + _visual_action_issue_line(issue))


def _response_label_zh(value: str) -> str:
    labels = {
        **CUE_LABELS_ZH,
        "closing": "闭合",
        "opening": "张开",
        "pinch": "捏合",
        "neutral": "中立",
    }
    return labels.get(str(value).strip().lower(), str(value).strip())


def _result_reason_zh(value: str) -> str:
    reasons = {
        "missing_onset_or_wrist_timeseries": "缺少手腕数据",
        "missing_onset_or_pinch_timeseries": "缺少捏合数据",
        "too_few_baseline_samples": "提示前数据不足",
        "too_few_response_samples": "响应期数据不足",
        "pre_existing_correct_action_at_cue": "提示出现时已经处于该方向",
        "no_stable_wrist_action_before_next_cue": "下一提示前没有稳定方向动作",
        "no_correct_wrist_action_before_next_cue": "下一提示前没有正确方向动作",
        "neutral_return_not_detected_before_next_cue": "下一提示前没有检测到回位",
        "no_correct_pinch_direction_before_next_cue": "下一提示前没有正确捏合变化",
        "no_stable_closure_increase_before_next_cue": "没有检测到稳定捏合",
        "no_stable_reopening_before_next_cue": "没有检测到松回",
        "no_stable_contact_reference_return_before_next_cue": "没有回到接触状态",
        "no_stable_target_state_before_next_cue": "没有进入目标状态",
        "baseline_closure_too_high_to_detect_extra_pinch": "提示前已捏合过紧",
        "contact_reference_not_available": "接触参考不可用",
    }
    return reasons.get(str(value).strip(), str(value).strip())


def _csv_bool(value: Any) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return int(default)


class _VisualCueDisplay:
    def __init__(self) -> None:
        import config as nback_defaults
        import pygame

        self.pygame = pygame
        self.config = nback_defaults
        pygame.init()
        self.screen = pygame.display.set_mode(
            (nback_defaults.SCREEN_WIDTH, nback_defaults.SCREEN_HEIGHT)
        )
        pygame.display.set_caption("Visual Hand Action Test")
        self.clock = pygame.time.Clock()
        self.font_cue = _load_font_safe(
            pygame,
            nback_defaults.FONT_SIZE_STIMULUS,
            is_chinese=True,
        )
        self.font_instruction = _load_font_safe(
            pygame,
            nback_defaults.FONT_SIZE_INSTRUCTION,
            is_chinese=True,
        )
        self.font_result = _load_font_safe(pygame, 26, is_chinese=True)

    def show_text_and_wait(self, text: str, *, wait_key_name: str) -> None:
        self._draw_centered_lines(text, self.font_instruction)
        target_key = _pygame_key_constant(self.pygame, wait_key_name)
        waiting = True
        while waiting:
            for event in self.pygame.event.get():
                if event.type == self.pygame.QUIT:
                    raise KeyboardInterrupt("pygame window closed")
                if event.type == self.pygame.KEYDOWN:
                    if event.key == self.pygame.K_ESCAPE:
                        raise KeyboardInterrupt("escape pressed")
                    if event.key == target_key:
                        waiting = False
            self.clock.tick(60)

    def draw_fixation(self) -> None:
        self._draw_centered_text("+", self.font_instruction)

    def draw_cue(self, label: str) -> None:
        self._draw_centered_text(str(label), self.font_cue)

    def draw_blank(self) -> None:
        self.screen.fill(self.config.BACKGROUND_COLOR)
        self.pygame.display.flip()

    def show_result(self, result: VisualActionResult) -> None:
        pages = _visual_action_result_pages(result)
        page_index = 0
        while True:
            self._draw_centered_lines("\n".join(pages[page_index]), self.font_result)
            for event in self.pygame.event.get():
                if event.type == self.pygame.QUIT:
                    return
                if event.type != self.pygame.KEYDOWN:
                    continue
                if event.key in {self.pygame.K_ESCAPE, self.pygame.K_RETURN}:
                    return
                if event.key in {self.pygame.K_RIGHT, self.pygame.K_SPACE}:
                    page_index = min(len(pages) - 1, page_index + 1)
                elif event.key == self.pygame.K_LEFT:
                    page_index = max(0, page_index - 1)
            self.clock.tick(60)

    def pump_events(self) -> None:
        for event in self.pygame.event.get():
            if event.type == self.pygame.QUIT:
                raise KeyboardInterrupt("pygame window closed")
            if event.type == self.pygame.KEYDOWN and event.key == self.pygame.K_ESCAPE:
                raise KeyboardInterrupt("escape pressed")

    def tick(self, fps: int) -> None:
        self.clock.tick(fps)

    def close(self) -> None:
        self.pygame.quit()

    def _draw_centered_lines(self, text: str, font: Any) -> None:
        self.screen.fill(self.config.BACKGROUND_COLOR)
        lines = str(text).split("\n")
        y_offset = self.config.SCREEN_HEIGHT // 2 - (len(lines) * font.get_height() // 2)
        for line in lines:
            surface = font.render(line, True, self.config.TEXT_COLOR)
            rect = surface.get_rect(center=(self.config.SCREEN_WIDTH // 2, y_offset))
            self.screen.blit(surface, rect)
            y_offset += font.get_height() + 10
        self.pygame.display.flip()

    def _draw_centered_text(self, text: str, font: Any) -> None:
        self.screen.fill(self.config.BACKGROUND_COLOR)
        surface = font.render(str(text), True, self.config.TEXT_COLOR)
        rect = surface.get_rect(
            center=(self.config.SCREEN_WIDTH // 2, self.config.SCREEN_HEIGHT // 2)
        )
        self.screen.blit(surface, rect)
        self.pygame.display.flip()


def _load_font_safe(pygame: Any, size: int, *, is_chinese: bool) -> Any:
    if not is_chinese:
        return pygame.font.Font(None, size)
    try:
        import config as nback_defaults

        font_path = getattr(nback_defaults, "FONT_PATH", "")
        if font_path and Path(font_path).exists():
            return pygame.font.Font(font_path, size)
        font_name = getattr(nback_defaults, "CHINESE_FONT_NAME", "")
        if font_name:
            return pygame.font.SysFont(font_name, size)
    except Exception:
        pass
    return pygame.font.Font(None, size)


def _pygame_key_constant(pygame: Any, key_name: str) -> int:
    key = str(key_name).strip().lower()
    key = {"enter": "return", "esc": "escape", "spacebar": "space"}.get(key, key)
    for constant_name in (f"K_{key}", f"K_{key.upper()}"):
        if hasattr(pygame, constant_name):
            return int(getattr(pygame, constant_name))
    raise ValueError(f"unsupported pygame key name: {key_name}")


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer.")
    result = int(value)
    if result <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return result


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative integer.")
    result = int(value)
    if result < 0:
        raise ValueError(f"{name} must be a non-negative integer.")
    return result


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Show randomized semantic cues, record MANUS hand actions, and analyze responses."
    )
    parser.add_argument("--config", default="visual_hand_action_test.yaml")
    args = parser.parse_args()
    run_visual_hand_action_test(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
