"""MANUS pinch + disabled haptic scheduler + 1-back dual-task runner."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dualtask_logger import DualTaskLogger, make_session_id
from haptic_plan_config import (
    HapticPlanConfig,
    haptic_defaults_from_dict,
    load_haptic_plan_config,
)
from haptic_trial_scheduler import HapticTrialScheduler, HapticTrialSchedulerConfig
from manus_pinch_input import ManusOnlyPinchInput, ManusPinchInputConfig, PinchInputSample
from nback_dualtask_runner import (
    NBACK_PHASE_BLANK,
    NBACK_PHASE_COMPLETE,
    NBACK_PHASE_FIXATION,
    NBACK_PHASE_STIMULUS,
    NBackConfig,
    NBackTick,
    NBackTimeline,
)
from pinch_calibration import (
    PinchCalibrationConfig,
    PinchCalibrationResult,
    calibrate_from_samples,
    classify_pinch_zone,
)
from run_pinch_haptic_dry_run import (
    MANUS_CLIENT_WAIT_TIMEOUT_S,
    ManusTcpLogState,
    _collect_live_samples,
    _get_manus_frame,
    _log_manus_listening,
    _make_manus_tcp_server,
    _object_section,
    _pending_onset_ms,
    _raw_from_live_frame,
    _wait_for_manus_client,
    load_dualtask_config,
)
from simple_haptic_sender import SimpleHapticSender, SimpleHapticSenderConfig
from vendor_exp2_abc.live_raw_stream import LiveRawStreamServer
from wrist_rotation import (
    WristRotationCalibrationResult,
    WristRotationConfig,
    calibrate_wrist_rotation,
    classify_wrist_rotation_frame,
    extract_wrist_quaternion,
    wrist_rotation_config_from_dict,
)


DEFAULT_TICK_INTERVAL_MS = 10.0
CALIBRATION_FAILURE_MESSAGE = (
    "Calibration failed: max-min too small.\n"
    "Check target_finger_node_id, hand gesture, and whether you are opening/pinching the configured fingers."
)


@dataclass(frozen=True)
class HapticDebugConfig:
    print_zone_transitions: bool = False
    print_scheduler_events: bool = True


@dataclass(frozen=True)
class SessionEndPolicy:
    end_policy: str = "stop_on_haptic_release"
    allow_multiple_haptic_trials: bool = False
    finish_active_haptic_before_exit: bool = True
    post_release_recording_ms: float = 0.0
    post_release_continue_nback: bool = False


@dataclass(frozen=True)
class HapticFeedbackDisplayConfig:
    mode: str = "none"
    print_on_emit: bool = True


@dataclass
class HapticEpisodeState:
    active: bool = False
    completed: bool = False
    haptic_trial_count: int = 0
    last_haptic_event_name: str = ""
    interrupted_haptic_trial: bool = False

    def observe(self, event: Any) -> None:
        event_name = str(getattr(event, "event_name", ""))
        self.last_haptic_event_name = event_name
        if event_name == "contact":
            self.active = True
            self.completed = False
            self.haptic_trial_count = max(
                self.haptic_trial_count,
                int(getattr(event, "haptic_trial_index", 0)) + 1,
            )
        if event_name == "release":
            self.active = False
            self.completed = True
            self.haptic_trial_count = max(
                self.haptic_trial_count,
                int(getattr(event, "haptic_trial_index", 0)) + 1,
            )


@dataclass
class ZoneRunStats:
    max_open_zone_duration_ms: float = 0.0
    max_closed_zone_duration_ms: float = 0.0
    open_zone_run_count: int = 0
    closed_zone_run_count: int = 0
    _current_zone: str | None = None
    _current_start_ms: float | None = None

    def update(self, zone: str, now_ms: float) -> None:
        if zone == self._current_zone:
            return
        self._finish_current(float(now_ms))
        if zone in {"open_zone", "closed_zone"}:
            if zone == "open_zone":
                self.open_zone_run_count += 1
            else:
                self.closed_zone_run_count += 1
            self._current_zone = zone
            self._current_start_ms = float(now_ms)
            return
        self._current_zone = None
        self._current_start_ms = None

    def finalize(self, now_ms: float) -> None:
        self._finish_current(float(now_ms))
        self._current_zone = None
        self._current_start_ms = None

    def to_dict(self) -> dict[str, float | int]:
        return {
            "max_open_zone_duration_ms": self.max_open_zone_duration_ms,
            "max_closed_zone_duration_ms": self.max_closed_zone_duration_ms,
            "open_zone_run_count": self.open_zone_run_count,
            "closed_zone_run_count": self.closed_zone_run_count,
        }

    def _finish_current(self, now_ms: float) -> None:
        if self._current_zone is None or self._current_start_ms is None:
            return
        duration = max(0.0, now_ms - self._current_start_ms)
        if self._current_zone == "open_zone":
            self.max_open_zone_duration_ms = max(
                self.max_open_zone_duration_ms,
                duration,
            )
        elif self._current_zone == "closed_zone":
            self.max_closed_zone_duration_ms = max(
                self.max_closed_zone_duration_ms,
                duration,
            )


@dataclass(frozen=True)
class NBackResponseInput:
    """Synthetic response used by the pure dual-task core tests."""

    key_name: str
    monotonic_ms: float


@dataclass(frozen=True)
class PinchHaptic1BackCoreResult:
    total_pinch_samples: int
    total_valid_pinch_samples: int
    total_haptic_events: int
    total_nback_trials: int
    total_nback_responses: int
    max_open_zone_duration_ms: float = 0.0
    max_closed_zone_duration_ms: float = 0.0
    open_zone_run_count: int = 0
    closed_zone_run_count: int = 0
    session_should_end: bool = False
    end_reason: str = ""
    haptic_episode_completed: bool = False
    haptic_trial_count: int = 0
    last_haptic_event_name: str = ""
    interrupted_haptic_trial: bool = False
    allow_multiple_haptic_trials: bool = True
    finish_active_haptic_before_exit: bool = True
    post_release_recording_ms: float = 0.0
    post_release_continue_nback: bool = False
    post_release_started_ms: float | None = None
    post_release_end_ms: float | None = None
    post_release_pinch_samples: int = 0


def run_pinch_haptic_1back_core(
    samples: Iterable[PinchInputSample],
    *,
    calibration: PinchCalibrationResult,
    plan: HapticPlanConfig,
    logger: DualTaskLogger,
    nback_timeline: NBackTimeline,
    sender: SimpleHapticSender | None = None,
    scheduler_config: HapticTrialSchedulerConfig | None = None,
    nback_responses: Iterable[NBackResponseInput | Any] | None = None,
    start_monotonic_ms: float | None = None,
    end_monotonic_ms: float | None = None,
    tick_interval_ms: float = DEFAULT_TICK_INTERVAL_MS,
    session_end_policy: SessionEndPolicy | None = None,
    haptic_feedback_display: HapticFeedbackDisplayConfig | None = None,
    print_fn: Any = print,
) -> PinchHaptic1BackCoreResult:
    """Run a deterministic dual-task loop without Pygame, TCP, or ESP32."""

    tick_interval = _positive_float(tick_interval_ms, "tick_interval_ms")
    sample_list = sorted(samples, key=lambda item: float(getattr(item, "monotonic_ms")))
    response_list = sorted(
        list(nback_responses or ()),
        key=lambda item: _response_time_ms(item),
    )
    if not nback_timeline.started:
        if start_monotonic_ms is None:
            start_monotonic_ms = _infer_start_ms(sample_list, response_list)
        nback_timeline.start(float(start_monotonic_ms))

    timeline_end = nback_timeline.end_monotonic_ms
    if timeline_end is None:
        raise ValueError("nback_timeline must contain at least one trial.")
    if start_monotonic_ms is None:
        first_trial = nback_timeline.trials[0]
        start_monotonic_ms = first_trial.fixation_onset_monotonic_ms
    if end_monotonic_ms is None:
        end_monotonic_ms = max(
            timeline_end,
            _last_time_ms(sample_list, default=float(start_monotonic_ms)),
            _last_response_time_ms(response_list, default=float(start_monotonic_ms)),
        )

    haptic_sender = sender or SimpleHapticSender(session_id=logger.session_id)
    scheduler = HapticTrialScheduler(plan, scheduler_config)
    policy = session_end_policy or SessionEndPolicy(
        allow_multiple_haptic_trials=True,
        finish_active_haptic_before_exit=False,
    )
    feedback_config = haptic_feedback_display or HapticFeedbackDisplayConfig()
    episode_state = HapticEpisodeState()
    latest_sample: PinchInputSample | None = None
    latest_zone = "invalid"
    sample_index = 0
    response_index = 0
    total_haptic_events = 0
    now_ms = float(start_monotonic_ms)
    end_ms = float(end_monotonic_ms)
    zone_stats = ZoneRunStats()
    session_should_end = False
    end_reason = ""
    final_now_ms = end_ms
    post_release_started_ms: float | None = None
    post_release_end_ms: float | None = None
    post_release_pinch_samples = 0

    while True:
        while (
            sample_index < len(sample_list)
            and float(getattr(sample_list[sample_index], "monotonic_ms")) <= now_ms + 1e-9
        ):
            latest_sample = sample_list[sample_index]
            latest_zone = classify_pinch_zone(
                getattr(latest_sample, "pinch_distance", None),
                calibration,
            )
            zone_stats.update(latest_zone, float(getattr(latest_sample, "monotonic_ms")))
            logger.write_pinch_sample(latest_sample, calibration=calibration, zone=latest_zone)
            if post_release_started_ms is not None:
                post_release_pinch_samples += 1
            sample_index += 1

        nback_active = post_release_started_ms is None or policy.post_release_continue_nback
        if nback_active:
            while (
                response_index < len(response_list)
                and _response_time_ms(response_list[response_index]) <= now_ms + 1e-9
            ):
                response = response_list[response_index]
                nback_timeline.record_response(
                    _response_key_name(response),
                    _response_time_ms(response),
                )
                response_index += 1

        emitted: list[Any] = []
        if post_release_started_ms is None:
            emitted = _advance_scheduler_for_current_state(
                scheduler,
                zone=latest_zone,
                now_ms=now_ms,
                latest_sample=latest_sample,
                digit_onsets_ms=nback_timeline.digit_onsets_ms,
            )
        for event in emitted:
            haptic_sender.record_scheduled_event(event)
            episode_state.observe(event)
            _print_haptic_feedback_if_needed(
                event,
                feedback_config,
                print_fn=print_fn,
            )
            if _event_should_end_session(event, policy):
                session_should_end = True
                post_release_started_ms = now_ms
                post_release_end_ms = now_ms + float(getattr(event, "duration_ms", 0) or 0) + policy.post_release_recording_ms
                end_reason = "haptic_release_post_recording"
        total_haptic_events += len(emitted)
        haptic_sender.poll_due_control_commands(now_ms)

        if nback_active:
            for row in nback_timeline.finalize_until(now_ms, session_id=logger.session_id):
                logger.write_nback_event(row)
        if post_release_end_ms is not None and now_ms >= post_release_end_ms:
            final_now_ms = now_ms
            end_reason = "haptic_release_post_recording_complete"
            break

        if post_release_end_ms is not None:
            future_sample_ms = _next_sample_time_ms(sample_list, sample_index)
            next_candidates = [now_ms + tick_interval, post_release_end_ms]
            if future_sample_ms is not None:
                next_candidates.append(future_sample_ms)
            now_ms = min(value for value in next_candidates if value > now_ms + 1e-9)
            continue

        loop_end_ms = end_ms
        if _haptic_sequence_active(scheduler, episode_state) and policy.finish_active_haptic_before_exit:
            loop_end_ms = max(end_ms, now_ms + tick_interval)
        next_ms = _next_loop_time_ms(
            now_ms=now_ms,
            end_ms=loop_end_ms,
            tick_interval_ms=tick_interval,
            sample_list=sample_list,
            sample_index=sample_index,
            response_list=response_list,
            response_index=response_index,
            nback_timeline=nback_timeline,
            scheduler=scheduler,
        )
        if next_ms is None:
            end_reason = _end_reason_at_limit(
                nback_timeline=nback_timeline,
                now_ms=now_ms,
                episode_state=episode_state,
                policy=policy,
            )
            final_now_ms = now_ms
            break
        now_ms = next_ms

    if _haptic_sequence_active(scheduler, episode_state) and not policy.finish_active_haptic_before_exit:
        episode_state.interrupted_haptic_trial = True
    final_nback_ms = (
        final_now_ms
        if post_release_started_ms is None or policy.post_release_continue_nback
        else post_release_started_ms
    )
    for row in nback_timeline.finalize_until(final_nback_ms, session_id=logger.session_id):
        logger.write_nback_event(row)
    haptic_sender.poll_due_control_commands(final_now_ms)
    zone_stats.finalize(final_now_ms)
    logger.write_nback_events([])
    haptic_sender.write_csv(logger.paths.haptic_events_csv)
    return PinchHaptic1BackCoreResult(
        total_pinch_samples=logger.total_pinch_samples,
        total_valid_pinch_samples=logger.total_valid_pinch_samples,
        total_haptic_events=total_haptic_events,
        total_nback_trials=logger.total_nback_trials,
        total_nback_responses=logger.total_nback_responses,
        session_should_end=session_should_end,
        end_reason=end_reason,
        haptic_episode_completed=episode_state.completed,
        haptic_trial_count=episode_state.haptic_trial_count,
        last_haptic_event_name=episode_state.last_haptic_event_name,
        interrupted_haptic_trial=episode_state.interrupted_haptic_trial,
        allow_multiple_haptic_trials=policy.allow_multiple_haptic_trials,
        finish_active_haptic_before_exit=policy.finish_active_haptic_before_exit,
        post_release_recording_ms=policy.post_release_recording_ms,
        post_release_continue_nback=policy.post_release_continue_nback,
        post_release_started_ms=post_release_started_ms,
        post_release_end_ms=post_release_end_ms,
        post_release_pinch_samples=post_release_pinch_samples,
        **zone_stats.to_dict(),
    )


def run_live_pinch_haptic_1back(config_path: str | Path) -> Path:
    """Run the interactive MANUS + 1-back dual-task with disabled haptic TCP."""

    config = load_dualtask_config(config_path)
    session_config = _object_section(config, "session")
    manus_config = _object_section(config, "manus")
    pinch_config = _object_section(config, "pinch")
    calibration_config_payload = _object_section(config, "calibration")
    haptic_config = _object_section(config, "haptic")
    sync_config = _object_section(config, "sync")
    wrist_rotation_config = wrist_rotation_config_from_dict(config.get("wrist_rotation"))
    haptic_debug_config = _haptic_debug_config_from_dualtask_config(config)
    session_end_policy = _session_end_policy_from_config(session_config)
    feedback_config = _haptic_feedback_display_from_dualtask_config(config)

    session_id = make_session_id(session_config.get("session_id_prefix", "pinch_haptic_1back"))
    logger = DualTaskLogger(
        session_id=session_id,
        output_root=session_config.get("output_root", "outputs"),
    )
    plan_path = Path(session_config.get("haptic_plan_config", "haptic_plan_config_example.yaml"))
    plan = load_haptic_plan_config(plan_path)
    plan = _plan_with_global_haptic_defaults(plan, config.get("haptic_defaults"))
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
        min_distance_range=calibration_config_payload.get("min_distance_range", 0.02),
        min_distance_range_ratio=calibration_config_payload.get(
            "min_distance_range_ratio",
            0.15,
        ),
    )
    vibration_tcp_config = config.get("vibration_tcp") or {}
    matrix_tcp_config = config.get("matrix_tcp") or {}
    vibration_enabled = bool(haptic_config.get("vibration_enabled", False))
    matrix_enabled = bool(haptic_config.get("matrix_enabled", False))
    vibration_tcp_enabled = vibration_enabled and bool(vibration_tcp_config.get("enabled", False))
    matrix_tcp_enabled = matrix_enabled and bool(matrix_tcp_config.get("enabled", False))
    sender_config = SimpleHapticSenderConfig(
        vibration_enabled=vibration_enabled,
        matrix_enabled=matrix_enabled,
        visual_text_cue_enabled=bool(haptic_config.get("visual_text_cue_enabled", False)),
        disabled_mode=not (vibration_tcp_enabled or matrix_tcp_enabled),
        vibration_tcp_enabled=vibration_tcp_enabled,
        vibration_required=bool(vibration_tcp_config.get("required", False)),
        vibration_host=str(vibration_tcp_config.get("host", "127.0.0.1")),
        vibration_port=int(vibration_tcp_config.get("port", 12346)),
        matrix_tcp_enabled=matrix_tcp_enabled,
        matrix_required=bool(matrix_tcp_config.get("required", False)),
        matrix_host=str(matrix_tcp_config.get("host", "127.0.0.1")),
        matrix_port=int(matrix_tcp_config.get("port", 12345)),
        vibration_connect_timeout_s=float(vibration_tcp_config.get("connect_timeout_s", 2.0)),
        vibration_send_timeout_s=float(vibration_tcp_config.get("send_timeout_s", 0.2)),
        matrix_connect_timeout_s=float(matrix_tcp_config.get("connect_timeout_s", 2.0)),
        matrix_send_timeout_s=float(matrix_tcp_config.get("send_timeout_s", 0.2)),
        max_queue_size=int(haptic_config.get("max_queue_size", 128)),
        matrix_latest_only=bool(haptic_config.get("matrix_latest_only", True)),
    )
    sender = SimpleHapticSender(sender_config, session_id=session_id)
    scheduler_config = HapticTrialSchedulerConfig(
        avoid_haptic_on_digit_onset=bool(sync_config.get("avoid_haptic_on_digit_onset", True)),
        digit_onset_guard_ms=sync_config.get("digit_onset_guard_ms", 150),
        max_haptic_delay_ms=sync_config.get("max_haptic_delay_ms", 500),
        if_cannot_avoid=str(sync_config.get("if_cannot_avoid", "log_warning_and_send")),
    )
    nback_timeline = NBackTimeline(_nback_config_from_dualtask_config(config))

    warnings: list[str] = []
    errors: list[str] = []
    start_wall = _now_iso()
    total_haptic_events = 0
    calibration: PinchCalibrationResult | None = None
    wrist_calibration: WristRotationCalibrationResult | None = None
    formal_result: PinchHaptic1BackCoreResult | None = None
    end_reason = ""
    server = _make_manus_tcp_server(manus_config)
    manus_tcp_log_state = ManusTcpLogState()
    display: _NBackPygameDisplay | None = None
    try:
        print(f"Session: {session_id}")
        print(f"Output: {logger.session_dir}")
        print("[MANUS TCP] start this Python runner before SDKMinimalClient_Windows.")
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
        if not _should_enter_formal_phase(calibration):
            warnings.append(f"calibration_failed: {calibration.calibration_failure_reason}")
            print(CALIBRATION_FAILURE_MESSAGE)
            display = _NBackPygameDisplay()
            display.show_text_and_wait(
                f"{CALIBRATION_FAILURE_MESSAGE}\n\n按空格键退出",
                wait_key_name="space",
            )
            return logger.session_dir

        if wrist_rotation_config.enabled:
            wrist_calibration = _run_live_wrist_rotation_calibration(
                server,
                logger,
                config=wrist_rotation_config,
                session_id=session_id,
                save_raw_frames=bool(manus_config.get("save_raw_frames", True)),
                tcp_log_state=manus_tcp_log_state,
            )
            logger.write_wrist_rotation_calibration(wrist_calibration)
            if not wrist_calibration.calibration_passed:
                warnings.append(
                    "wrist_rotation_calibration_failed:"
                    + str(wrist_calibration.failure_reason)
                )

        display = _NBackPygameDisplay()
        display.show_text_and_wait(
            "1-Back 任务\n\n"
            "屏幕上会依次显示数字\n"
            "请判断当前数字是否与前一个数字相同\n\n"
            f"相同按 [{nback_timeline.config.key_same.upper()}] 键\n"
            f"不同按 [{nback_timeline.config.key_different.upper()}] 键\n\n"
            "按空格键开始正式双任务",
            wait_key_name="space",
        )
        formal_result = _run_live_formal_phase(
            server,
            parser,
            logger,
            calibration=calibration,
            plan=plan,
            sender=sender,
            scheduler_config=scheduler_config,
            nback_timeline=nback_timeline,
            display=display,
            session_id=session_id,
            save_raw_frames=bool(manus_config.get("save_raw_frames", True)),
            tcp_log_state=manus_tcp_log_state,
            haptic_debug_config=haptic_debug_config,
            session_end_policy=session_end_policy,
            haptic_feedback_display=feedback_config,
            duration_s=float(session_config.get("duration_s", 60)),
            wrist_rotation_config=wrist_rotation_config,
            wrist_rotation_calibration=wrist_calibration,
        )
        total_haptic_events = formal_result.total_haptic_events
        end_reason = formal_result.end_reason
    except Exception as exc:
        errors.append(str(exc))
        raise
    finally:
        server.stop("pinch_haptic_1back_finished")
        server.join(timeout=1.0)
        if display is not None:
            display.close()
        sender.write_csv(logger.paths.haptic_events_csv)
        logger.write_nback_events([])
        end_wall = _now_iso()
        summary = {
                "session_id": session_id,
                "participant_id": session_config.get("participant_id", ""),
                "condition_id": session_config.get("condition_id", ""),
                "config_path": str(config_path),
                "haptic_plan_config_path": str(plan_path),
                "start_wall_time_iso": start_wall,
                "end_wall_time_iso": end_wall,
                "output_files": logger.paths.to_dict(),
                "total_nback_trials": logger.total_nback_trials,
                "total_nback_responses": logger.total_nback_responses,
                "total_haptic_events": len(sender.records),
                "total_pinch_samples": logger.total_pinch_samples,
                "total_valid_pinch_samples": logger.total_valid_pinch_samples,
                "visual_text_cue_enabled": sender_config.visual_text_cue_enabled,
                "vibration_enabled": sender_config.vibration_enabled,
                "matrix_enabled": sender_config.matrix_enabled,
                "wrist_rotation_enabled": wrist_rotation_config.enabled,
                "wrist_rotation_calibration_passed": (
                    wrist_calibration.calibration_passed
                    if wrist_calibration is not None
                    else False
                ),
                "warnings": warnings,
                "errors": errors,
        }
        summary.update(_calibration_summary_fields(calibration))
        summary.update(_zone_summary_fields(formal_result))
        summary.update(_haptic_end_summary_fields(formal_result, session_end_policy, end_reason))
        if len(sender.records) == 0:
            _append_no_haptic_event_warnings(warnings, summary, plan)
        if summary.get("interrupted_haptic_trial"):
            warnings.append("haptic_sequence_interrupted")
        logger.write_summary(summary)
    print(f"Dual-task complete. Haptic events: {total_haptic_events}")
    return logger.session_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="MANUS pinch+haptic+1-back disabled runner.")
    parser.add_argument("--config", default="dualtask_config.yaml")
    args = parser.parse_args()
    run_live_pinch_haptic_1back(args.config)
    return 0


def _run_live_wrist_rotation_calibration(
    server: LiveRawStreamServer,
    logger: DualTaskLogger,
    *,
    config: WristRotationConfig,
    session_id: str,
    save_raw_frames: bool,
    tcp_log_state: ManusTcpLogState | None = None,
) -> WristRotationCalibrationResult:
    input("Wrist neutral calibration: press Enter, then keep wrist neutral...")
    neutral = _collect_live_wrist_quaternions(
        server,
        logger,
        config=config,
        duration_s=config.calibration_duration_s,
        save_raw_frames=save_raw_frames,
        tcp_log_state=tcp_log_state,
    )
    input("Wrist left calibration: press Enter, then rotate wrist left...")
    left = _collect_live_wrist_quaternions(
        server,
        logger,
        config=config,
        duration_s=config.calibration_duration_s,
        save_raw_frames=save_raw_frames,
        tcp_log_state=tcp_log_state,
    )
    input("Wrist right calibration: press Enter, then rotate wrist right...")
    right = _collect_live_wrist_quaternions(
        server,
        logger,
        config=config,
        duration_s=config.calibration_duration_s,
        save_raw_frames=save_raw_frames,
        tcp_log_state=tcp_log_state,
    )
    result = calibrate_wrist_rotation(
        neutral,
        left,
        right,
        config=config,
    )
    if result.calibration_passed:
        print(f"Wrist rotation calibration passed: threshold={result.threshold:.6f}")
    else:
        print(f"Wrist rotation calibration failed: {result.failure_reason}")
    return result


def _collect_live_wrist_quaternions(
    server: LiveRawStreamServer,
    logger: DualTaskLogger,
    *,
    config: WristRotationConfig,
    duration_s: float,
    save_raw_frames: bool,
    tcp_log_state: ManusTcpLogState | None = None,
) -> list[tuple[float, float, float, float]]:
    deadline = time.monotonic() + float(duration_s)
    quaternions: list[tuple[float, float, float, float]] = []
    while time.monotonic() < deadline:
        frame = _get_manus_frame(server, timeout=0.1, log_state=tcp_log_state)
        if frame is None:
            continue
        raw = _raw_from_live_frame(frame)
        if save_raw_frames:
            logger.write_raw_frame(raw)
        q = extract_wrist_quaternion(
            frame,
            node_id=config.node_id,
            quaternion_order=config.quaternion_order,
        )
        if q is not None:
            quaternions.append(q)
    return quaternions


def _run_live_formal_phase(
    server: LiveRawStreamServer,
    parser: ManusOnlyPinchInput,
    logger: DualTaskLogger,
    *,
    calibration: PinchCalibrationResult,
    plan: HapticPlanConfig,
    sender: SimpleHapticSender,
    scheduler_config: HapticTrialSchedulerConfig,
    nback_timeline: NBackTimeline,
    display: "_NBackPygameDisplay",
    session_id: str,
    save_raw_frames: bool,
    tcp_log_state: ManusTcpLogState | None = None,
    haptic_debug_config: HapticDebugConfig | None = None,
    session_end_policy: SessionEndPolicy | None = None,
    haptic_feedback_display: HapticFeedbackDisplayConfig | None = None,
    duration_s: float = 60.0,
    wrist_rotation_config: WristRotationConfig | None = None,
    wrist_rotation_calibration: WristRotationCalibrationResult | None = None,
) -> PinchHaptic1BackCoreResult:
    scheduler = HapticTrialScheduler(plan, scheduler_config)
    policy = session_end_policy or SessionEndPolicy()
    feedback_config = haptic_feedback_display or HapticFeedbackDisplayConfig()
    episode_state = HapticEpisodeState()
    latest_sample: PinchInputSample | None = None
    latest_zone = "invalid"
    previous_logged_zone = "invalid"
    total_haptic_events = 0
    zone_stats = ZoneRunStats()
    debug_config = haptic_debug_config or HapticDebugConfig()
    wrist_config = wrist_rotation_config or WristRotationConfig()
    start_ms = time.monotonic() * 1000.0
    duration_deadline_ms = start_ms + max(0.0, float(duration_s)) * 1000.0
    nback_timeline.start(start_ms)
    end_reason = ""
    final_now_ms = start_ms
    post_release_started_ms: float | None = None
    post_release_end_ms: float | None = None
    post_release_pinch_samples = 0

    while True:
        now_ms = time.monotonic() * 1000.0
        nback_active = post_release_started_ms is None or policy.post_release_continue_nback
        for key_name in display.poll_keydowns():
            if nback_active:
                nback_timeline.record_response(key_name, now_ms)

        frame = _get_manus_frame(server, timeout=0.0, log_state=tcp_log_state)
        while frame is not None:
            raw = _raw_from_live_frame(frame)
            if save_raw_frames:
                logger.write_raw_frame(raw)
            latest_sample = parser.parse_sample(frame, session_id=session_id)
            latest_zone = classify_pinch_zone(
                getattr(latest_sample, "pinch_distance", None),
                calibration,
            )
            zone_stats.update(latest_zone, float(getattr(latest_sample, "monotonic_ms")))
            if (
                debug_config.print_zone_transitions
                and latest_zone != previous_logged_zone
                and latest_zone in {"open_zone", "closed_zone"}
            ):
                print(f"enter {latest_zone}")
            previous_logged_zone = latest_zone
            logger.write_pinch_sample(latest_sample, calibration=calibration, zone=latest_zone)
            if (
                wrist_config.enabled
                and wrist_config.save_timeseries
                and wrist_rotation_calibration is not None
            ):
                logger.write_wrist_rotation_sample(
                    classify_wrist_rotation_frame(
                        frame,
                        wrist_rotation_calibration,
                        quaternion_order=wrist_config.quaternion_order,
                        session_id=session_id,
                    )
                )
            if post_release_started_ms is not None:
                post_release_pinch_samples += 1
            frame = _get_manus_frame(server, timeout=0.0, log_state=tcp_log_state)

        emitted: list[Any] = []
        if post_release_started_ms is None:
            emitted = _advance_scheduler_for_current_state(
                scheduler,
                zone=latest_zone,
                now_ms=now_ms,
                latest_sample=latest_sample,
                digit_onsets_ms=nback_timeline.digit_onsets_ms,
                haptic_debug_config=debug_config,
            )
        for event in emitted:
            sender.record_scheduled_event(event)
            episode_state.observe(event)
            _print_haptic_feedback_if_needed(event, feedback_config)
        total_haptic_events += len(emitted)
        sender.poll_due_control_commands(now_ms)

        if nback_active:
            for row in nback_timeline.finalize_until(now_ms, session_id=session_id):
                logger.write_nback_event(row)
            tick = nback_timeline.tick(now_ms)
            display.draw(tick)
        else:
            display.draw(NBackTick(phase=NBACK_PHASE_COMPLETE, trial=None))

        if any(_event_should_end_session(event, policy) for event in emitted):
            release_event = next(event for event in emitted if _event_should_end_session(event, policy))
            post_release_started_ms = now_ms
            post_release_end_ms = now_ms + float(getattr(release_event, "duration_ms", 0) or 0) + policy.post_release_recording_ms
            end_reason = "haptic_release_post_recording"
        if post_release_end_ms is not None and now_ms >= post_release_end_ms:
            end_reason = "haptic_release_post_recording_complete"
            final_now_ms = now_ms
            break
        if post_release_end_ms is not None:
            display.tick(60)
            continue
        nback_complete = nback_timeline.is_complete(now_ms)
        duration_elapsed = now_ms >= duration_deadline_ms
        if nback_complete or duration_elapsed:
            if _haptic_sequence_active(scheduler, episode_state) and policy.finish_active_haptic_before_exit:
                display.tick(60)
                continue
            end_reason = "nback_complete" if nback_complete else "duration_elapsed"
            if _haptic_sequence_active(scheduler, episode_state) and not policy.finish_active_haptic_before_exit:
                episode_state.interrupted_haptic_trial = True
            final_now_ms = now_ms
            break
        display.tick(60)

    final_nback_ms = (
        final_now_ms
        if post_release_started_ms is None or policy.post_release_continue_nback
        else post_release_started_ms
    )
    for row in nback_timeline.finalize_until(final_nback_ms, session_id=session_id):
        logger.write_nback_event(row)
    sender.poll_due_control_commands(final_now_ms)
    zone_stats.finalize(final_now_ms)
    sender.write_csv(logger.paths.haptic_events_csv)
    logger.write_nback_events([])
    return PinchHaptic1BackCoreResult(
        total_pinch_samples=logger.total_pinch_samples,
        total_valid_pinch_samples=logger.total_valid_pinch_samples,
        total_haptic_events=total_haptic_events,
        total_nback_trials=logger.total_nback_trials,
        total_nback_responses=logger.total_nback_responses,
        session_should_end=end_reason == "haptic_release",
        end_reason=end_reason,
        haptic_episode_completed=episode_state.completed,
        haptic_trial_count=episode_state.haptic_trial_count,
        last_haptic_event_name=episode_state.last_haptic_event_name,
        interrupted_haptic_trial=episode_state.interrupted_haptic_trial,
        allow_multiple_haptic_trials=policy.allow_multiple_haptic_trials,
        finish_active_haptic_before_exit=policy.finish_active_haptic_before_exit,
        post_release_recording_ms=policy.post_release_recording_ms,
        post_release_continue_nback=policy.post_release_continue_nback,
        post_release_started_ms=post_release_started_ms,
        post_release_end_ms=post_release_end_ms,
        post_release_pinch_samples=post_release_pinch_samples,
        **zone_stats.to_dict(),
    )


def _advance_scheduler_for_current_state(
    scheduler: HapticTrialScheduler,
    *,
    zone: str,
    now_ms: float,
    latest_sample: PinchInputSample | None,
    digit_onsets_ms: Iterable[float] | None,
    haptic_debug_config: HapticDebugConfig | None = None,
) -> list[Any]:
    events: list[Any] = []
    debug_config = haptic_debug_config or HapticDebugConfig(print_scheduler_events=False)
    pinch_distance = (
        getattr(latest_sample, "pinch_distance", None) if latest_sample is not None else None
    )
    frame_index = (
        getattr(latest_sample, "frame_index", None) if latest_sample is not None else None
    )
    previous_state = getattr(scheduler, "state", "")
    emitted = scheduler.update(
        zone=zone,
        now_ms=now_ms,
        pinch_distance=pinch_distance,
        frame_index=frame_index,
        digit_onsets_ms=digit_onsets_ms,
    )
    if debug_config.print_scheduler_events:
        _print_scheduler_debug(
            scheduler=scheduler,
            previous_state=previous_state,
            current_zone=zone,
            emitted=emitted,
        )
    events.extend(emitted)
    return events


def _next_loop_time_ms(
    *,
    now_ms: float,
    end_ms: float,
    tick_interval_ms: float,
    sample_list: list[PinchInputSample],
    sample_index: int,
    response_list: list[Any],
    response_index: int,
    nback_timeline: NBackTimeline,
    scheduler: HapticTrialScheduler,
) -> float | None:
    if now_ms >= end_ms:
        return None
    candidates = [now_ms + tick_interval_ms, end_ms]
    if sample_index < len(sample_list):
        candidates.append(float(getattr(sample_list[sample_index], "monotonic_ms")))
    if response_index < len(response_list):
        candidates.append(_response_time_ms(response_list[response_index]))
    pending_onset = _pending_onset_ms(scheduler)
    if pending_onset is not None:
        candidates.append(float(pending_onset))
    next_nback_end = _next_nback_finalize_time_ms(nback_timeline, now_ms)
    if next_nback_end is not None:
        candidates.append(next_nback_end)
    future = [value for value in candidates if value > now_ms + 1e-9]
    if not future:
        return None
    return min(future)


def _next_nback_finalize_time_ms(
    nback_timeline: NBackTimeline,
    now_ms: float,
) -> float | None:
    finalized = getattr(nback_timeline, "_finalized_indices", set())
    for trial in nback_timeline.trials:
        if trial.stimulus_index in finalized:
            continue
        value = trial.response_window_end_monotonic_ms
        if value > now_ms + 1e-9:
            return value
    return None


def _nback_config_from_dualtask_config(config: dict[str, Any]) -> NBackConfig:
    import config as nback_defaults

    payload = config.get("nback", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("nback section must be an object.")
    return NBackConfig(
        num_trials=payload.get("num_trials", nback_defaults.NUM_TRIALS),
        target_ratio=payload.get("target_ratio", nback_defaults.TARGET_RATIO),
        number_min=payload.get("number_min", nback_defaults.NUMBER_MIN),
        number_max=payload.get("number_max", nback_defaults.NUMBER_MAX),
        fixation_duration_ms=payload.get(
            "fixation_duration_ms",
            nback_defaults.FIXATION_DURATION,
        ),
        stimulus_duration_ms=payload.get(
            "stimulus_duration_ms",
            nback_defaults.STIMULUS_DURATION,
        ),
        isi_min_ms=payload.get("isi_min_ms", nback_defaults.ISI_MIN),
        isi_max_ms=payload.get("isi_max_ms", nback_defaults.ISI_MAX),
        key_same=payload.get("key_same", nback_defaults.KEY_SAME),
        key_different=payload.get("key_different", nback_defaults.KEY_DIFFERENT),
        random_seed=payload.get("random_seed"),
    )


def _haptic_debug_config_from_dualtask_config(config: dict[str, Any]) -> HapticDebugConfig:
    payload = config.get("haptic_debug", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("haptic_debug section must be an object.")
    return HapticDebugConfig(
        print_zone_transitions=bool(payload.get("print_zone_transitions", False)),
        print_scheduler_events=bool(payload.get("print_scheduler_events", True)),
    )


def _session_end_policy_from_config(session_config: dict[str, Any]) -> SessionEndPolicy:
    return SessionEndPolicy(
        end_policy=str(session_config.get("end_policy", "stop_on_haptic_release")),
        allow_multiple_haptic_trials=bool(session_config.get("allow_multiple_haptic_trials", False)),
        finish_active_haptic_before_exit=bool(
            session_config.get("finish_active_haptic_before_exit", True)
        ),
        post_release_recording_ms=float(session_config.get("post_release_recording_ms", 0)),
        post_release_continue_nback=bool(session_config.get("post_release_continue_nback", False)),
    )


def _haptic_feedback_display_from_dualtask_config(
    config: dict[str, Any],
) -> HapticFeedbackDisplayConfig:
    payload = config.get("haptic_feedback_display", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("haptic_feedback_display section must be an object.")
    mode = str(payload.get("mode", "none")).strip().lower()
    if mode not in {"none", "console"}:
        raise ValueError("haptic_feedback_display.mode must be none or console for this stage.")
    return HapticFeedbackDisplayConfig(
        mode=mode,
        print_on_emit=bool(payload.get("print_on_emit", True)),
    )


def _plan_with_global_haptic_defaults(
    plan: HapticPlanConfig,
    payload: Any,
) -> HapticPlanConfig:
    if payload is None:
        return plan
    if not isinstance(payload, dict):
        raise ValueError("haptic_defaults section must be an object.")
    return replace(
        plan,
        haptic_defaults=haptic_defaults_from_dict(payload, timing=plan.timing),
    )


def _calibration_summary_fields(
    calibration: PinchCalibrationResult | None,
) -> dict[str, Any]:
    if calibration is None:
        return {
            "distance_range": None,
            "distance_range_ratio": None,
            "calibration_passed": False,
            "calibration_failure_reason": "calibration_not_completed",
        }
    return {
        "distance_range": calibration.distance_range,
        "distance_range_ratio": calibration.distance_range_ratio,
        "calibration_passed": calibration.calibration_passed,
        "calibration_failure_reason": calibration.calibration_failure_reason,
    }


def _should_enter_formal_phase(calibration: PinchCalibrationResult) -> bool:
    return bool(calibration.calibration_passed)


def _zone_summary_fields(
    result: PinchHaptic1BackCoreResult | None,
) -> dict[str, float | int]:
    if result is None:
        return ZoneRunStats().to_dict()
    return {
        "max_open_zone_duration_ms": result.max_open_zone_duration_ms,
        "max_closed_zone_duration_ms": result.max_closed_zone_duration_ms,
        "open_zone_run_count": result.open_zone_run_count,
        "closed_zone_run_count": result.closed_zone_run_count,
    }


def _haptic_end_summary_fields(
    result: PinchHaptic1BackCoreResult | None,
    policy: SessionEndPolicy,
    end_reason: str = "",
) -> dict[str, Any]:
    if result is None:
        return {
            "end_reason": end_reason,
            "haptic_episode_completed": False,
            "haptic_trial_count": 0,
            "last_haptic_event_name": "",
            "interrupted_haptic_trial": False,
            "allow_multiple_haptic_trials": policy.allow_multiple_haptic_trials,
            "finish_active_haptic_before_exit": policy.finish_active_haptic_before_exit,
            "post_release_recording_ms": policy.post_release_recording_ms,
            "post_release_continue_nback": policy.post_release_continue_nback,
            "post_release_started_ms": None,
            "post_release_end_ms": None,
            "post_release_pinch_samples": 0,
        }
    return {
        "end_reason": result.end_reason or end_reason,
        "haptic_episode_completed": result.haptic_episode_completed,
        "haptic_trial_count": result.haptic_trial_count,
        "last_haptic_event_name": result.last_haptic_event_name,
        "interrupted_haptic_trial": result.interrupted_haptic_trial,
        "allow_multiple_haptic_trials": result.allow_multiple_haptic_trials,
        "finish_active_haptic_before_exit": result.finish_active_haptic_before_exit,
        "post_release_recording_ms": result.post_release_recording_ms,
        "post_release_continue_nback": result.post_release_continue_nback,
        "post_release_started_ms": result.post_release_started_ms,
        "post_release_end_ms": result.post_release_end_ms,
        "post_release_pinch_samples": result.post_release_pinch_samples,
    }


def _append_no_haptic_event_warnings(
    warnings: list[str],
    summary: dict[str, Any],
    plan: HapticPlanConfig,
) -> None:
    min_contact_delay = _min_contact_onset_delay_ms(plan)
    max_open_duration = float(summary.get("max_open_zone_duration_ms") or 0.0)
    warnings.extend(
        [
            "no_haptic_events",
            f"max_open_zone_duration_ms={max_open_duration}",
            f"min_contact_onset_delay_ms={min_contact_delay}",
        ]
    )
    if max_open_duration < min_contact_delay:
        warnings.append(
            "open_zone segments were shorter than contact onset delay; contact could not trigger."
        )


def _min_contact_onset_delay_ms(plan: HapticPlanConfig) -> int:
    contact = plan.events[0]
    delay_range = contact.onset_delay_ms or plan.haptic_defaults.contact_onset_delay_ms
    return int(delay_range[0])


def _event_should_end_session(event: Any, policy: SessionEndPolicy) -> bool:
    return (
        policy.end_policy == "stop_on_haptic_release"
        and not policy.allow_multiple_haptic_trials
        and str(getattr(event, "event_name", "")) == "release"
    )


def _haptic_sequence_active(
    scheduler: HapticTrialScheduler,
    episode_state: HapticEpisodeState,
) -> bool:
    return bool(
        episode_state.active
        or getattr(scheduler, "state", "")
        in {"PENDING_CONTACT", "WAIT_CLOSED_ZONE", "PENDING_PLAN_EVENT"}
    )


def _end_reason_at_limit(
    *,
    nback_timeline: NBackTimeline,
    now_ms: float,
    episode_state: HapticEpisodeState,
    policy: SessionEndPolicy,
) -> str:
    if episode_state.active and not policy.finish_active_haptic_before_exit:
        episode_state.interrupted_haptic_trial = True
    if nback_timeline.is_complete(now_ms):
        return "nback_complete"
    return "duration_elapsed"


def _next_sample_time_ms(
    sample_list: list[PinchInputSample],
    sample_index: int,
) -> float | None:
    if sample_index >= len(sample_list):
        return None
    return float(getattr(sample_list[sample_index], "monotonic_ms"))


def _print_haptic_feedback_if_needed(
    event: Any,
    config: HapticFeedbackDisplayConfig,
    *,
    print_fn: Any = print,
) -> None:
    if config.mode != "console" or not config.print_on_emit:
        return
    trial_index = getattr(event, "haptic_trial_index", 0)
    event_name = getattr(event, "event_name", "")
    modality = getattr(event, "modality", "")
    duration_ms = getattr(event, "duration_ms", None)
    if modality == "matrix":
        channels = list(getattr(event, "channel_list", ()) or ())
        print_fn(
            f"[HAPTIC] trial={trial_index} event={event_name} "
            f"modality={modality} channels={channels}"
        )
    else:
        print_fn(
            f"[HAPTIC] trial={trial_index} event={event_name} "
            f"modality={modality} duration={duration_ms}ms"
        )
    if event_name == "release":
        print_fn("[HAPTIC] release emitted; ending dual-task session.")


def _print_scheduler_debug(
    *,
    scheduler: HapticTrialScheduler,
    previous_state: str,
    current_zone: str,
    emitted: list[Any],
) -> None:
    current_state = getattr(scheduler, "state", "")
    pending = getattr(scheduler, "_pending", None)
    if previous_state == "WAIT_OPEN_ZONE" and current_state == "PENDING_CONTACT":
        sampled_delay = getattr(pending, "sampled_delay_ms", None)
        print(f"pending contact sampled delay: {sampled_delay}")
    if (
        previous_state == "PENDING_CONTACT"
        and current_state == "WAIT_OPEN_ZONE"
        and current_zone != "open_zone"
    ):
        print("pending contact canceled because zone exited")
    for event in emitted:
        event_name = getattr(event, "event_name", "")
        if event_name == "contact":
            print("contact emitted")
        else:
            print(f"event emitted: {event_name}")


class _NBackPygameDisplay:
    def __init__(self) -> None:
        import config as nback_defaults
        import pygame

        self.pygame = pygame
        self.config = nback_defaults
        pygame.init()
        self.screen = pygame.display.set_mode(
            (nback_defaults.SCREEN_WIDTH, nback_defaults.SCREEN_HEIGHT)
        )
        pygame.display.set_caption("1-Back 双任务")
        self.clock = pygame.time.Clock()
        self.font_stimulus = _load_font_safe(
            pygame,
            nback_defaults.FONT_SIZE_STIMULUS,
            is_chinese=False,
        )
        self.font_instruction = _load_font_safe(
            pygame,
            nback_defaults.FONT_SIZE_INSTRUCTION,
            is_chinese=True,
        )

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

    def poll_keydowns(self) -> list[str]:
        keys: list[str] = []
        for event in self.pygame.event.get():
            if event.type == self.pygame.QUIT:
                raise KeyboardInterrupt("pygame window closed")
            if event.type != self.pygame.KEYDOWN:
                continue
            if event.key == self.pygame.K_ESCAPE:
                raise KeyboardInterrupt("escape pressed")
            keys.append(self.pygame.key.name(event.key).lower())
        return keys

    def draw(self, tick: NBackTick) -> None:
        background = self.config.BACKGROUND_COLOR
        text_color = self.config.TEXT_COLOR
        self.screen.fill(background)
        if tick.phase == NBACK_PHASE_FIXATION:
            self._draw_centered_text("+", self.font_instruction, text_color)
        elif tick.phase == NBACK_PHASE_STIMULUS and tick.trial is not None:
            self._draw_centered_text(str(tick.trial.stimulus), self.font_stimulus, text_color)
        elif tick.phase in {NBACK_PHASE_BLANK, NBACK_PHASE_COMPLETE}:
            pass
        self.pygame.display.flip()

    def tick(self, fps: int) -> None:
        self.clock.tick(fps)

    def close(self) -> None:
        self.pygame.quit()

    def _draw_centered_lines(self, text: str, font: Any) -> None:
        self.screen.fill(self.config.BACKGROUND_COLOR)
        lines = text.split("\n")
        y_offset = self.config.SCREEN_HEIGHT // 2 - (len(lines) * font.get_height() // 2)
        for line in lines:
            surface = font.render(line, True, self.config.TEXT_COLOR)
            rect = surface.get_rect(center=(self.config.SCREEN_WIDTH // 2, y_offset))
            self.screen.blit(surface, rect)
            y_offset += font.get_height() + 10
        self.pygame.display.flip()

    def _draw_centered_text(self, text: str, font: Any, color: tuple[int, int, int]) -> None:
        surface = font.render(text, True, color)
        rect = surface.get_rect(
            center=(self.config.SCREEN_WIDTH // 2, self.config.SCREEN_HEIGHT // 2)
        )
        self.screen.blit(surface, rect)


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
    if key.startswith("k_"):
        key = key[2:]
    key = {
        "esc": "escape",
        "spacebar": "space",
        "enter": "return",
    }.get(key, key)
    for constant_name in (f"K_{key}", f"K_{key.upper()}"):
        value = getattr(pygame, constant_name, None)
        if value is not None:
            return int(value)
    raise ValueError(f"unsupported pygame key name: {key_name}")


def _infer_start_ms(
    samples: list[PinchInputSample],
    responses: list[Any],
) -> float:
    candidates: list[float] = []
    if samples:
        candidates.append(float(getattr(samples[0], "monotonic_ms")))
    if responses:
        candidates.append(_response_time_ms(responses[0]))
    return min(candidates) if candidates else 0.0


def _last_time_ms(samples: list[PinchInputSample], *, default: float) -> float:
    if not samples:
        return default
    return float(getattr(samples[-1], "monotonic_ms"))


def _last_response_time_ms(responses: list[Any], *, default: float) -> float:
    if not responses:
        return default
    return _response_time_ms(responses[-1])


def _response_time_ms(value: Any) -> float:
    if isinstance(value, tuple) and len(value) >= 2:
        return float(value[1])
    if hasattr(value, "monotonic_ms"):
        return float(getattr(value, "monotonic_ms"))
    return float(getattr(value, "response_monotonic_ms"))


def _response_key_name(value: Any) -> str:
    if isinstance(value, tuple) and len(value) >= 2:
        return str(value[0])
    if hasattr(value, "key_name"):
        return str(getattr(value, "key_name"))
    return str(getattr(value, "response_key"))


def _positive_float(value: Any, name: str) -> float:
    result = float(value)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive.")
    return result


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
