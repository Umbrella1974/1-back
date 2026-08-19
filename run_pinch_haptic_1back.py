"""MANUS pinch + disabled haptic scheduler + 1-back dual-task runner."""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from dualtask_logger import DualTaskLogger, make_session_id
from haptic_plan_config import (
    HapticPlanConfig,
    haptic_defaults_from_dict,
    load_haptic_plan_config,
)
from haptic_trial_scheduler import (
    HapticTrialScheduler,
    HapticTrialSchedulerConfig,
    TimedGroupedHapticScheduler,
)
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
from session_seeds import session_seed_info_from_config
from simple_haptic_sender import SimpleHapticSender, SimpleHapticSenderConfig
from vendor_exp2_abc.live_raw_stream import LiveRawStreamServer
from wrist_rotation import (
    WristRotationCalibrationResult,
    WristRotationConfig,
    calibrate_wrist_rotation,
    classify_wrist_rotation,
    classify_wrist_rotation_frame,
    extract_wrist_quaternion,
    wrist_rotation_config_from_dict,
)


DEFAULT_TICK_INTERVAL_MS = 10.0
TASK_TYPE_DUAL = "dual"
TASK_TYPE_SINGLE = "single"
TASK_TYPES = {TASK_TYPE_DUAL, TASK_TYPE_SINGLE, "tactile_only"}
CUE_DISPATCH_ZONE_SEQUENTIAL = "zone_sequential"
CUE_DISPATCH_TIMED_GROUPED = "timed_grouped"
CUE_DISPATCH_MODES = {CUE_DISPATCH_ZONE_SEQUENTIAL, CUE_DISPATCH_TIMED_GROUPED}
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
    single_post_release_recording_ms: float | None = None
    post_release_continue_nback: bool = False
    release_nback_trial_window: tuple[int, int] | None = None
    prerelease_haptic_complete_by_trial: int | None = None
    hold_release_until_nback_trial: bool = False
    finish_nback_after_haptic_release: bool = False


@dataclass(frozen=True)
class HapticFeedbackDisplayConfig:
    mode: str = "none"
    print_on_emit: bool = True


class OperatorAbort(RuntimeError):
    """Raised when the operator cancels from a command-line prompt."""


@dataclass(frozen=True)
class CalibrationReuseConfig:
    enabled: bool = False
    calibration_in: Path | None = None
    calibration_out: Path | None = None
    calibration_id: str = ""
    quick_check_enabled: bool = True
    quick_check_duration_s: float = 2.0
    open_mad_multiplier: float = 6.0
    wrist_neutral_min_ratio: float = 0.80


@dataclass(frozen=True)
class CalibrationBundle:
    calibration_id: str
    path: Path
    pinch_calibration: PinchCalibrationResult
    wrist_rotation_calibration: WristRotationCalibrationResult | None = None


@dataclass(frozen=True)
class CalibrationQuickCheckResult:
    enabled: bool = False
    passed: bool | None = None
    reason: str = ""
    open_valid_frame_count: int = 0
    open_distance_median: float | None = None
    open_distance_mad: float | None = None
    open_distance_delta: float | None = None
    open_distance_tolerance: float | None = None
    wrist_checked: bool = False
    wrist_valid_frame_count: int = 0
    wrist_neutral_count: int = 0
    wrist_neutral_ratio: float | None = None

    def to_summary_fields(self) -> dict[str, Any]:
        return {
            "calibration_quick_check_enabled": self.enabled,
            "calibration_quick_check_passed": self.passed,
            "calibration_quick_check_reason": self.reason,
            "calibration_quick_check_open_valid_frame_count": self.open_valid_frame_count,
            "calibration_quick_check_open_distance_median": self.open_distance_median,
            "calibration_quick_check_open_distance_mad": self.open_distance_mad,
            "calibration_quick_check_open_distance_delta": self.open_distance_delta,
            "calibration_quick_check_open_distance_tolerance": self.open_distance_tolerance,
            "calibration_quick_check_wrist_checked": self.wrist_checked,
            "calibration_quick_check_wrist_valid_frame_count": self.wrist_valid_frame_count,
            "calibration_quick_check_wrist_neutral_count": self.wrist_neutral_count,
            "calibration_quick_check_wrist_neutral_ratio": self.wrist_neutral_ratio,
        }


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


@dataclass
class ReleaseGateState:
    pending_event: Any | None = None
    pending_event_ready_ms: float | None = None
    pending_held_by_trial_gate: bool = False
    pending_held_by_wrist_neutral_gate: bool = False
    pending_planned_emit_trial_number: int | None = None
    pending_trial_gate_window: tuple[int, int] | None = None
    pending_trial_gate_open_trial: int | None = None
    pending_trial_gate_ignored: bool = False
    pending_late_window_warning: str = ""
    pending_wrist_neutral_gate_required: bool = False
    pending_wrist_neutral_gate_passed: bool | None = None
    release_was_held: bool = False
    release_emit_trial_number: int | None = None
    prerelease_deadline_warning_written: bool = False
    warnings: list[str] = field(default_factory=list)


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
    release_nback_trial_window: tuple[int, int] | None = None
    prerelease_haptic_complete_by_trial: int | None = None
    hold_release_until_nback_trial: bool = False
    finish_nback_after_haptic_release: bool = False
    post_release_started_ms: float | None = None
    post_release_end_ms: float | None = None
    post_release_pinch_samples: int = 0
    release_was_held: bool = False
    release_emit_trial_number: int | None = None
    haptic_policy_warnings: tuple[str, ...] = ()
    task_type: str = TASK_TYPE_DUAL
    cue_dispatch_mode: str = CUE_DISPATCH_ZONE_SEQUENTIAL
    nback_enabled: bool = True
    trial_gate_enabled: bool = True
    digit_guard_enabled: bool = True
    queue_depth_at_formal_start: int | None = None
    queue_depth_before_formal_flush: int | None = None
    flushed_count_at_formal_start: int | None = None
    first_frame_index_after_formal_flush: int | None = None
    latest_received_frame_index_at_formal_start: int | None = None
    max_queue_depth_during_formal: int | None = None
    max_frame_age_ms_during_formal: float | None = None
    haptic_tcp_failed: bool = False
    haptic_tcp_failure_count: int = 0
    haptic_tcp_failure_errors: tuple[str, ...] = ()


def run_pinch_haptic_1back_core(
    samples: Iterable[PinchInputSample],
    *,
    calibration: PinchCalibrationResult,
    plan: HapticPlanConfig,
    logger: DualTaskLogger,
    nback_timeline: NBackTimeline | None = None,
    sender: SimpleHapticSender | None = None,
    scheduler_config: HapticTrialSchedulerConfig | None = None,
    nback_responses: Iterable[NBackResponseInput | Any] | None = None,
    start_monotonic_ms: float | None = None,
    end_monotonic_ms: float | None = None,
    tick_interval_ms: float = DEFAULT_TICK_INTERVAL_MS,
    session_end_policy: SessionEndPolicy | None = None,
    haptic_feedback_display: HapticFeedbackDisplayConfig | None = None,
    task_type: str = TASK_TYPE_DUAL,
    print_fn: Any = print,
) -> PinchHaptic1BackCoreResult:
    """Run a deterministic dual-task loop without Pygame, TCP, or ESP32."""

    task = _normalize_task_type(task_type)
    nback_enabled = task == TASK_TYPE_DUAL
    trial_gate_enabled = nback_enabled
    digit_guard_enabled = nback_enabled
    if nback_enabled and nback_timeline is None:
        raise ValueError("nback_timeline is required when task_type=dual.")
    tick_interval = _positive_float(tick_interval_ms, "tick_interval_ms")
    sample_list = sorted(samples, key=lambda item: float(getattr(item, "monotonic_ms")))
    response_list = sorted(
        list(nback_responses or ()) if nback_enabled else [],
        key=lambda item: _response_time_ms(item),
    )
    if nback_enabled and nback_timeline is not None and not nback_timeline.started:
        if start_monotonic_ms is None:
            start_monotonic_ms = _infer_start_ms(sample_list, response_list)
        nback_timeline.start(float(start_monotonic_ms))

    if start_monotonic_ms is None:
        if nback_enabled and nback_timeline is not None:
            first_trial = nback_timeline.trials[0]
            start_monotonic_ms = first_trial.fixation_onset_monotonic_ms
        else:
            start_monotonic_ms = _infer_start_ms(sample_list, response_list)
    timeline_end = nback_timeline.end_monotonic_ms if nback_enabled and nback_timeline is not None else None
    if nback_enabled and timeline_end is None:
        raise ValueError("nback_timeline must contain at least one trial.")
    if end_monotonic_ms is None:
        end_monotonic_ms = max(
            timeline_end if timeline_end is not None else float(start_monotonic_ms),
            _last_time_ms(sample_list, default=float(start_monotonic_ms)),
            _last_response_time_ms(response_list, default=float(start_monotonic_ms)),
        )

    haptic_sender = sender or SimpleHapticSender(session_id=logger.session_id)
    scheduler = HapticTrialScheduler(plan, scheduler_config)
    policy = _session_end_policy_for_task(
        session_end_policy or SessionEndPolicy(
            allow_multiple_haptic_trials=True,
            finish_active_haptic_before_exit=False,
        ),
        task,
    )
    feedback_config = haptic_feedback_display or HapticFeedbackDisplayConfig()
    episode_state = HapticEpisodeState()
    latest_sample: PinchInputSample | None = None
    latest_wrist_sample: Any | None = None
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
    release_gate_state = ReleaseGateState()

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

        nback_active = nback_enabled and _post_release_nback_active(post_release_started_ms, policy)
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
            if release_gate_state.pending_event is None:
                emitted = _advance_scheduler_for_current_state(
                    scheduler,
                    zone=latest_zone,
                    now_ms=now_ms,
                    latest_sample=latest_sample,
                    digit_onsets_ms=(
                        nback_timeline.digit_onsets_ms if digit_guard_enabled and nback_timeline is not None else None
                    ),
                )
            emitted = _gate_haptic_events(
                emitted,
                policy=policy,
                gate_state=release_gate_state,
                scheduler=scheduler,
                nback_timeline=nback_timeline,
                trial_gate_enabled=trial_gate_enabled,
                now_ms=now_ms,
                latest_zone=latest_zone,
                latest_wrist_sample=None,
            )
            if trial_gate_enabled:
                _append_prerelease_deadline_warning_if_needed(
                    policy=policy,
                    gate_state=release_gate_state,
                    scheduler=scheduler,
                    nback_timeline=nback_timeline,
                    now_ms=now_ms,
                    post_release_started_ms=post_release_started_ms,
                )
        for event in emitted:
            _record_haptic_event(
                event,
                sender=haptic_sender,
                episode_state=episode_state,
                feedback_config=feedback_config,
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
        if _post_release_complete(
            policy=policy,
            nback_timeline=nback_timeline,
            nback_enabled=nback_enabled,
            now_ms=now_ms,
            post_release_end_ms=post_release_end_ms,
        ):
            final_now_ms = now_ms
            end_reason = _post_release_complete_reason(policy)
            break

        if post_release_end_ms is not None:
            future_sample_ms = _next_sample_time_ms(sample_list, sample_index)
            next_candidates = [now_ms + tick_interval, post_release_end_ms]
            if future_sample_ms is not None:
                next_candidates.append(future_sample_ms)
            now_ms = min(value for value in next_candidates if value > now_ms + 1e-9)
            continue

        loop_end_ms = end_ms
        if (
            (
                _haptic_sequence_active(scheduler, episode_state)
                or release_gate_state.pending_event is not None
            )
            and policy.finish_active_haptic_before_exit
        ):
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

    if (
        _haptic_sequence_active(scheduler, episode_state)
        or release_gate_state.pending_event is not None
    ) and not policy.finish_active_haptic_before_exit:
        episode_state.interrupted_haptic_trial = True
    final_nback_ms = (
        final_now_ms
        if post_release_started_ms is None or policy.post_release_continue_nback
        else post_release_started_ms
    )
    if nback_enabled and nback_timeline is not None:
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
        release_nback_trial_window=policy.release_nback_trial_window,
        prerelease_haptic_complete_by_trial=policy.prerelease_haptic_complete_by_trial,
        hold_release_until_nback_trial=policy.hold_release_until_nback_trial,
        finish_nback_after_haptic_release=policy.finish_nback_after_haptic_release,
        post_release_started_ms=post_release_started_ms,
        post_release_end_ms=post_release_end_ms,
        post_release_pinch_samples=post_release_pinch_samples,
        release_was_held=release_gate_state.release_was_held,
        release_emit_trial_number=release_gate_state.release_emit_trial_number,
        haptic_policy_warnings=tuple(release_gate_state.warnings),
        task_type=task,
        cue_dispatch_mode=CUE_DISPATCH_ZONE_SEQUENTIAL,
        nback_enabled=nback_enabled,
        trial_gate_enabled=trial_gate_enabled,
        digit_guard_enabled=digit_guard_enabled,
        **zone_stats.to_dict(),
    )


