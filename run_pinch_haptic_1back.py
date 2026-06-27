"""MANUS pinch + disabled haptic scheduler + 1-back dual-task runner."""

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


DEFAULT_TICK_INTERVAL_MS = 10.0


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
    latest_sample: PinchInputSample | None = None
    latest_zone = "invalid"
    sample_index = 0
    response_index = 0
    total_haptic_events = 0
    now_ms = float(start_monotonic_ms)
    end_ms = float(end_monotonic_ms)

    while now_ms <= end_ms + 1e-9:
        while (
            sample_index < len(sample_list)
            and float(getattr(sample_list[sample_index], "monotonic_ms")) <= now_ms + 1e-9
        ):
            latest_sample = sample_list[sample_index]
            latest_zone = classify_pinch_zone(
                getattr(latest_sample, "pinch_distance", None),
                calibration,
            )
            logger.write_pinch_sample(latest_sample, calibration=calibration, zone=latest_zone)
            sample_index += 1

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

        emitted = _advance_scheduler_for_current_state(
            scheduler,
            zone=latest_zone,
            now_ms=now_ms,
            latest_sample=latest_sample,
            digit_onsets_ms=nback_timeline.digit_onsets_ms,
        )
        for event in emitted:
            haptic_sender.record_scheduled_event(event)
        total_haptic_events += len(emitted)

        for row in nback_timeline.finalize_until(now_ms, session_id=logger.session_id):
            logger.write_nback_event(row)

        next_ms = _next_loop_time_ms(
            now_ms=now_ms,
            end_ms=end_ms,
            tick_interval_ms=tick_interval,
            sample_list=sample_list,
            sample_index=sample_index,
            response_list=response_list,
            response_index=response_index,
            nback_timeline=nback_timeline,
            scheduler=scheduler,
        )
        if next_ms is None:
            break
        now_ms = next_ms

    for row in nback_timeline.finalize_until(end_ms, session_id=logger.session_id):
        logger.write_nback_event(row)
    logger.write_nback_events([])
    haptic_sender.write_csv(logger.paths.haptic_events_csv)
    return PinchHaptic1BackCoreResult(
        total_pinch_samples=logger.total_pinch_samples,
        total_valid_pinch_samples=logger.total_valid_pinch_samples,
        total_haptic_events=total_haptic_events,
        total_nback_trials=logger.total_nback_trials,
        total_nback_responses=logger.total_nback_responses,
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

    session_id = make_session_id(session_config.get("session_id_prefix", "pinch_haptic_1back"))
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
    sender_config = SimpleHapticSenderConfig(
        vibration_enabled=bool(haptic_config.get("vibration_enabled", False)),
        matrix_enabled=bool(haptic_config.get("matrix_enabled", False)),
        visual_text_cue_enabled=bool(haptic_config.get("visual_text_cue_enabled", False)),
        disabled_mode=True,
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
        result = _run_live_formal_phase(
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
        )
        total_haptic_events = result.total_haptic_events
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
        logger.write_summary(
            {
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
                "warnings": warnings,
                "errors": errors,
            }
        )
    print(f"Dual-task complete. Haptic events: {total_haptic_events}")
    return logger.session_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="MANUS pinch+haptic+1-back disabled runner.")
    parser.add_argument("--config", default="dualtask_config.yaml")
    args = parser.parse_args()
    run_live_pinch_haptic_1back(args.config)
    return 0


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
) -> PinchHaptic1BackCoreResult:
    scheduler = HapticTrialScheduler(plan, scheduler_config)
    latest_sample: PinchInputSample | None = None
    latest_zone = "invalid"
    total_haptic_events = 0
    nback_timeline.start(time.monotonic() * 1000.0)

    while True:
        now_ms = time.monotonic() * 1000.0
        for key_name in display.poll_keydowns():
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
            logger.write_pinch_sample(latest_sample, calibration=calibration, zone=latest_zone)
            frame = _get_manus_frame(server, timeout=0.0, log_state=tcp_log_state)

        emitted = _advance_scheduler_for_current_state(
            scheduler,
            zone=latest_zone,
            now_ms=now_ms,
            latest_sample=latest_sample,
            digit_onsets_ms=nback_timeline.digit_onsets_ms,
        )
        for event in emitted:
            sender.record_scheduled_event(event)
        total_haptic_events += len(emitted)

        for row in nback_timeline.finalize_until(now_ms, session_id=session_id):
            logger.write_nback_event(row)
        tick = nback_timeline.tick(now_ms)
        display.draw(tick)

        if nback_timeline.is_complete(now_ms):
            break
        display.tick(60)

    for row in nback_timeline.finalize_all(session_id=session_id):
        logger.write_nback_event(row)
    sender.write_csv(logger.paths.haptic_events_csv)
    logger.write_nback_events([])
    return PinchHaptic1BackCoreResult(
        total_pinch_samples=logger.total_pinch_samples,
        total_valid_pinch_samples=logger.total_valid_pinch_samples,
        total_haptic_events=total_haptic_events,
        total_nback_trials=logger.total_nback_trials,
        total_nback_responses=logger.total_nback_responses,
    )


def _advance_scheduler_for_current_state(
    scheduler: HapticTrialScheduler,
    *,
    zone: str,
    now_ms: float,
    latest_sample: PinchInputSample | None,
    digit_onsets_ms: Iterable[float] | None,
) -> list[Any]:
    events: list[Any] = []
    pinch_distance = (
        getattr(latest_sample, "pinch_distance", None) if latest_sample is not None else None
    )
    frame_index = (
        getattr(latest_sample, "frame_index", None) if latest_sample is not None else None
    )
    for _ in range(64):
        emitted = scheduler.update(
            zone=zone,
            now_ms=now_ms,
            pinch_distance=pinch_distance,
            frame_index=frame_index,
            digit_onsets_ms=digit_onsets_ms,
        )
        events.extend(emitted)
        pending_onset = _pending_onset_ms(scheduler)
        if pending_onset is None or pending_onset > now_ms:
            break
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