def run_live_pinch_haptic_1back(config_path: str | Path) -> Path:
    """Run the interactive MANUS + 1-back dual-task with disabled haptic TCP."""

    config = load_dualtask_config(config_path)
    session_config = _object_section(config, "session")
    manus_config = _object_section(config, "manus")
    pinch_config = _object_section(config, "pinch")
    calibration_config_payload = _object_section(config, "calibration")
    calibration_reuse_config = _calibration_reuse_config_from_dict(
        config.get("calibration_reuse"),
        config_path=Path(config_path),
    )
    haptic_config = _object_section(config, "haptic")
    sync_config = _object_section(config, "sync")
    wrist_rotation_config = wrist_rotation_config_from_dict(config.get("wrist_rotation"))
    haptic_debug_config = _haptic_debug_config_from_dualtask_config(config)
    configured_session_end_policy = _session_end_policy_from_config(session_config)
    feedback_config = _haptic_feedback_display_from_dualtask_config(config)
    seed_info = session_seed_info_from_config(session_config)
    task_type = _normalize_task_type(session_config.get("task_type", TASK_TYPE_DUAL))
    cue_dispatch_mode = _normalize_cue_dispatch_mode(
        session_config.get("cue_dispatch_mode", CUE_DISPATCH_ZONE_SEQUENTIAL)
    )
    nback_enabled = task_type == TASK_TYPE_DUAL
    trial_gate_enabled = nback_enabled
    digit_guard_enabled = nback_enabled
    warnings: list[str] = []

    session_id = make_session_id(session_config.get("session_id_prefix", "pinch_haptic_1back"))
    logger = DualTaskLogger(
        session_id=session_id,
        output_root=session_config.get("output_root", "outputs"),
    )
    plan_path = Path(session_config.get("haptic_plan_config", "haptic_plan_config_example.yaml"))
    plan = load_haptic_plan_config(plan_path)
    haptic_plan_template_random_seed = plan.random_seed
    plan = replace(plan, random_seed=seed_info.haptic_seed)
    plan = _plan_with_global_haptic_defaults(plan, config.get("haptic_defaults"))
    session_end_policy = _session_end_policy_for_task(configured_session_end_policy, task_type)
    if not trial_gate_enabled and _task_config_has_trial_gate_fields(plan, configured_session_end_policy):
        warnings.append("trial_gate_ignored_for_single_task")
    parser = ManusOnlyPinchInput(
        ManusPinchInputConfig(
            thumb_node_id=pinch_config.get("thumb_node_id", 4),
            target_finger_node_id=pinch_config.get("target_finger_node_id", 14),
            require_tracker=bool(manus_config.get("require_tracker", False)),
        )
    )
    calibration_config = PinchCalibrationConfig(
        open_hand_duration_s=calibration_config_payload.get("open_hand_duration_s", 3.0),
        contact_hand_duration_s=calibration_config_payload.get("contact_hand_duration_s", 3.0),
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
    sender_config = SimpleHapticSenderConfig(
        vibration_enabled=vibration_enabled,
        matrix_enabled=matrix_enabled,
        visual_text_cue_enabled=_bool_config_value(
            haptic_config.get("visual_text_cue_enabled", False),
            "haptic.visual_text_cue_enabled",
        ),
        disabled_mode=not (vibration_tcp_enabled or matrix_tcp_enabled),
        vibration_tcp_enabled=vibration_tcp_enabled,
        vibration_required=_bool_config_value(
            vibration_tcp_config.get("required", False),
            "vibration_tcp.required",
        ),
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
        matrix_required=_bool_config_value(
            matrix_tcp_config.get("required", False),
            "matrix_tcp.required",
        ),
        matrix_host=str(matrix_tcp_config.get("host", "127.0.0.1")),
        matrix_port=int(matrix_tcp_config.get("port", 12345)),
        vibration_connect_timeout_s=float(vibration_tcp_config.get("connect_timeout_s", 2.0)),
        vibration_send_timeout_s=float(vibration_tcp_config.get("send_timeout_s", 0.2)),
        matrix_connect_timeout_s=float(matrix_tcp_config.get("connect_timeout_s", 2.0)),
        matrix_send_timeout_s=float(matrix_tcp_config.get("send_timeout_s", 0.2)),
        max_queue_size=int(haptic_config.get("max_queue_size", 128)),
        matrix_latest_only=_bool_config_value(
            haptic_config.get("matrix_latest_only", True),
            "haptic.matrix_latest_only",
        ),
    )
    sender = SimpleHapticSender(sender_config, session_id=session_id)
    scheduler_config = HapticTrialSchedulerConfig(
        avoid_haptic_on_digit_onset=(
            bool(sync_config.get("avoid_haptic_on_digit_onset", True))
            if digit_guard_enabled
            else False
        ),
        digit_onset_guard_ms=sync_config.get("digit_onset_guard_ms", 150),
        max_haptic_delay_ms=sync_config.get("max_haptic_delay_ms", 500),
        if_cannot_avoid=str(sync_config.get("if_cannot_avoid", "log_warning_and_send")),
    )
    nback_config = (
        replace(
            _nback_config_from_dualtask_config(config),
            random_seed=seed_info.nback_seed,
        )
        if nback_enabled
        else None
    )
    nback_timeline = NBackTimeline(nback_config) if nback_config is not None else None

    errors: list[str] = []
    start_wall = _now_iso()
    total_haptic_events = 0
    calibration: PinchCalibrationResult | None = None
    wrist_calibration: WristRotationCalibrationResult | None = None
    calibration_bundle: CalibrationBundle | None = None
    calibration_quick_check = CalibrationQuickCheckResult(enabled=False)
    calibration_loaded_from_bundle = False
    calibration_saved_path = ""
    calibration_save_reason = ""
    formal_result: PinchHaptic1BackCoreResult | None = None
    end_reason = ""
    manus_queue_flush_events: list[dict[str, Any]] = []
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

        if (
            calibration_reuse_config.enabled
            and calibration_reuse_config.calibration_in is not None
            and calibration_reuse_config.calibration_in.exists()
        ):
            calibration_bundle = _load_calibration_bundle(
                calibration_reuse_config.calibration_in
            )
            print(f"[CALIBRATION] loaded {calibration_bundle.calibration_id}")
            reuse_block_reason = _calibration_reuse_block_reason(
                calibration_bundle.pinch_calibration
            )
            if reuse_block_reason:
                calibration_quick_check = replace(
                    calibration_quick_check,
                    enabled=calibration_reuse_config.quick_check_enabled,
                    passed=False,
                    reason=reuse_block_reason,
                )
                warnings.append("calibration_reuse_blocked:" + reuse_block_reason)
                print(
                    "[CALIBRATION] loaded calibration cannot be reused: "
                    + reuse_block_reason
                )
                _prompt_enter_or_abort(
                    "Press Enter to run a full calibration and save a new version..."
                )
            elif calibration_reuse_config.quick_check_enabled:
                calibration_quick_check = _run_live_calibration_quick_check(
                    server,
                    parser,
                    logger,
                    calibration=calibration_bundle.pinch_calibration,
                    wrist_calibration=calibration_bundle.wrist_rotation_calibration,
                    reuse_config=calibration_reuse_config,
                    wrist_rotation_config=wrist_rotation_config,
                    session_id=session_id,
                    save_raw_frames=bool(manus_config.get("save_raw_frames", True)),
                    tcp_log_state=manus_tcp_log_state,
                    min_valid_frames=calibration_config.min_valid_frames,
                    flush_events=manus_queue_flush_events,
                )
                if not calibration_quick_check.passed:
                    warnings.append(
                        "calibration_quick_check_failed:"
                        + calibration_quick_check.reason
                    )
                    print(
                        "[CALIBRATION] quick check failed: "
                        + calibration_quick_check.reason
                    )
                    _prompt_enter_or_abort(
                        "Press Enter to run a full calibration and save a new version..."
                    )
                else:
                    print("[CALIBRATION] quick check passed; reusing loaded calibration.")
            if (
                not reuse_block_reason
                and (
                    not calibration_reuse_config.quick_check_enabled
                    or calibration_quick_check.passed
                )
            ):
                calibration = calibration_bundle.pinch_calibration
                wrist_calibration = calibration_bundle.wrist_rotation_calibration
                calibration_loaded_from_bundle = True

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
                flush_events=manus_queue_flush_events,
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

        if wrist_rotation_config.enabled and wrist_calibration is None:
            wrist_calibration = _run_live_wrist_rotation_calibration(
                server,
                logger,
                config=wrist_rotation_config,
                session_id=session_id,
                save_raw_frames=bool(manus_config.get("save_raw_frames", True)),
                tcp_log_state=manus_tcp_log_state,
                flush_events=manus_queue_flush_events,
            )
        if wrist_rotation_config.enabled and wrist_calibration is not None:
            logger.write_wrist_rotation_calibration(wrist_calibration)
            if calibration_loaded_from_bundle:
                print(f"[WRIST] loaded calibration: passed={wrist_calibration.calibration_passed}")
            if not wrist_calibration.calibration_passed:
                warnings.append(
                    "wrist_rotation_calibration_failed:"
                    + str(wrist_calibration.failure_reason)
                )
                if wrist_rotation_config.required:
                    raise RuntimeError(
                        "wrist_rotation_calibration_failed:"
                        + str(wrist_calibration.failure_reason)
                    )
        else:
            print("[WRIST] calibration disabled")

        if calibration_reuse_config.enabled and not calibration_loaded_from_bundle:
            saved_path = _save_calibration_bundle(
                calibration,
                wrist_calibration,
                reuse_config=calibration_reuse_config,
                fallback_base_path=calibration_reuse_config.calibration_in,
            )
            calibration_saved_path = str(saved_path) if saved_path is not None else ""
            calibration_save_reason = (
                "new_version_after_quick_check_failure"
                if calibration_bundle is not None
                else "initial_full_calibration"
            )
            if saved_path is not None:
                print(f"[CALIBRATION] saved {saved_path}")

        if nback_enabled:
            if nback_timeline is None:
                raise RuntimeError("nback_timeline missing for dual task.")
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
        else:
            _prompt_enter_or_abort(
                "Tactile-only task: press Enter to start the formal tactile session..."
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
            task_type=task_type,
            cue_dispatch_mode=cue_dispatch_mode,
            flush_events=manus_queue_flush_events,
        )
        total_haptic_events = formal_result.total_haptic_events
        end_reason = formal_result.end_reason
    except OperatorAbort as exc:
        errors.append(str(exc))
        end_reason = "operator_aborted"
        raise
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
        end_reason = _final_summary_end_reason(end_reason, formal_result)
        summary = {
                "session_id": session_id,
                "participant_id": session_config.get("participant_id", ""),
                "condition_id": session_config.get("condition_id", ""),
                "task_type": task_type,
                "cue_dispatch_mode": cue_dispatch_mode,
                "nback_enabled": nback_enabled,
                "trial_gate_enabled": trial_gate_enabled,
                "digit_guard_enabled": digit_guard_enabled,
                "config_path": str(config_path),
                "haptic_plan_config_path": str(plan_path),
                "haptic_plan_id": plan.plan_id,
                "haptic_plan_template_random_seed": haptic_plan_template_random_seed,
                "haptic_plan_random_seed": plan.random_seed,
                **seed_info.to_dict(),
                "calibration_reuse_enabled": calibration_reuse_config.enabled,
                "calibration_loaded_from_bundle": calibration_loaded_from_bundle,
                "calibration_bundle_path": (
                    str(calibration_bundle.path) if calibration_bundle is not None else ""
                ),
                "calibration_id": _active_calibration_id(
                    calibration_bundle=calibration_bundle,
                    reuse_config=calibration_reuse_config,
                    saved_path=calibration_saved_path,
                    loaded=calibration_loaded_from_bundle,
                ),
                "calibration_saved_path": calibration_saved_path,
                "calibration_save_reason": calibration_save_reason,
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
                "wrist_rotation_required": wrist_rotation_config.required,
                "wrist_rotation_save_timeseries": wrist_rotation_config.save_timeseries,
                "wrist_up_down_enabled": wrist_rotation_config.enable_up_down,
                "wrist_rotation_calibration_passed": (
                    wrist_calibration.calibration_passed
                    if wrist_calibration is not None
                    else False
                ),
                "wrist_up_down_calibration_passed": (
                    wrist_calibration.up_down_calibration_passed
                    if wrist_calibration is not None
                    else False
                ),
                "wrist_rotation_failure_reason": (
                    wrist_calibration.failure_reason
                    if wrist_calibration is not None
                    else ""
                ),
                "wrist_up_down_failure_reason": (
                    wrist_calibration.up_down_failure_reason
                    if wrist_calibration is not None
                    else ""
                ),
                "wrist_rotation_timeseries_csv": (
                    str(logger.paths.wrist_rotation_timeseries_csv)
                    if wrist_rotation_config.enabled
                    else ""
                ),
                "wrist_rotation_calibration_json": (
                    str(logger.paths.wrist_rotation_calibration_json)
                    if wrist_rotation_config.enabled
                    else ""
                ),
                "wrist_rotation_valid_samples": logger.total_wrist_rotation_valid_samples,
                "wrist_rotation_invalid_samples": logger.total_wrist_rotation_invalid_samples,
                "manus_queue_flush_events": manus_queue_flush_events,
                "warnings": warnings,
                "errors": errors,
        }
        summary.update(_calibration_summary_fields(calibration))
        summary.update(calibration_quick_check.to_summary_fields())
        summary.update(_zone_summary_fields(formal_result))
        summary.update(_haptic_end_summary_fields(formal_result, session_end_policy, end_reason))
        warnings.extend(_haptic_policy_warnings_from_result(formal_result))
        if _should_append_no_haptic_event_warnings(formal_result, len(sender.records)):
            _append_no_haptic_event_warnings(warnings, summary, plan)
        if summary.get("interrupted_haptic_trial"):
            warnings.append("haptic_sequence_interrupted")
        logger.close_wrist_rotation_writer()
        logger.write_summary(summary)
    print(f"{task_type} task complete. Haptic events: {total_haptic_events}")
    return logger.session_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="MANUS pinch+haptic+1-back disabled runner.")
    parser.add_argument("--config", default="dualtask_config.yaml")
    args = parser.parse_args()
    try:
        run_live_pinch_haptic_1back(args.config)
    except OperatorAbort:
        print("Operator aborted.")
        return 130
    return 0


def _run_live_pinch_calibration(
    server: LiveRawStreamServer,
    parser: ManusOnlyPinchInput,
    logger: DualTaskLogger,
    *,
    calibration_config: PinchCalibrationConfig,
    pinch_config: dict[str, Any],
    manus_config: dict[str, Any],
    session_id: str,
    tcp_log_state: ManusTcpLogState | None,
    flush_events: list[dict[str, Any]] | None = None,
) -> PinchCalibrationResult:
    _prompt_enter_or_abort("Open hand calibration: press Enter, then keep hand open...")
    open_samples = _collect_live_calibration_samples(
        server,
        parser,
        logger,
        session_id=session_id,
        duration_s=calibration_config.open_hand_duration_s,
        save_raw_frames=bool(manus_config.get("save_raw_frames", True)),
        tcp_log_state=tcp_log_state,
        phase="open",
        flush_events=flush_events,
    )
    _prompt_enter_or_abort(
        "C-shape calibration: press Enter, then keep the task-ready C-shape posture..."
    )
    contact_samples = _collect_live_calibration_samples(
        server,
        parser,
        logger,
        session_id=session_id,
        duration_s=calibration_config.contact_hand_duration_s,
        save_raw_frames=bool(manus_config.get("save_raw_frames", True)),
        tcp_log_state=tcp_log_state,
        phase="contact",
        flush_events=flush_events,
    )
    _prompt_enter_or_abort(
        "Pinch calibration: press Enter, then pinch thumb and target finger..."
    )
    pinch_samples = _collect_live_calibration_samples(
        server,
        parser,
        logger,
        session_id=session_id,
        duration_s=calibration_config.pinch_hand_duration_s,
        save_raw_frames=bool(manus_config.get("save_raw_frames", True)),
        tcp_log_state=tcp_log_state,
        phase="pinch",
        flush_events=flush_events,
    )
    return calibrate_from_samples(
        open_samples,
        pinch_samples,
        contact_samples=contact_samples,
        config=calibration_config,
        thumb_node_id=pinch_config.get("thumb_node_id", 4),
        target_finger_node_id=pinch_config.get("target_finger_node_id", 14),
    )


def _calibration_reuse_config_from_dict(
    payload: Any,
    *,
    config_path: Path,
) -> CalibrationReuseConfig:
    value = payload or {}
    if not isinstance(value, dict):
        raise ValueError("calibration_reuse section must be an object.")
    enabled = _bool_config_value(value.get("enabled", False), "calibration_reuse.enabled")
    base_dir = Path(config_path).resolve().parent
    calibration_in = _optional_config_path(value.get("calibration_in"), base_dir=base_dir)
    calibration_out = _optional_config_path(value.get("calibration_out"), base_dir=base_dir)
    if enabled and calibration_in is None and calibration_out is None:
        raise ValueError(
            "calibration_reuse.enabled requires calibration_in or calibration_out."
        )
    return CalibrationReuseConfig(
        enabled=enabled,
        calibration_in=calibration_in,
        calibration_out=calibration_out,
        calibration_id=str(value.get("calibration_id", "") or ""),
        quick_check_enabled=_bool_config_value(
            value.get("quick_check_enabled", True),
            "calibration_reuse.quick_check_enabled",
        ),
        quick_check_duration_s=_positive_config_float(
            value.get("quick_check_duration_s", 2.0),
            "calibration_reuse.quick_check_duration_s",
        ),
        open_mad_multiplier=_positive_config_float(
            value.get("open_mad_multiplier", 6.0),
            "calibration_reuse.open_mad_multiplier",
        ),
        wrist_neutral_min_ratio=_ratio_config_float(
            value.get("wrist_neutral_min_ratio", 0.80),
            "calibration_reuse.wrist_neutral_min_ratio",
        ),
    )


def _optional_config_path(value: Any, *, base_dir: Path) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    path = Path(str(value))
    return path if path.is_absolute() else base_dir / path


def _load_calibration_bundle(path: Path) -> CalibrationBundle:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("calibration bundle must be a JSON object.")
    pinch_payload = payload.get("pinch_calibration")
    if pinch_payload is None and "min_distance" in payload:
        pinch_payload = payload
    if not isinstance(pinch_payload, dict):
        raise ValueError("calibration bundle missing pinch_calibration.")
    wrist_payload = payload.get("wrist_rotation_calibration")
    return CalibrationBundle(
        calibration_id=str(payload.get("calibration_id") or path.stem),
        path=path,
        pinch_calibration=_dataclass_from_dict(PinchCalibrationResult, pinch_payload),
        wrist_rotation_calibration=(
            _dataclass_from_dict(WristRotationCalibrationResult, wrist_payload)
            if isinstance(wrist_payload, dict)
            else None
        ),
    )


def _save_calibration_bundle(
    calibration: PinchCalibrationResult,
    wrist_calibration: WristRotationCalibrationResult | None,
    *,
    reuse_config: CalibrationReuseConfig,
    fallback_base_path: Path | None,
) -> Path | None:
    target = reuse_config.calibration_out or fallback_base_path
    if target is None:
        return None
    requested_target = target
    target = _next_calibration_version_path(target)
    calibration_id = (
        target.stem
        if target != requested_target
        else reuse_config.calibration_id or target.stem
    )
    payload = {
        "format_version": 1,
        "calibration_id": calibration_id,
        "created_wall_time_iso": _now_iso(),
        "pinch_calibration": calibration.to_dict(),
        "wrist_rotation_calibration": (
            wrist_calibration.to_dict() if wrist_calibration is not None else None
        ),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def _next_calibration_version_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix or ".json"
    marker = "_v"
    prefix = stem
    start_version = 2
    if marker in stem:
        prefix_candidate, version_text = stem.rsplit(marker, 1)
        if version_text.isdigit():
            prefix = prefix_candidate
            start_version = int(version_text) + 1
    for version in range(start_version, 1000):
        candidate = path.with_name(f"{prefix}_v{version:02d}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find free calibration version for {path}")


def _run_live_calibration_quick_check(
    server: LiveRawStreamServer,
    parser: ManusOnlyPinchInput,
    logger: DualTaskLogger,
    *,
    calibration: PinchCalibrationResult,
    wrist_calibration: WristRotationCalibrationResult | None,
    reuse_config: CalibrationReuseConfig,
    wrist_rotation_config: WristRotationConfig,
    session_id: str,
    save_raw_frames: bool,
    tcp_log_state: ManusTcpLogState | None,
    min_valid_frames: int,
    flush_events: list[dict[str, Any]] | None = None,
) -> CalibrationQuickCheckResult:
    _prompt_enter_or_abort(
        "Calibration quick check: press Enter, then keep hand open and wrist neutral..."
    )
    open_samples = _collect_live_calibration_samples(
        server,
        parser,
        logger,
        session_id=session_id,
        duration_s=reuse_config.quick_check_duration_s,
        save_raw_frames=save_raw_frames,
        tcp_log_state=tcp_log_state,
        phase="quick_check_open",
        flush_events=flush_events,
    )
    pinch_result = _pinch_open_quick_check_from_samples(
        open_samples,
        calibration=calibration,
        min_valid_frames=min_valid_frames,
        open_mad_multiplier=reuse_config.open_mad_multiplier,
    )
    if not pinch_result.passed:
        return pinch_result
    if not wrist_rotation_config.enabled:
        return pinch_result
    if wrist_calibration is None or not wrist_calibration.calibration_passed:
        return replace(
            pinch_result,
            passed=False,
            reason="missing_or_failed_wrist_calibration_in_bundle",
            wrist_checked=True,
        )
    quaternions = _collect_live_wrist_quaternions(
        server,
        logger,
        config=wrist_rotation_config,
        duration_s=reuse_config.quick_check_duration_s,
        save_raw_frames=save_raw_frames,
        tcp_log_state=tcp_log_state,
        phase="quick_check_wrist_neutral",
        flush_events=flush_events,
    )
    wrist_result = _wrist_neutral_quick_check_from_quaternions(
        quaternions,
        calibration=wrist_calibration,
        min_valid_frames=wrist_rotation_config.min_valid_frames,
        min_neutral_ratio=reuse_config.wrist_neutral_min_ratio,
    )
    return replace(
        pinch_result,
        passed=pinch_result.passed and wrist_result["passed"],
        reason=wrist_result["reason"],
        wrist_checked=True,
        wrist_valid_frame_count=wrist_result["valid_count"],
        wrist_neutral_count=wrist_result["neutral_count"],
        wrist_neutral_ratio=wrist_result["neutral_ratio"],
    )


def _pinch_open_quick_check_from_samples(
    samples: Iterable[Any],
    *,
    calibration: PinchCalibrationResult,
    min_valid_frames: int,
    open_mad_multiplier: float,
) -> CalibrationQuickCheckResult:
    distances = _valid_pinch_distances(samples)
    if len(distances) < int(min_valid_frames):
        return CalibrationQuickCheckResult(
            enabled=True,
            passed=False,
            reason="not_enough_valid_open_quick_check_frames",
            open_valid_frame_count=len(distances),
        )
    reference_median = calibration.open_distance_median
    reference_mad = calibration.open_distance_mad
    if reference_median is None or reference_mad is None or float(reference_mad) <= 0.0:
        return CalibrationQuickCheckResult(
            enabled=True,
            passed=False,
            reason="missing_open_reference_mad",
            open_valid_frame_count=len(distances),
        )
    current_median = median(distances)
    current_mad = median([abs(value - current_median) for value in distances])
    tolerance = float(reference_mad) * float(open_mad_multiplier)
    delta = abs(float(current_median) - float(reference_median))
    reason = ""
    if delta > tolerance:
        reason = "open_distance_shifted_from_reference"
    elif current_mad > tolerance:
        reason = "open_distance_unstable"
    return CalibrationQuickCheckResult(
        enabled=True,
        passed=not reason,
        reason=reason,
        open_valid_frame_count=len(distances),
        open_distance_median=float(current_median),
        open_distance_mad=float(current_mad),
        open_distance_delta=float(delta),
        open_distance_tolerance=float(tolerance),
    )


def _wrist_neutral_quick_check_from_quaternions(
    quaternions: Iterable[Any],
    *,
    calibration: WristRotationCalibrationResult,
    min_valid_frames: int,
    min_neutral_ratio: float,
) -> dict[str, Any]:
    valid_count = 0
    neutral_count = 0
    for q in quaternions:
        sample = classify_wrist_rotation(q, calibration)
        lr_neutral = (
            sample.wrist_rotation_valid
            and sample.wrist_rotation_class == "neutral"
        )
        ud_required = bool(calibration.up_down_calibration_passed)
        ud_neutral = (
            not ud_required
            or (
                sample.wrist_up_down_valid
                and sample.wrist_up_down_class == "neutral"
            )
        )
        if sample.wrist_rotation_valid:
            valid_count += 1
        if lr_neutral and ud_neutral:
            neutral_count += 1
    ratio = neutral_count / valid_count if valid_count > 0 else None
    reason = ""
    if valid_count < int(min_valid_frames):
        reason = "not_enough_valid_wrist_quick_check_frames"
    elif ratio is None or ratio < float(min_neutral_ratio):
        reason = "wrist_not_neutral_enough_for_saved_calibration"
    return {
        "passed": not reason,
        "reason": reason,
        "valid_count": valid_count,
        "neutral_count": neutral_count,
        "neutral_ratio": ratio,
    }


def _valid_pinch_distances(samples: Iterable[Any]) -> list[float]:
    distances: list[float] = []
    for sample in samples:
        if not bool(getattr(sample, "pinch_valid", False)):
            continue
        value = getattr(sample, "pinch_distance", None)
        try:
            distance = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(distance) and distance > 0.0:
            distances.append(distance)
    return distances


def _dataclass_from_dict(cls: Any, payload: dict[str, Any]) -> Any:
    allowed = {item.name for item in fields(cls)}
    return cls(**{key: value for key, value in payload.items() if key in allowed})


def _active_calibration_id(
    *,
    calibration_bundle: CalibrationBundle | None,
    reuse_config: CalibrationReuseConfig,
    saved_path: str,
    loaded: bool,
) -> str:
    if loaded and calibration_bundle is not None:
        return calibration_bundle.calibration_id
    if saved_path:
        return Path(saved_path).stem
    if reuse_config.calibration_id:
        return reuse_config.calibration_id
    return ""


def _positive_config_float(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be positive.") from exc
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be positive.")
    return result


def _ratio_config_float(value: Any, name: str) -> float:
    result = _positive_config_float(value, name)
    if result > 1.0:
        raise ValueError(f"{name} must be between 0 and 1.")
    return result


def _prompt_enter_or_abort(prompt: str) -> None:
    response = input(f"{prompt} [Enter/q] ")
    if str(response).strip().lower() in {"q", "quit", "exit", "abort"}:
        raise OperatorAbort("operator_aborted")


def _flush_manus_queue(
    server: LiveRawStreamServer,
    *,
    phase: str,
    flush_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    latest_before = _latest_received_frame_index(server)
    drained = server.drain_frames()
    event = {
        "phase": str(phase),
        "queue_depth_before_flush": len(drained),
        "flushed_count": len(drained),
        "last_flushed_frame_index": (
            drained[-1].frame_index if drained else None
        ),
        "latest_received_frame_index_before_flush": latest_before,
        "first_frame_index_after_flush": None,
        "queue_depth_after_flush": _queue_depth(server),
    }
    if flush_events is not None:
        flush_events.append(event)
    if drained:
        print(f"[MANUS TCP] flushed {len(drained)} queued frames before {phase}")
    return event


def _mark_first_frame_after_flush(
    flush_info: dict[str, Any],
    frame: Any,
) -> int | None:
    frame_index = getattr(frame, "frame_index", None)
    if flush_info.get("first_frame_index_after_flush") is None:
        flush_info["first_frame_index_after_flush"] = frame_index
    return flush_info.get("first_frame_index_after_flush")


def _frame_age_ms(frame: Any, *, now_s: float | None = None) -> float | None:
    receive_s = getattr(frame, "receive_time_monotonic", None)
    if receive_s is None:
        return None
    age = ((time.monotonic() if now_s is None else float(now_s)) - float(receive_s)) * 1000.0
    if not math.isfinite(age):
        return None
    return max(0.0, age)


def _collect_live_calibration_samples(
    server: LiveRawStreamServer,
    parser: ManusOnlyPinchInput,
    logger: DualTaskLogger,
    *,
    session_id: str,
    duration_s: float,
    save_raw_frames: bool,
    phase: str,
    tcp_log_state: ManusTcpLogState | None,
    flush_events: list[dict[str, Any]] | None = None,
) -> list[PinchInputSample]:
    flush_info = _flush_manus_queue(
        server,
        phase=phase,
        flush_events=flush_events,
    )
    queue_depth_at_phase_start = _queue_depth(server)
    deadline = time.monotonic() + float(duration_s)
    samples: list[PinchInputSample] = []
    while time.monotonic() < deadline:
        queue_depth_before_read = _queue_depth(server)
        latest_received_frame_index = _latest_received_frame_index(server)
        frame = _get_manus_frame(server, timeout=0.1, log_state=tcp_log_state)
        if frame is None:
            continue
        first_frame_index_after_flush = _mark_first_frame_after_flush(flush_info, frame)
        frame_age_ms = _frame_age_ms(frame)
        raw = _raw_from_live_frame(frame)
        if save_raw_frames:
            logger.write_raw_frame(raw)
        sample = parser.parse_sample(frame, session_id=session_id)
        samples.append(sample)
        logger.write_calibration_sample(
            sample,
            phase=phase,
            queue_depth=queue_depth_before_read,
            queue_depth_at_phase_start=queue_depth_at_phase_start,
            queue_depth_before_flush=flush_info["queue_depth_before_flush"],
            flushed_count=flush_info["flushed_count"],
            first_frame_index_after_flush=first_frame_index_after_flush,
            latest_received_frame_index=latest_received_frame_index,
            frame_age_ms=frame_age_ms,
        )
    return samples


def _queue_depth(server: LiveRawStreamServer) -> int:
    return int(server.queue_size())


def _latest_received_frame_index(server: LiveRawStreamServer) -> int | None:
    total = int(server.stats_snapshot().total_received_frames)
    if total <= 0:
        return None
    return total - 1


def _run_live_wrist_rotation_calibration(
    server: LiveRawStreamServer,
    logger: DualTaskLogger,
    *,
    config: WristRotationConfig,
    session_id: str,
    save_raw_frames: bool,
    tcp_log_state: ManusTcpLogState | None = None,
    flush_events: list[dict[str, Any]] | None = None,
) -> WristRotationCalibrationResult:
    _prompt_enter_or_abort("Wrist neutral calibration: press Enter, then keep wrist neutral...")
    print("[WRIST] neutral calibration collecting...")
    neutral = _collect_live_wrist_quaternions(
        server,
        logger,
        config=config,
        duration_s=config.calibration_duration_s,
        save_raw_frames=save_raw_frames,
        tcp_log_state=tcp_log_state,
        phase="wrist_neutral",
        flush_events=flush_events,
    )
    _prompt_enter_or_abort("Wrist left calibration: press Enter, then rotate wrist left...")
    print("[WRIST] left calibration collecting...")
    left = _collect_live_wrist_quaternions(
        server,
        logger,
        config=config,
        duration_s=config.calibration_duration_s,
        save_raw_frames=save_raw_frames,
        tcp_log_state=tcp_log_state,
        phase="wrist_left",
        flush_events=flush_events,
    )
    _prompt_enter_or_abort("Wrist right calibration: press Enter, then rotate wrist right...")
    print("[WRIST] right calibration collecting...")
    right = _collect_live_wrist_quaternions(
        server,
        logger,
        config=config,
        duration_s=config.calibration_duration_s,
        save_raw_frames=save_raw_frames,
        tcp_log_state=tcp_log_state,
        phase="wrist_right",
        flush_events=flush_events,
    )
    up: list[tuple[float, float, float, float]] = []
    down: list[tuple[float, float, float, float]] = []
    if config.enable_up_down:
        _prompt_enter_or_abort("Wrist up calibration: press Enter, then move wrist up...")
        print("[WRIST] up calibration collecting...")
        up = _collect_live_wrist_quaternions(
            server,
            logger,
            config=config,
            duration_s=config.calibration_duration_s,
            save_raw_frames=save_raw_frames,
            tcp_log_state=tcp_log_state,
            phase="wrist_up",
            flush_events=flush_events,
        )
        _prompt_enter_or_abort("Wrist down calibration: press Enter, then move wrist down...")
        print("[WRIST] down calibration collecting...")
        down = _collect_live_wrist_quaternions(
            server,
            logger,
            config=config,
            duration_s=config.calibration_duration_s,
            save_raw_frames=save_raw_frames,
            tcp_log_state=tcp_log_state,
            phase="wrist_down",
            flush_events=flush_events,
        )
    result = calibrate_wrist_rotation(
        neutral,
        left,
        right,
        up_quaternions=up,
        down_quaternions=down,
        config=config,
    )
    if result.calibration_passed:
        print(f"[WRIST] calibration passed: threshold={result.threshold:.6f}")
    else:
        print(f"[WRIST] calibration failed: {result.failure_reason}")
    if config.enable_up_down:
        if result.up_down_calibration_passed:
            print(f"[WRIST] up/down calibration passed: threshold={result.up_down_threshold:.6f}")
        else:
            print(f"[WRIST] up/down calibration failed: {result.up_down_failure_reason}")
    if config.save_timeseries:
        print(f"[WRIST] writing {logger.paths.wrist_rotation_timeseries_csv.name}")
    return result


def _collect_live_wrist_quaternions(
    server: LiveRawStreamServer,
    logger: DualTaskLogger,
    *,
    config: WristRotationConfig,
    duration_s: float,
    save_raw_frames: bool,
    tcp_log_state: ManusTcpLogState | None = None,
    phase: str = "wrist",
    flush_events: list[dict[str, Any]] | None = None,
) -> list[tuple[float, float, float, float]]:
    flush_info = _flush_manus_queue(
        server,
        phase=phase,
        flush_events=flush_events,
    )
    deadline = time.monotonic() + float(duration_s)
    quaternions: list[tuple[float, float, float, float]] = []
    while time.monotonic() < deadline:
        frame = _get_manus_frame(server, timeout=0.1, log_state=tcp_log_state)
        if frame is None:
            continue
        _mark_first_frame_after_flush(flush_info, frame)
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
    nback_timeline: NBackTimeline | None,
    display: "_NBackPygameDisplay | None",
    session_id: str,
    save_raw_frames: bool,
    tcp_log_state: ManusTcpLogState | None = None,
    haptic_debug_config: HapticDebugConfig | None = None,
    session_end_policy: SessionEndPolicy | None = None,
    haptic_feedback_display: HapticFeedbackDisplayConfig | None = None,
    duration_s: float = 60.0,
    wrist_rotation_config: WristRotationConfig | None = None,
    wrist_rotation_calibration: WristRotationCalibrationResult | None = None,
    task_type: str = TASK_TYPE_DUAL,
    cue_dispatch_mode: str = CUE_DISPATCH_ZONE_SEQUENTIAL,
    flush_events: list[dict[str, Any]] | None = None,
) -> PinchHaptic1BackCoreResult:
    task = _normalize_task_type(task_type)
    dispatch_mode = _normalize_cue_dispatch_mode(cue_dispatch_mode)
    nback_enabled = task == TASK_TYPE_DUAL
    trial_gate_enabled = nback_enabled
    digit_guard_enabled = nback_enabled
    if nback_enabled and nback_timeline is None:
        raise ValueError("nback_timeline is required when task_type=dual.")
    if nback_enabled and display is None:
        raise ValueError("display is required when task_type=dual.")
    scheduler = _make_haptic_scheduler(
        plan,
        scheduler_config,
        cue_dispatch_mode=dispatch_mode,
    )
    policy = session_end_policy or SessionEndPolicy()
    feedback_config = haptic_feedback_display or HapticFeedbackDisplayConfig()
    episode_state = HapticEpisodeState()
    latest_sample: PinchInputSample | None = None
    latest_wrist_sample = None
    latest_zone = "invalid"
    previous_logged_zone = "invalid"
    total_haptic_events = 0
    zone_stats = ZoneRunStats()
    debug_config = haptic_debug_config or HapticDebugConfig()
    wrist_config = wrist_rotation_config or WristRotationConfig()
    flush_info = _flush_manus_queue(
        server,
        phase="formal_start",
        flush_events=flush_events,
    )
    queue_depth_at_formal_start = _queue_depth(server)
    latest_received_frame_index_at_formal_start = _latest_received_frame_index(server)
    max_queue_depth_during_formal = queue_depth_at_formal_start
    max_frame_age_ms_during_formal: float | None = None
    start_ms = time.monotonic() * 1000.0
    duration_deadline_ms = start_ms + max(0.0, float(duration_s)) * 1000.0
    if nback_enabled and nback_timeline is not None:
        nback_timeline.start(start_ms)
    end_reason = ""
    final_now_ms = start_ms
    post_release_started_ms: float | None = None
    post_release_end_ms: float | None = None
    post_release_pinch_samples = 0
    release_gate_state = ReleaseGateState()
    haptic_tcp_failed = False
    haptic_tcp_failure_errors: tuple[str, ...] = ()

    while True:
        now_ms = time.monotonic() * 1000.0
        nback_active = nback_enabled and _post_release_nback_active(post_release_started_ms, policy)
        if nback_enabled and display is not None and nback_timeline is not None:
            for key_name in display.poll_keydowns():
                if nback_active:
                    nback_timeline.record_response(key_name, now_ms)

        queue_depth_before_read = _queue_depth(server)
        max_queue_depth_during_formal = max(
            max_queue_depth_during_formal,
            queue_depth_before_read,
        )
        latest_received_frame_index = _latest_received_frame_index(server)
        frame = _get_manus_frame(server, timeout=0.0, log_state=tcp_log_state)
        while frame is not None:
            first_frame_index_after_flush = _mark_first_frame_after_flush(flush_info, frame)
            frame_age_ms = _frame_age_ms(frame)
            if frame_age_ms is not None:
                max_frame_age_ms_during_formal = (
                    frame_age_ms
                    if max_frame_age_ms_during_formal is None
                    else max(max_frame_age_ms_during_formal, frame_age_ms)
                )
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
            logger.write_pinch_sample(
                latest_sample,
                calibration=calibration,
                zone=latest_zone,
                phase="formal",
                queue_depth=queue_depth_before_read,
                queue_depth_at_phase_start=queue_depth_at_formal_start,
                queue_depth_before_flush=flush_info["queue_depth_before_flush"],
                flushed_count=flush_info["flushed_count"],
                first_frame_index_after_flush=first_frame_index_after_flush,
                latest_received_frame_index=latest_received_frame_index,
                frame_age_ms=frame_age_ms,
            )
            if (
                wrist_config.enabled
                and wrist_config.save_timeseries
                and wrist_rotation_calibration is not None
            ):
                latest_wrist_sample = classify_wrist_rotation_frame(
                    frame,
                    wrist_rotation_calibration,
                    quaternion_order=wrist_config.quaternion_order,
                    session_id=session_id,
                )
                logger.write_wrist_rotation_sample(latest_wrist_sample)
            if post_release_started_ms is not None:
                post_release_pinch_samples += 1
            queue_depth_before_read = _queue_depth(server)
            max_queue_depth_during_formal = max(
                max_queue_depth_during_formal,
                queue_depth_before_read,
            )
            latest_received_frame_index = _latest_received_frame_index(server)
            frame = _get_manus_frame(server, timeout=0.0, log_state=tcp_log_state)

        emitted: list[Any] = []
        if post_release_started_ms is None:
            if release_gate_state.pending_event is None:
                emitted = _advance_scheduler_for_current_state(
                    scheduler,
                    zone=latest_zone,
                    now_ms=now_ms,
                    latest_sample=latest_sample,
                    digit_onsets_ms=(
                        nback_timeline.digit_onsets_ms
                        if digit_guard_enabled and nback_timeline is not None
                        else None
                    ),
                    haptic_debug_config=debug_config,
                )
            if dispatch_mode == CUE_DISPATCH_TIMED_GROUPED:
                emitted = _annotate_timed_grouped_events(
                    emitted,
                    nback_timeline=nback_timeline,
                    now_ms=now_ms,
                    latest_zone=latest_zone,
                    latest_wrist_sample=latest_wrist_sample,
                )
            else:
                emitted = _gate_haptic_events(
                    emitted,
                    policy=policy,
                    gate_state=release_gate_state,
                    scheduler=scheduler,
                    nback_timeline=nback_timeline,
                    trial_gate_enabled=trial_gate_enabled,
                    now_ms=now_ms,
                    latest_zone=latest_zone,
                    latest_wrist_sample=latest_wrist_sample,
                )
            if trial_gate_enabled and dispatch_mode == CUE_DISPATCH_ZONE_SEQUENTIAL:
                _append_prerelease_deadline_warning_if_needed(
                    policy=policy,
                    gate_state=release_gate_state,
                    scheduler=scheduler,
                    nback_timeline=nback_timeline,
                    now_ms=now_ms,
                    post_release_started_ms=post_release_started_ms,
                )
        for event in _ordered_haptic_events_for_send(emitted):
            _record_haptic_event(
                event,
                sender=sender,
                episode_state=episode_state,
                feedback_config=feedback_config,
            )
        total_haptic_events += len(emitted)
        sender.poll_due_control_commands(now_ms)
        haptic_tcp_failure_records = sender.tcp_failure_records()
        if haptic_tcp_failure_records:
            haptic_tcp_failed = True
            haptic_tcp_failure_errors = _haptic_tcp_failure_errors(sender)
            end_reason = "haptic_tcp_failed"
            episode_state.interrupted_haptic_trial = True
            final_now_ms = now_ms
            print("[HAPTIC TCP] send failed; stopping formal session.")
            break

        if nback_active:
            for row in nback_timeline.finalize_until(now_ms, session_id=session_id):
                logger.write_nback_event(row)
            tick = nback_timeline.tick(now_ms)
            display.draw(tick)
        elif nback_enabled and display is not None:
            display.draw(NBackTick(phase=NBACK_PHASE_COMPLETE, trial=None))

        if any(_event_should_end_session(event, policy) for event in emitted):
            release_event = next(event for event in emitted if _event_should_end_session(event, policy))
            post_release_started_ms = now_ms
            post_release_end_ms = now_ms + float(getattr(release_event, "duration_ms", 0) or 0) + policy.post_release_recording_ms
            end_reason = "haptic_release_post_recording"
        if _post_release_complete(
            policy=policy,
            nback_timeline=nback_timeline,
            nback_enabled=nback_enabled,
            now_ms=now_ms,
            post_release_end_ms=post_release_end_ms,
        ):
            end_reason = _post_release_complete_reason(policy)
            final_now_ms = now_ms
            break
        if post_release_end_ms is not None:
            _formal_phase_tick(display)
            continue
        nback_complete = nback_enabled and nback_timeline is not None and nback_timeline.is_complete(now_ms)
        duration_elapsed = now_ms >= duration_deadline_ms
        if nback_complete or duration_elapsed:
            if (
                (
                    _haptic_sequence_active(scheduler, episode_state)
                    or release_gate_state.pending_event is not None
                )
                and policy.finish_active_haptic_before_exit
            ):
                _formal_phase_tick(display)
                continue
            end_reason = "nback_complete" if nback_complete else "duration_elapsed"
            if (
                _haptic_sequence_active(scheduler, episode_state)
                or release_gate_state.pending_event is not None
            ) and not policy.finish_active_haptic_before_exit:
                episode_state.interrupted_haptic_trial = True
            final_now_ms = now_ms
            break
        _formal_phase_tick(display)

    final_nback_ms = (
        final_now_ms
        if post_release_started_ms is None or policy.post_release_continue_nback
        else post_release_started_ms
    )
    if nback_enabled and nback_timeline is not None:
        for row in nback_timeline.finalize_until(final_nback_ms, session_id=session_id):
            logger.write_nback_event(row)
    sender.poll_due_control_commands(final_now_ms)
    haptic_tcp_failure_records = sender.tcp_failure_records()
    if haptic_tcp_failure_records:
        haptic_tcp_failed = True
        haptic_tcp_failure_errors = _haptic_tcp_failure_errors(sender)
        if not end_reason:
            end_reason = "haptic_tcp_failed"
    zone_stats.finalize(final_now_ms)
    sender.write_csv(logger.paths.haptic_events_csv)
    logger.write_nback_events([])
    return PinchHaptic1BackCoreResult(
        total_pinch_samples=logger.total_pinch_samples,
        total_valid_pinch_samples=logger.total_valid_pinch_samples,
        total_haptic_events=total_haptic_events,
        total_nback_trials=logger.total_nback_trials,
        total_nback_responses=logger.total_nback_responses,
        session_should_end=_is_release_end_reason(end_reason),
        end_reason=end_reason,
        haptic_episode_completed=episode_state.completed,
        haptic_trial_count=episode_state.haptic_trial_count,
        last_haptic_event_name=episode_state.last_haptic_event_name,
        interrupted_haptic_trial=episode_state.interrupted_haptic_trial,
        allow_multiple_haptic_trials=policy.allow_multiple_haptic_trials,
        finish_active_haptic_before_exit=policy.finish_active_haptic_before_exit,
        post_release_recording_ms=policy.post_release_recording_ms,
        post_release_continue_nback=policy.post_release_continue_nback,
        release_nback_trial_window=policy.release_nback_trial_window,
        prerelease_haptic_complete_by_trial=policy.prerelease_haptic_complete_by_trial,
        hold_release_until_nback_trial=policy.hold_release_until_nback_trial,
        finish_nback_after_haptic_release=policy.finish_nback_after_haptic_release,
        post_release_started_ms=post_release_started_ms,
        post_release_end_ms=post_release_end_ms,
        post_release_pinch_samples=post_release_pinch_samples,
        release_was_held=release_gate_state.release_was_held,
        release_emit_trial_number=release_gate_state.release_emit_trial_number,
        haptic_policy_warnings=tuple(release_gate_state.warnings),
        task_type=task,
        nback_enabled=nback_enabled,
        trial_gate_enabled=trial_gate_enabled,
        digit_guard_enabled=digit_guard_enabled,
        **zone_stats.to_dict(),
        queue_depth_at_formal_start=queue_depth_at_formal_start,
        queue_depth_before_formal_flush=flush_info["queue_depth_before_flush"],
        flushed_count_at_formal_start=flush_info["flushed_count"],
        first_frame_index_after_formal_flush=flush_info["first_frame_index_after_flush"],
        latest_received_frame_index_at_formal_start=latest_received_frame_index_at_formal_start,
        max_queue_depth_during_formal=max_queue_depth_during_formal,
        max_frame_age_ms_during_formal=max_frame_age_ms_during_formal,
        haptic_tcp_failed=haptic_tcp_failed,
        haptic_tcp_failure_count=len(haptic_tcp_failure_records),
        haptic_tcp_failure_errors=haptic_tcp_failure_errors,
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
    nback_timeline: NBackTimeline | None,
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
    if nback_timeline is not None:
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
    release_window = _optional_trial_window(
        session_config.get("release_nback_trial_window"),
        "session.release_nback_trial_window",
    )
    prerelease_deadline = _optional_positive_int(
        session_config.get("prerelease_haptic_complete_by_trial"),
        "session.prerelease_haptic_complete_by_trial",
    )
    if prerelease_deadline is not None and release_window is not None:
        if prerelease_deadline > release_window[1]:
            raise ValueError(
                "session.prerelease_haptic_complete_by_trial must be <= "
                "session.release_nback_trial_window upper bound."
            )
    return SessionEndPolicy(
        end_policy=str(session_config.get("end_policy", "stop_on_haptic_release")),
        allow_multiple_haptic_trials=bool(session_config.get("allow_multiple_haptic_trials", False)),
        finish_active_haptic_before_exit=bool(
            session_config.get("finish_active_haptic_before_exit", True)
        ),
        post_release_recording_ms=float(session_config.get("post_release_recording_ms", 0)),
        single_post_release_recording_ms=(
            float(session_config["single_post_release_recording_ms"])
            if session_config.get("single_post_release_recording_ms") is not None
            else None
        ),
        post_release_continue_nback=bool(session_config.get("post_release_continue_nback", False)),
        release_nback_trial_window=release_window,
        prerelease_haptic_complete_by_trial=prerelease_deadline,
        hold_release_until_nback_trial=bool(
            session_config.get("hold_release_until_nback_trial", False)
        ),
        finish_nback_after_haptic_release=bool(
            session_config.get("finish_nback_after_haptic_release", False)
        ),
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


def _optional_trial_window(value: Any, name: str) -> tuple[int, int] | None:
    if value is None:
        return None
    if not isinstance(value, list | tuple) or len(value) != 2:
        raise ValueError(f"{name} must be a two-item list.")
    lower = _positive_int_value(value[0], f"{name}[0]")
    upper = _positive_int_value(value[1], f"{name}[1]")
    if lower > upper:
        raise ValueError(f"{name} lower bound must be <= upper bound.")
    return lower, upper


def _optional_positive_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _positive_int_value(value, name)


def _positive_int_value(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer.")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if result <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return result


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


def _task_config_has_trial_gate_fields(
    plan: HapticPlanConfig,
    policy: SessionEndPolicy,
) -> bool:
    if (
        policy.release_nback_trial_window is not None
        or policy.prerelease_haptic_complete_by_trial is not None
        or policy.hold_release_until_nback_trial
        or policy.finish_nback_after_haptic_release
        or policy.post_release_continue_nback
    ):
        return True
    return any(getattr(event, "nback_trial_window", None) is not None for event in plan.events)


def _session_end_policy_for_task(
    policy: SessionEndPolicy,
    task_type: str,
) -> SessionEndPolicy:
    if _normalize_task_type(task_type) == TASK_TYPE_DUAL:
        return policy
    return replace(
        policy,
        post_release_recording_ms=(
            policy.single_post_release_recording_ms
            if policy.single_post_release_recording_ms is not None
            else policy.post_release_recording_ms
        ),
        post_release_continue_nback=False,
        finish_nback_after_haptic_release=False,
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
        "pinch_reference_quality_passed": calibration.pinch_reference_quality_passed,
        "pinch_reference_quality_reason": calibration.pinch_reference_quality_reason,
        "open_distance_median": calibration.open_distance_median,
        "contact_distance_median": calibration.contact_distance_median,
        "pinch_distance_median": calibration.pinch_distance_median,
        "open_contact_boundary": calibration.open_contact_boundary,
        "contact_pinch_boundary": calibration.contact_pinch_boundary,
    }


def _should_enter_formal_phase(calibration: PinchCalibrationResult) -> bool:
    return bool(calibration.calibration_passed)


def _calibration_reuse_block_reason(calibration: PinchCalibrationResult) -> str:
    if not bool(getattr(calibration, "calibration_passed", False)):
        reason = str(getattr(calibration, "calibration_failure_reason", "") or "")
        return "loaded_calibration_failed" + (f":{reason}" if reason else "")
    if not bool(getattr(calibration, "pinch_reference_quality_passed", False)):
        reason = str(getattr(calibration, "pinch_reference_quality_reason", "") or "")
        return "loaded_pinch_reference_quality_failed" + (
            f":{reason}" if reason else ""
        )
    return ""


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
            "single_post_release_recording_ms": policy.single_post_release_recording_ms,
            "post_release_continue_nback": policy.post_release_continue_nback,
            "release_nback_trial_window": _list_or_none(policy.release_nback_trial_window),
            "prerelease_haptic_complete_by_trial": policy.prerelease_haptic_complete_by_trial,
            "hold_release_until_nback_trial": policy.hold_release_until_nback_trial,
            "finish_nback_after_haptic_release": policy.finish_nback_after_haptic_release,
            "post_release_started_ms": None,
            "post_release_end_ms": None,
            "post_release_pinch_samples": 0,
            "release_was_held": False,
            "release_emit_trial_number": None,
            "queue_depth_at_formal_start": None,
            "queue_depth_before_formal_flush": None,
            "flushed_count_at_formal_start": None,
            "first_frame_index_after_formal_flush": None,
            "latest_received_frame_index_at_formal_start": None,
            "max_queue_depth_during_formal": None,
            "max_frame_age_ms_during_formal": None,
            "haptic_tcp_failed": False,
            "haptic_tcp_failure_count": 0,
            "haptic_tcp_failure_errors": [],
            "haptic_policy_warnings": [],
            "cue_dispatch_mode": CUE_DISPATCH_ZONE_SEQUENTIAL,
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
        "single_post_release_recording_ms": policy.single_post_release_recording_ms,
        "post_release_continue_nback": result.post_release_continue_nback,
        "release_nback_trial_window": _list_or_none(result.release_nback_trial_window),
        "prerelease_haptic_complete_by_trial": result.prerelease_haptic_complete_by_trial,
        "hold_release_until_nback_trial": result.hold_release_until_nback_trial,
        "finish_nback_after_haptic_release": result.finish_nback_after_haptic_release,
        "post_release_started_ms": result.post_release_started_ms,
        "post_release_end_ms": result.post_release_end_ms,
        "post_release_pinch_samples": result.post_release_pinch_samples,
        "queue_depth_at_formal_start": result.queue_depth_at_formal_start,
        "queue_depth_before_formal_flush": result.queue_depth_before_formal_flush,
        "flushed_count_at_formal_start": result.flushed_count_at_formal_start,
        "first_frame_index_after_formal_flush": (
            result.first_frame_index_after_formal_flush
        ),
        "latest_received_frame_index_at_formal_start": (
            result.latest_received_frame_index_at_formal_start
        ),
        "max_queue_depth_during_formal": result.max_queue_depth_during_formal,
        "max_frame_age_ms_during_formal": result.max_frame_age_ms_during_formal,
        "haptic_tcp_failed": result.haptic_tcp_failed,
        "haptic_tcp_failure_count": result.haptic_tcp_failure_count,
        "haptic_tcp_failure_errors": list(result.haptic_tcp_failure_errors),
        "release_was_held": result.release_was_held,
        "release_emit_trial_number": result.release_emit_trial_number,
        "haptic_policy_warnings": list(result.haptic_policy_warnings),
        "task_type": result.task_type,
        "cue_dispatch_mode": result.cue_dispatch_mode,
        "nback_enabled": result.nback_enabled,
        "trial_gate_enabled": result.trial_gate_enabled,
        "digit_guard_enabled": result.digit_guard_enabled,
    }


def _haptic_tcp_failure_errors(sender: SimpleHapticSender) -> tuple[str, ...]:
    errors: list[str] = []
    seen: set[str] = set()
    for record in sender.tcp_failure_records():
        text = str(record.tcp_error or record.not_sent_reason or record.send_status or "")
        if not text or text in seen:
            continue
        seen.add(text)
        errors.append(text)
        if len(errors) >= 5:
            break
    return tuple(errors)


def _final_summary_end_reason(
    end_reason: str,
    formal_result: PinchHaptic1BackCoreResult | None,
) -> str:
    if str(end_reason):
        return str(end_reason)
    if formal_result is None:
        return "formal_not_started"
    return str(formal_result.end_reason or "")


def _should_append_no_haptic_event_warnings(
    formal_result: PinchHaptic1BackCoreResult | None,
    sender_record_count: int,
) -> bool:
    return formal_result is not None and int(sender_record_count) == 0


def _list_or_none(value: tuple[int, int] | None) -> list[int] | None:
    if value is None:
        return None
    return [int(value[0]), int(value[1])]


def _bool_config_value(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1", "on"}:
            return True
        if normalized in {"false", "no", "n", "0", "off"}:
            return False
    raise ValueError(f"{name} must be true or false.")


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


def _haptic_policy_warnings_from_result(
    result: PinchHaptic1BackCoreResult | None,
) -> list[str]:
    if result is None:
        return []
    return list(result.haptic_policy_warnings)


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


def _nback_trial_number_at(
    nback_timeline: NBackTimeline,
    now_ms: float,
) -> int:
    """Return the 1-based trial number active/reached at now_ms."""

    trials = nback_timeline.trials
    if trials and now_ms >= trials[-1].response_window_end_monotonic_ms:
        return len(trials) + 1
    trial_number = 0
    for trial in trials:
        if now_ms + 1e-9 < trial.fixation_onset_monotonic_ms:
            break
        trial_number = int(trial.stimulus_index) + 1
        if now_ms < trial.response_window_end_monotonic_ms:
            break
    return trial_number


def _required_nback_trial_number_at(
    nback_timeline: NBackTimeline | None,
    now_ms: float,
) -> int:
    if nback_timeline is None:
        raise ValueError("nback_timeline is required when trial gate is enabled.")
    return _nback_trial_number_at(nback_timeline, now_ms)


def _normalize_task_type(value: Any) -> str:
    task_type = str(value if value is not None else TASK_TYPE_DUAL).strip().lower()
    if task_type == "tactile_only":
        return TASK_TYPE_SINGLE
    if task_type not in {TASK_TYPE_DUAL, TASK_TYPE_SINGLE}:
        raise ValueError("session.task_type must be dual or single.")
    return task_type


def _normalize_cue_dispatch_mode(value: Any) -> str:
    mode = str(value if value is not None else CUE_DISPATCH_ZONE_SEQUENTIAL).strip().lower()
    if mode not in CUE_DISPATCH_MODES:
        raise ValueError(
            "session.cue_dispatch_mode must be one of: "
            + ", ".join(sorted(CUE_DISPATCH_MODES))
        )
    return mode


def _make_haptic_scheduler(
    plan: HapticPlanConfig,
    scheduler_config: HapticTrialSchedulerConfig,
    *,
    cue_dispatch_mode: str,
) -> Any:
    if cue_dispatch_mode == CUE_DISPATCH_TIMED_GROUPED:
        return TimedGroupedHapticScheduler(plan, scheduler_config)
    return HapticTrialScheduler(plan, scheduler_config)


def _formal_phase_tick(display: Any | None) -> None:
    if display is not None:
        display.tick(60)
    else:
        time.sleep(1.0 / 60.0)


def _gate_haptic_events(
    events: list[Any],
    *,
    policy: SessionEndPolicy,
    gate_state: ReleaseGateState,
    scheduler: HapticTrialScheduler,
    nback_timeline: NBackTimeline | None,
    trial_gate_enabled: bool,
    now_ms: float,
    latest_zone: str,
    latest_wrist_sample: Any | None,
) -> list[Any]:
    ready: list[Any] = []
    if gate_state.pending_event is not None:
        released = _release_pending_gate_event_if_ready(
            policy=policy,
            gate_state=gate_state,
            scheduler=scheduler,
            nback_timeline=nback_timeline,
            trial_gate_enabled=trial_gate_enabled,
            now_ms=now_ms,
            latest_zone=latest_zone,
            latest_wrist_sample=latest_wrist_sample,
        )
        if released is None:
            return ready
        ready.append(released)
    for event in events:
        released = _gate_single_haptic_event(
            event,
            policy=policy,
            gate_state=gate_state,
            scheduler=scheduler,
            nback_timeline=nback_timeline,
            trial_gate_enabled=trial_gate_enabled,
            now_ms=now_ms,
            latest_zone=latest_zone,
            latest_wrist_sample=latest_wrist_sample,
        )
        if released is None:
            break
        ready.append(released)
    return ready


def _annotate_timed_grouped_events(
    events: list[Any],
    *,
    nback_timeline: NBackTimeline | None,
    now_ms: float,
    latest_zone: str,
    latest_wrist_sample: Any | None,
) -> list[Any]:
    if not events:
        return []
    emit_trial = (
        _nback_trial_number_at(nback_timeline, now_ms)
        if nback_timeline is not None
        else None
    )
    annotated: list[Any] = []
    for event in events:
        timing_note = str(getattr(event, "timing_note", "") or "")
        notes = [item for item in (timing_note, "timed_grouped_no_zone_gate") if item]
        annotated.append(
            replace(
                event,
                actual_zone_at_emit=str(latest_zone),
                emit_trial_number=emit_trial,
                trial_gate_enabled=False,
                trial_gate_ignored=getattr(event, "nback_trial_window", None) is not None,
                wrist_neutral_gate_required=False,
                held_by_wrist_neutral_gate=False,
                wrist_neutral_gate_passed=None,
                wrist_neutral_wait_ms=None,
                wrist_lr_class_at_emit=_wrist_lr_class(latest_wrist_sample),
                wrist_up_down_class_at_emit=_wrist_up_down_class(latest_wrist_sample),
                timing_note=";".join(notes),
            )
        )
    return annotated


def _ordered_haptic_events_for_send(events: list[Any]) -> list[Any]:
    if not events:
        return []
    grouped = any(str(getattr(event, "simultaneous_group", "") or "") for event in events)
    if not grouped:
        return list(events)
    return sorted(
        events,
        key=lambda event: (
            0 if str(getattr(event, "modality", "")) == "vibration" else 1,
            int(getattr(event, "event_index", 0)),
        ),
    )


def _gate_single_haptic_event(
    event: Any,
    *,
    policy: SessionEndPolicy,
    gate_state: ReleaseGateState,
    scheduler: HapticTrialScheduler,
    nback_timeline: NBackTimeline | None,
    trial_gate_enabled: bool,
    now_ms: float,
    latest_zone: str,
    latest_wrist_sample: Any | None,
) -> Any | None:
    time_ready_ms = float(now_ms)
    explicit_trial_window = _event_trial_window(event, policy)
    trial_window = explicit_trial_window if trial_gate_enabled else None
    trial_gate_ignored = bool(explicit_trial_window is not None and not trial_gate_enabled)
    planned_trial = (
        _required_nback_trial_number_at(nback_timeline, time_ready_ms)
        if trial_gate_enabled
        else None
    )
    if trial_window is not None:
        lower, upper = trial_window
        if planned_trial < lower:
            _store_pending_gate_event(
                event,
                gate_state=gate_state,
                time_ready_ms=time_ready_ms,
                planned_trial=planned_trial,
                trial_window=trial_window,
                held_by_trial_gate=True,
                held_by_wrist_neutral_gate=False,
            )
            if str(getattr(event, "event_name", "")) == "release":
                gate_state.release_was_held = True
            return None
    if _event_requires_wrist_neutral(event) and not _wrist_neutral_gate_passed(latest_wrist_sample):
        _store_pending_gate_event(
            event,
            gate_state=gate_state,
            time_ready_ms=time_ready_ms,
            planned_trial=planned_trial,
            trial_window=trial_window,
            trial_gate_ignored=trial_gate_ignored,
            held_by_trial_gate=False,
            held_by_wrist_neutral_gate=True,
            wrist_neutral_gate_passed=False,
        )
        return None
    return _event_ready_for_emit(
        event,
        policy=policy,
        gate_state=gate_state,
        scheduler=scheduler,
        nback_timeline=nback_timeline,
        trial_gate_enabled=trial_gate_enabled,
        now_ms=now_ms,
        latest_zone=latest_zone,
        latest_wrist_sample=latest_wrist_sample,
        time_ready_ms=time_ready_ms,
        planned_trial=planned_trial,
        trial_window=trial_window,
        trial_gate_ignored=trial_gate_ignored,
        held_by_trial_gate=False,
        held_by_wrist_neutral_gate=False,
        wrist_neutral_gate_passed=(
            True if _event_requires_wrist_neutral(event) else None
        ),
    )


def _release_pending_gate_event_if_ready(
    *,
    policy: SessionEndPolicy,
    gate_state: ReleaseGateState,
    scheduler: HapticTrialScheduler,
    nback_timeline: NBackTimeline | None,
    trial_gate_enabled: bool,
    now_ms: float,
    latest_zone: str,
    latest_wrist_sample: Any | None,
) -> Any | None:
    event = gate_state.pending_event
    if event is None:
        return None
    trial_number = (
        _required_nback_trial_number_at(nback_timeline, now_ms)
        if trial_gate_enabled
        else None
    )
    if gate_state.pending_trial_gate_window is not None:
        lower, _ = gate_state.pending_trial_gate_window
        if trial_number is None:
            raise ValueError("trial gate pending without an active nback timeline.")
        if trial_number < lower:
            return None
    wrist_required = bool(gate_state.pending_wrist_neutral_gate_required)
    wrist_passed = _wrist_neutral_gate_passed(latest_wrist_sample)
    if wrist_required and not wrist_passed:
        timeout_ms = _event_wrist_neutral_timeout_ms(event)
        waited_ms = float(now_ms) - float(gate_state.pending_event_ready_ms or now_ms)
        if waited_ms < timeout_ms:
            gate_state.pending_held_by_wrist_neutral_gate = True
            gate_state.pending_wrist_neutral_gate_passed = False
            return None
    result = _event_ready_for_emit(
        event,
        policy=policy,
        gate_state=gate_state,
        scheduler=scheduler,
        nback_timeline=nback_timeline,
        trial_gate_enabled=trial_gate_enabled,
        now_ms=now_ms,
        latest_zone=latest_zone,
        latest_wrist_sample=latest_wrist_sample,
        time_ready_ms=float(gate_state.pending_event_ready_ms or now_ms),
        planned_trial=gate_state.pending_planned_emit_trial_number,
        trial_window=gate_state.pending_trial_gate_window,
        trial_gate_ignored=gate_state.pending_trial_gate_ignored,
        held_by_trial_gate=gate_state.pending_held_by_trial_gate,
        held_by_wrist_neutral_gate=gate_state.pending_held_by_wrist_neutral_gate,
        wrist_neutral_gate_passed=(
            wrist_passed if wrist_required else gate_state.pending_wrist_neutral_gate_passed
        ),
    )
    gate_state.pending_event = None
    gate_state.pending_event_ready_ms = None
    gate_state.pending_held_by_trial_gate = False
    gate_state.pending_held_by_wrist_neutral_gate = False
    gate_state.pending_planned_emit_trial_number = None
    gate_state.pending_trial_gate_window = None
    gate_state.pending_trial_gate_open_trial = None
    gate_state.pending_trial_gate_ignored = False
    gate_state.pending_late_window_warning = ""
    gate_state.pending_wrist_neutral_gate_required = False
    gate_state.pending_wrist_neutral_gate_passed = None
    return result


def _store_pending_gate_event(
    event: Any,
    *,
    gate_state: ReleaseGateState,
    time_ready_ms: float,
    planned_trial: int | None,
    trial_window: tuple[int, int] | None,
    trial_gate_ignored: bool = False,
    held_by_trial_gate: bool,
    held_by_wrist_neutral_gate: bool,
    wrist_neutral_gate_passed: bool | None = None,
) -> None:
    gate_state.pending_event = event
    gate_state.pending_event_ready_ms = float(time_ready_ms)
    gate_state.pending_planned_emit_trial_number = (
        int(planned_trial) if planned_trial is not None else None
    )
    gate_state.pending_trial_gate_window = trial_window
    gate_state.pending_trial_gate_open_trial = trial_window[0] if trial_window is not None else None
    gate_state.pending_trial_gate_ignored = bool(trial_gate_ignored)
    gate_state.pending_held_by_trial_gate = bool(held_by_trial_gate)
    gate_state.pending_held_by_wrist_neutral_gate = bool(held_by_wrist_neutral_gate)
    gate_state.pending_wrist_neutral_gate_required = _event_requires_wrist_neutral(event)
    gate_state.pending_wrist_neutral_gate_passed = wrist_neutral_gate_passed


def _event_ready_for_emit(
    event: Any,
    *,
    policy: SessionEndPolicy,
    gate_state: ReleaseGateState,
    scheduler: HapticTrialScheduler,
    nback_timeline: NBackTimeline | None,
    trial_gate_enabled: bool,
    now_ms: float,
    latest_zone: str,
    latest_wrist_sample: Any | None,
    time_ready_ms: float,
    planned_trial: int | None,
    trial_window: tuple[int, int] | None,
    trial_gate_ignored: bool = False,
    held_by_trial_gate: bool,
    held_by_wrist_neutral_gate: bool,
    wrist_neutral_gate_passed: bool | None,
) -> Any:
    emit_trial = (
        _required_nback_trial_number_at(nback_timeline, now_ms)
        if trial_gate_enabled
        else None
    )
    late_warning = ""
    if trial_window is not None and emit_trial is not None and emit_trial > trial_window[1]:
        late_warning = (
            f"{getattr(event, 'event_name', 'event')}_after_nback_trial_window_"
            f"{trial_window[0]}_{trial_window[1]}:trial_{emit_trial}"
        )
        _append_once(gate_state.warnings, late_warning)
    if str(getattr(event, "event_name", "")) == "release":
        gate_state.release_emit_trial_number = emit_trial
    duration_ms = float(getattr(event, "duration_ms", 0) or 0)
    timing_note = str(getattr(event, "timing_note", "") or "")
    notes: list[str] = []
    if held_by_trial_gate:
        notes.append("held_by_trial_gate")
    if held_by_wrist_neutral_gate:
        notes.append("held_by_wrist_neutral_gate")
    if notes:
        timing_note = ";".join([item for item in (timing_note, *notes) if item])
    _retime_scheduler_pending_after_gate_hold(
        scheduler,
        held_event=event,
        held_by_gate=held_by_trial_gate or held_by_wrist_neutral_gate,
        time_ready_ms=time_ready_ms,
        actual_emit_ms=now_ms,
    )
    return replace(
        event,
        actual_emit_monotonic_ms=float(now_ms),
        actual_emit_ms=float(now_ms),
        event_end_monotonic_ms=float(now_ms) + duration_ms,
        actual_zone_at_emit=str(latest_zone),
        time_ready_ms=float(time_ready_ms),
        planned_emit_trial_number=planned_trial,
        emit_trial_number=emit_trial,
        trial_gate_enabled=trial_gate_enabled,
        trial_gate_ignored=trial_gate_ignored,
        trial_gate_window=trial_window,
        trial_gate_open_trial=trial_window[0] if trial_window is not None else None,
        held_by_trial_gate=held_by_trial_gate,
        late_window_warning=late_warning,
        wrist_neutral_gate_required=_event_requires_wrist_neutral(event),
        held_by_wrist_neutral_gate=held_by_wrist_neutral_gate,
        wrist_neutral_gate_passed=wrist_neutral_gate_passed,
        wrist_neutral_wait_ms=(
            float(now_ms) - float(time_ready_ms)
            if held_by_wrist_neutral_gate
            else 0.0
            if _event_requires_wrist_neutral(event)
            else None
        ),
        wrist_lr_class_at_emit=_wrist_lr_class(latest_wrist_sample),
        wrist_up_down_class_at_emit=_wrist_up_down_class(latest_wrist_sample),
        timing_note=timing_note,
    )


def _retime_scheduler_pending_after_gate_hold(
    scheduler: HapticTrialScheduler,
    *,
    held_event: Any,
    held_by_gate: bool,
    time_ready_ms: float,
    actual_emit_ms: float,
) -> None:
    if not held_by_gate:
        return
    delay_ms = float(actual_emit_ms) - float(time_ready_ms)
    if delay_ms <= 1e-9:
        return
    pending = getattr(scheduler, "_pending", None)
    if pending is None:
        return
    if int(getattr(pending, "event_index", -1)) <= int(getattr(held_event, "event_index", -1)):
        return
    adjustment = getattr(pending, "adjustment", None)
    if adjustment is None:
        return
    scheduler._pending = replace(
        pending,
        adjustment=replace(
            adjustment,
            original_planned_onset_ms=float(adjustment.original_planned_onset_ms)
            + delay_ms,
            adjusted_onset_ms=float(adjustment.adjusted_onset_ms) + delay_ms,
        ),
    )


def _event_trial_window(
    event: Any,
    policy: SessionEndPolicy,
) -> tuple[int, int] | None:
    if (
        str(getattr(event, "event_name", "")) == "release"
        and policy.hold_release_until_nback_trial
        and policy.release_nback_trial_window is not None
    ):
        return policy.release_nback_trial_window
    value = getattr(event, "nback_trial_window", None)
    if value is None:
        return None
    return (int(value[0]), int(value[1]))


def _event_requires_wrist_neutral(event: Any) -> bool:
    return bool(getattr(event, "require_wrist_neutral_before_emit", False))


def _event_wrist_neutral_timeout_ms(event: Any) -> float:
    value = getattr(event, "wrist_neutral_timeout_ms", None)
    return float(value if value is not None else 3000.0)


def _wrist_neutral_gate_passed(sample: Any | None) -> bool:
    if sample is None:
        return False
    return (
        str(getattr(sample, "wrist_rotation_class", "unknown")) == "neutral"
        and str(getattr(sample, "wrist_up_down_class", "unknown")) == "neutral"
    )


def _wrist_lr_class(sample: Any | None) -> str:
    if sample is None:
        return ""
    return str(getattr(sample, "wrist_rotation_class", ""))


def _wrist_up_down_class(sample: Any | None) -> str:
    if sample is None:
        return ""
    return str(getattr(sample, "wrist_up_down_class", ""))


def _append_prerelease_deadline_warning_if_needed(
    *,
    policy: SessionEndPolicy,
    gate_state: ReleaseGateState,
    scheduler: HapticTrialScheduler,
    nback_timeline: NBackTimeline | None,
    now_ms: float,
    post_release_started_ms: float | None,
) -> None:
    deadline = policy.prerelease_haptic_complete_by_trial
    if (
        deadline is None
        or gate_state.prerelease_deadline_warning_written
        or post_release_started_ms is not None
        or gate_state.pending_event is not None
    ):
        return
    if _required_nback_trial_number_at(nback_timeline, now_ms) < deadline:
        return
    if _scheduler_is_waiting_for_release(scheduler):
        return
    gate_state.prerelease_deadline_warning_written = True
    gate_state.warnings.append(
        f"prerelease_haptic_not_complete_by_trial_{deadline}"
    )


def _scheduler_is_waiting_for_release(scheduler: HapticTrialScheduler) -> bool:
    pending = getattr(scheduler, "_pending", None)
    if pending is None:
        return False
    event = getattr(pending, "event", None)
    return str(getattr(event, "name", "")) == "release"


def _post_release_nback_active(
    post_release_started_ms: float | None,
    policy: SessionEndPolicy,
) -> bool:
    return (
        post_release_started_ms is None
        or policy.post_release_continue_nback
        or policy.finish_nback_after_haptic_release
    )


def _post_release_complete(
    *,
    policy: SessionEndPolicy,
    nback_timeline: NBackTimeline | None,
    nback_enabled: bool,
    now_ms: float,
    post_release_end_ms: float | None,
) -> bool:
    if post_release_end_ms is None or now_ms < post_release_end_ms:
        return False
    if policy.finish_nback_after_haptic_release:
        return bool(nback_enabled and nback_timeline is not None and nback_timeline.is_complete(now_ms))
    return True


def _post_release_complete_reason(policy: SessionEndPolicy) -> str:
    if policy.finish_nback_after_haptic_release:
        return "nback_complete_after_haptic_release"
    return "haptic_release_post_recording_complete"


def _record_haptic_event(
    event: Any,
    *,
    sender: SimpleHapticSender,
    episode_state: HapticEpisodeState,
    feedback_config: HapticFeedbackDisplayConfig,
    print_fn: Any = print,
) -> None:
    sender.record_scheduled_event(event)
    episode_state.observe(event)
    _print_haptic_feedback_if_needed(
        event,
        feedback_config,
        print_fn=print_fn,
    )


def _append_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _is_release_end_reason(end_reason: str) -> bool:
    return str(end_reason) in {
        "haptic_release",
        "haptic_release_post_recording",
        "haptic_release_post_recording_complete",
        "nback_complete_after_haptic_release",
    }


def _haptic_sequence_active(
    scheduler: HapticTrialScheduler,
    episode_state: HapticEpisodeState,
) -> bool:
    return bool(
        episode_state.active
        or getattr(scheduler, "state", "")
        in {"PENDING_CONTACT", "WAIT_CLOSED_ZONE", "PENDING_PLAN_EVENT", "PENDING_TIMED_GROUP"}
    )


def _end_reason_at_limit(
    *,
    nback_timeline: NBackTimeline | None,
    now_ms: float,
    episode_state: HapticEpisodeState,
    policy: SessionEndPolicy,
) -> str:
    if episode_state.active and not policy.finish_active_haptic_before_exit:
        episode_state.interrupted_haptic_trial = True
    if nback_timeline is not None and nback_timeline.is_complete(now_ms):
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
        print_fn("[HAPTIC] release emitted.")


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
