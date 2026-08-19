"""Pure haptic trial scheduler state machine."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from haptic_plan_config import HapticPlanConfig, HapticPlanEvent


WAIT_OPEN_ZONE = "WAIT_OPEN_ZONE"
PENDING_CONTACT = "PENDING_CONTACT"
WAIT_CLOSED_ZONE = "WAIT_CLOSED_ZONE"
PENDING_PLAN_EVENT = "PENDING_PLAN_EVENT"
REFRACTORY = "REFRACTORY"
PENDING_TIMED_GROUP = "PENDING_TIMED_GROUP"

IF_CANNOT_AVOID_POLICIES = {"log_warning_and_send", "skip_event", "abort"}


class HapticOnsetConflictError(RuntimeError):
    """Raised when digit onset guard is configured to abort on conflict."""


@dataclass(frozen=True)
class HapticTrialSchedulerConfig:
    """Digit-onset guard settings for scheduler event onsets."""

    avoid_haptic_on_digit_onset: bool = True
    digit_onset_guard_ms: float = 150.0
    max_haptic_delay_ms: float = 500.0
    if_cannot_avoid: str = "log_warning_and_send"

    def __post_init__(self) -> None:
        if not isinstance(self.avoid_haptic_on_digit_onset, bool):
            raise ValueError("avoid_haptic_on_digit_onset must be true or false.")
        object.__setattr__(
            self,
            "digit_onset_guard_ms",
            _non_negative_float(self.digit_onset_guard_ms, "digit_onset_guard_ms"),
        )
        object.__setattr__(
            self,
            "max_haptic_delay_ms",
            _non_negative_float(self.max_haptic_delay_ms, "max_haptic_delay_ms"),
        )
        if self.if_cannot_avoid not in IF_CANNOT_AVOID_POLICIES:
            raise ValueError(
                "if_cannot_avoid must be one of: "
                + ", ".join(sorted(IF_CANNOT_AVOID_POLICIES))
            )


@dataclass(frozen=True)
class OnsetAdjustment:
    """Result of applying digit onset guard to one planned haptic onset."""

    original_planned_onset_ms: float
    adjusted_onset_ms: float
    nearest_digit_onset_ms: float | None
    digit_onset_delta_ms: float | None
    onset_was_delayed: bool
    sync_warning: str = ""
    should_skip: bool = False


@dataclass(frozen=True)
class ScheduledHapticEvent:
    """One haptic event emitted by the scheduler."""

    haptic_trial_index: int
    event_index: int
    event_name: str
    modality: str
    command_label: str | None
    command_id: int | None
    end_command_label: str | None = None
    end_command_id: int | None = None
    channel_list: tuple[int, ...] = field(default_factory=tuple)
    matrix_sequence: tuple[Any, ...] = field(default_factory=tuple)
    simultaneous_group: str = ""
    duration_ms: int = 0
    sampled_duration_ms: int | None = None
    global_default_used: bool = False
    trigger_zone: str = ""
    actual_zone_at_emit: str = ""
    trigger_pinch_distance: float | None = None
    trigger_frame_index: int | None = None
    actual_emit_monotonic_ms: float | None = None
    event_end_monotonic_ms: float | None = None
    original_planned_onset_ms: float = 0.0
    adjusted_onset_ms: float = 0.0
    nearest_digit_onset_ms: float | None = None
    digit_onset_delta_ms: float | None = None
    onset_was_delayed: bool = False
    sync_warning: str = ""
    sampled_delay_ms: int | None = None
    sampled_gap_ms: int | None = None
    nback_trial_window: tuple[int, int] | None = None
    require_wrist_neutral_before_emit: bool = False
    wrist_neutral_timeout_ms: int | None = None
    time_ready_ms: float | None = None
    actual_emit_ms: float | None = None
    planned_emit_trial_number: int | None = None
    emit_trial_number: int | None = None
    trial_gate_enabled: bool = True
    trial_gate_ignored: bool = False
    trial_gate_window: tuple[int, int] | None = None
    trial_gate_open_trial: int | None = None
    held_by_trial_gate: bool = False
    late_window_warning: str = ""
    wrist_neutral_gate_required: bool = False
    held_by_wrist_neutral_gate: bool = False
    wrist_neutral_gate_passed: bool | None = None
    wrist_neutral_wait_ms: float | None = None
    wrist_lr_class_at_emit: str = ""
    wrist_up_down_class_at_emit: str = ""
    timing_note: str = ""
    end_reason: str = ""
    haptic_episode_completed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["channel_list"] = list(self.channel_list)
        payload["matrix_sequence"] = [
            (
                step.to_dict()
                if hasattr(step, "to_dict")
                else {
                    "offset_ms": int(getattr(step, "offset_ms")),
                    "channel_list": list(getattr(step, "channel_list")),
                }
            )
            for step in self.matrix_sequence
        ]
        if self.nback_trial_window is not None:
            payload["nback_trial_window"] = list(self.nback_trial_window)
        return payload


@dataclass(frozen=True)
class _PendingEvent:
    event_index: int
    event: HapticPlanEvent
    adjustment: OnsetAdjustment
    sampled_duration_ms: int
    global_default_used: bool
    sampled_delay_ms: int | None = None
    sampled_gap_ms: int | None = None
    timing_note: str = ""


@dataclass(frozen=True)
class _TimedGroup:
    group_index: int
    event_index: int
    events: tuple[HapticPlanEvent, ...]
    simultaneous_group: str = ""


@dataclass(frozen=True)
class _PendingTimedGroup:
    group_index: int
    group: _TimedGroup
    adjustment: OnsetAdjustment
    sampled_durations_ms: tuple[int, ...]
    global_default_used: tuple[bool, ...]
    sampled_delay_ms: int | None = None
    sampled_gap_ms: int | None = None
    timing_note: str = ""

    @property
    def event_index(self) -> int:
        return self.group.event_index

    @property
    def event(self) -> HapticPlanEvent:
        return self.group.events[0]


def adjust_onset_away_from_digit_onsets(
    *,
    onset_ms: float,
    digit_onsets_ms: Iterable[float] | None = None,
    avoid_haptic_on_digit_onset: bool = True,
    guard_ms: float = 150.0,
    max_haptic_delay_ms: float = 500.0,
    if_cannot_avoid: str = "log_warning_and_send",
) -> OnsetAdjustment:
    """Delay one haptic onset until it is outside all digit-onset guard windows."""

    original = _finite_float(onset_ms, "onset_ms")
    guard = _non_negative_float(guard_ms, "guard_ms")
    max_delay = _non_negative_float(max_haptic_delay_ms, "max_haptic_delay_ms")
    if if_cannot_avoid not in IF_CANNOT_AVOID_POLICIES:
        raise ValueError(
            "if_cannot_avoid must be one of: "
            + ", ".join(sorted(IF_CANNOT_AVOID_POLICIES))
        )

    digit_onsets = sorted(_finite_float(value, "digit_onset") for value in (digit_onsets_ms or ()))
    nearest = _nearest_digit_onset(original, digit_onsets)
    delta = original - nearest if nearest is not None else None
    if not avoid_haptic_on_digit_onset or nearest is None or abs(delta) >= guard:
        return OnsetAdjustment(
            original_planned_onset_ms=original,
            adjusted_onset_ms=original,
            nearest_digit_onset_ms=nearest,
            digit_onset_delta_ms=delta,
            onset_was_delayed=False,
        )

    candidate = original
    while True:
        conflict = _first_conflicting_digit(candidate, digit_onsets, guard)
        if conflict is None:
            break
        candidate = conflict + guard
        if candidate - original > max_delay:
            warning = "haptic_onset_conflict_could_not_avoid_within_max_delay"
            if if_cannot_avoid == "abort":
                raise HapticOnsetConflictError(warning)
            return OnsetAdjustment(
                original_planned_onset_ms=original,
                adjusted_onset_ms=original,
                nearest_digit_onset_ms=nearest,
                digit_onset_delta_ms=delta,
                onset_was_delayed=False,
                sync_warning=warning,
                should_skip=if_cannot_avoid == "skip_event",
            )

    return OnsetAdjustment(
        original_planned_onset_ms=original,
        adjusted_onset_ms=candidate,
        nearest_digit_onset_ms=nearest,
        digit_onset_delta_ms=delta,
        onset_was_delayed=candidate > original,
    )


class HapticTrialScheduler:
    """Turn pinch zones and a haptic plan into scheduled haptic events."""

    def __init__(
        self,
        plan: HapticPlanConfig,
        config: HapticTrialSchedulerConfig | None = None,
        *,
        rng: random.Random | None = None,
    ) -> None:
        if not plan.events:
            raise ValueError("plan must contain at least one event.")
        missing_zone = [
            event.name for event in plan.events if not str(event.trigger_zone or "").strip()
        ]
        if missing_zone:
            raise ValueError(
                "zone_sequential haptic plan events require trigger_zone: "
                + ", ".join(missing_zone)
            )
        self.plan = plan
        self.config = config or HapticTrialSchedulerConfig()
        self.rng = rng or random.Random(plan.random_seed)
        self.state = WAIT_OPEN_ZONE
        self.haptic_trial_index = 0
        self._pending: _PendingEvent | None = None
        self._previous_event_end_ms: float | None = None
        self._refractory_until_ms: float | None = None

    def update(
        self,
        *,
        zone: str,
        now_ms: float,
        pinch_distance: float | None = None,
        frame_index: int | None = None,
        digit_onsets_ms: Iterable[float] | None = None,
    ) -> list[ScheduledHapticEvent]:
        """Advance the scheduler with one current zone/time sample."""

        now = _finite_float(now_ms, "now_ms")
        events: list[ScheduledHapticEvent] = []

        while True:
            if self.state == WAIT_OPEN_ZONE:
                if zone == "open_zone":
                    self._schedule_contact(now, digit_onsets_ms)
                return events

            if self.state == PENDING_CONTACT:
                if zone != "open_zone":
                    self._clear_pending()
                    self.state = WAIT_OPEN_ZONE
                    return events
                pending = self._pending
                if pending is None or now < pending.adjustment.adjusted_onset_ms:
                    return events
                events.append(
                    self._emit_pending(
                        actual_emit_ms=now,
                        actual_zone_at_emit=zone,
                        pinch_distance=pinch_distance,
                        frame_index=frame_index,
                    )
                )
                self.state = WAIT_CLOSED_ZONE
                return events

            if self.state == WAIT_CLOSED_ZONE:
                if zone == "closed_zone":
                    self._schedule_plan_event(
                        1,
                        base_ms=now,
                        digit_onsets_ms=digit_onsets_ms,
                        timing_note="planned_after_closed_zone_enter",
                    )
                return events

            if self.state == PENDING_PLAN_EVENT:
                pending = self._pending
                if pending is None or now < pending.adjustment.adjusted_onset_ms:
                    return events
                emitted = self._emit_pending(
                    actual_emit_ms=now,
                    actual_zone_at_emit=zone,
                    pinch_distance=pinch_distance,
                    frame_index=frame_index,
                )
                events.append(emitted)
                if emitted.event_index >= len(self.plan.events) - 1:
                    self._enter_refractory(emitted)
                    return events
                self._schedule_plan_event(
                    emitted.event_index + 1,
                    base_ms=now + float(emitted.duration_ms),
                    digit_onsets_ms=digit_onsets_ms,
                    timing_note="planned_after_previous_actual_emit",
                )
                return events

            if self.state == REFRACTORY:
                refractory_until = self._refractory_until_ms
                if refractory_until is not None and now < refractory_until:
                    return events
                self._refractory_until_ms = None
                self.state = WAIT_OPEN_ZONE
                continue

            raise RuntimeError(f"unknown haptic scheduler state: {self.state}")

    def _schedule_contact(
        self,
        now_ms: float,
        digit_onsets_ms: Iterable[float] | None,
    ) -> None:
        event = self.plan.events[0]
        delay_range = event.onset_delay_ms or self.plan.haptic_defaults.contact_onset_delay_ms
        sampled_delay = self._sample_range(delay_range)
        sampled_duration, global_default_used = self._sample_event_duration(event)
        original_onset = now_ms + sampled_delay
        adjustment = self._adjust_onset(original_onset, digit_onsets_ms)
        if adjustment.should_skip:
            self.state = WAIT_OPEN_ZONE
            self._pending = None
            return
        self._pending = _PendingEvent(
            event_index=0,
            event=event,
            adjustment=adjustment,
            sampled_duration_ms=sampled_duration,
            global_default_used=global_default_used,
            sampled_delay_ms=sampled_delay,
            timing_note="planned_after_open_zone_enter",
        )
        self.state = PENDING_CONTACT

    def _schedule_plan_event(
        self,
        event_index: int,
        *,
        base_ms: float,
        digit_onsets_ms: Iterable[float] | None,
        timing_note: str,
    ) -> None:
        if event_index >= len(self.plan.events):
            raise ValueError("event_index exceeds plan length.")
        event = self.plan.events[event_index]
        gap_range = event.onset_gap_after_previous_ms or self.plan.haptic_defaults.inter_event_gap_ms
        sampled_gap = self._sample_range(gap_range)
        sampled_duration, global_default_used = self._sample_event_duration(event)
        original_onset = float(base_ms) + sampled_gap
        adjustment = self._adjust_onset(original_onset, digit_onsets_ms)
        if adjustment.should_skip:
            self._previous_event_end_ms = original_onset
            if event_index >= len(self.plan.events) - 1:
                self._refractory_until_ms = (
                    original_onset + self.plan.timing.refractory_ms
                )
                self.haptic_trial_index += 1
                self.state = REFRACTORY
                self._pending = None
            else:
                self._schedule_plan_event(
                    event_index + 1,
                    base_ms=original_onset + sampled_duration,
                    digit_onsets_ms=digit_onsets_ms,
                    timing_note="planned_after_previous_actual_emit",
                )
            return
        self._pending = _PendingEvent(
            event_index=event_index,
            event=event,
            adjustment=adjustment,
            sampled_duration_ms=sampled_duration,
            global_default_used=global_default_used,
            sampled_gap_ms=sampled_gap,
            timing_note=timing_note,
        )
        self.state = PENDING_PLAN_EVENT

    def _emit_pending(
        self,
        *,
        actual_emit_ms: float,
        actual_zone_at_emit: str,
        pinch_distance: float | None,
        frame_index: int | None,
    ) -> ScheduledHapticEvent:
        pending = self._pending
        if pending is None:
            raise RuntimeError("no pending haptic event to emit.")
        event = pending.event
        adjustment = pending.adjustment
        scheduled = ScheduledHapticEvent(
            haptic_trial_index=self.haptic_trial_index,
            event_index=pending.event_index,
            event_name=event.name,
            modality=event.modality,
            command_label=event.command_label,
            command_id=event.command_id,
            end_command_label=event.end_command_label,
            end_command_id=event.end_command_id,
            channel_list=event.channel_list,
            matrix_sequence=event.matrix_sequence,
            duration_ms=pending.sampled_duration_ms,
            sampled_duration_ms=pending.sampled_duration_ms,
            global_default_used=pending.global_default_used,
            trigger_zone=event.trigger_zone,
            actual_zone_at_emit=str(actual_zone_at_emit),
            trigger_pinch_distance=(
                float(pinch_distance) if pinch_distance is not None else None
            ),
            trigger_frame_index=int(frame_index) if frame_index is not None else None,
            actual_emit_monotonic_ms=float(actual_emit_ms),
            event_end_monotonic_ms=float(actual_emit_ms) + float(pending.sampled_duration_ms),
            original_planned_onset_ms=adjustment.original_planned_onset_ms,
            adjusted_onset_ms=adjustment.adjusted_onset_ms,
            nearest_digit_onset_ms=adjustment.nearest_digit_onset_ms,
            digit_onset_delta_ms=adjustment.digit_onset_delta_ms,
            onset_was_delayed=adjustment.onset_was_delayed,
            sync_warning=adjustment.sync_warning,
            sampled_delay_ms=pending.sampled_delay_ms,
            sampled_gap_ms=pending.sampled_gap_ms,
            nback_trial_window=event.nback_trial_window,
            require_wrist_neutral_before_emit=event.require_wrist_neutral_before_emit,
            wrist_neutral_timeout_ms=event.wrist_neutral_timeout_ms,
            timing_note=pending.timing_note,
            end_reason="haptic_release" if event.name == "release" else "",
            haptic_episode_completed=event.name == "release",
        )
        self._previous_event_end_ms = (
            float(actual_emit_ms) + float(scheduled.duration_ms)
        )
        self._pending = None
        return scheduled

    def _enter_refractory(self, event: ScheduledHapticEvent) -> None:
        self._refractory_until_ms = (
            float(event.actual_emit_monotonic_ms or event.adjusted_onset_ms)
            + float(event.duration_ms)
            + float(self.plan.timing.refractory_ms)
        )
        self.haptic_trial_index += 1
        self.state = REFRACTORY
        self._pending = None

    def _adjust_onset(
        self,
        original_onset_ms: float,
        digit_onsets_ms: Iterable[float] | None,
    ) -> OnsetAdjustment:
        return adjust_onset_away_from_digit_onsets(
            onset_ms=original_onset_ms,
            digit_onsets_ms=digit_onsets_ms,
            avoid_haptic_on_digit_onset=self.config.avoid_haptic_on_digit_onset,
            guard_ms=self.config.digit_onset_guard_ms,
            max_haptic_delay_ms=self.config.max_haptic_delay_ms,
            if_cannot_avoid=self.config.if_cannot_avoid,
        )

    def _sample_range(self, value: tuple[int, int]) -> int:
        lower, upper = value
        return int(self.rng.randint(int(lower), int(upper)))

    def _sample_event_duration(self, event: HapticPlanEvent) -> tuple[int, bool]:
        if event.duration_ms is not None:
            return int(event.duration_ms), False
        if event.duration_ms_range is not None:
            return self._sample_range(event.duration_ms_range), False
        return self._sample_range(self._default_duration_range(event)), True

    def _default_duration_range(self, event: HapticPlanEvent) -> tuple[int, int]:
        if event.name in {"contact", "release"}:
            return self.plan.haptic_defaults.release_duration_ms
        if event.modality == "matrix":
            return self.plan.haptic_defaults.matrix_duration_ms
        return self.plan.haptic_defaults.vibration_duration_ms

    def _clear_pending(self) -> None:
        self._pending = None


class TimedGroupedHapticScheduler:
    """Schedule haptic events by elapsed time, ignoring pinch-zone triggers."""

    def __init__(
        self,
        plan: HapticPlanConfig,
        config: HapticTrialSchedulerConfig | None = None,
        *,
        rng: random.Random | None = None,
    ) -> None:
        if not plan.events:
            raise ValueError("plan must contain at least one event.")
        self.plan = plan
        self.config = config or HapticTrialSchedulerConfig()
        self.rng = rng or random.Random(plan.random_seed)
        self.groups = _timed_groups(plan.events)
        self.state = "TIMED_GROUP_INIT"
        self.haptic_trial_index = 0
        self._pending: _PendingTimedGroup | None = None
        self._refractory_until_ms: float | None = None

    def update(
        self,
        *,
        zone: str,
        now_ms: float,
        pinch_distance: float | None = None,
        frame_index: int | None = None,
        digit_onsets_ms: Iterable[float] | None = None,
    ) -> list[ScheduledHapticEvent]:
        now = _finite_float(now_ms, "now_ms")
        while True:
            if self.state == "TIMED_GROUP_INIT":
                self._schedule_group(
                    0,
                    base_ms=now,
                    digit_onsets_ms=digit_onsets_ms,
                    timing_note="timed_grouped_after_formal_start",
                    first_group=True,
                )
                return []
            if self.state == PENDING_TIMED_GROUP:
                pending = self._pending
                if pending is None or now < pending.adjustment.adjusted_onset_ms:
                    return []
                events = self._emit_pending_group(
                    actual_emit_ms=now,
                    actual_zone_at_emit=zone,
                    pinch_distance=pinch_distance,
                    frame_index=frame_index,
                )
                next_group_index = pending.group_index + 1
                if next_group_index >= len(self.groups):
                    self._enter_refractory(events)
                    return events
                group_duration = max(float(event.duration_ms or 0) for event in events)
                self._schedule_group(
                    next_group_index,
                    base_ms=now + group_duration,
                    digit_onsets_ms=digit_onsets_ms,
                    timing_note="timed_grouped_after_previous_group_emit",
                    first_group=False,
                )
                return events
            if self.state == REFRACTORY:
                refractory_until = self._refractory_until_ms
                if refractory_until is not None and now < refractory_until:
                    return []
                self._refractory_until_ms = None
                self.state = "TIMED_GROUP_INIT"
                continue
            raise RuntimeError(f"unknown timed haptic scheduler state: {self.state}")

    def _schedule_group(
        self,
        group_index: int,
        *,
        base_ms: float,
        digit_onsets_ms: Iterable[float] | None,
        timing_note: str,
        first_group: bool,
    ) -> None:
        group = self.groups[group_index]
        timing_event = group.events[0]
        if first_group:
            delay_range = timing_event.onset_delay_ms or self.plan.haptic_defaults.contact_onset_delay_ms
            sampled_delay = self._sample_range(delay_range)
            sampled_gap = None
            original_onset = float(base_ms) + sampled_delay
        else:
            gap_range = timing_event.onset_gap_after_previous_ms or self.plan.haptic_defaults.inter_event_gap_ms
            sampled_gap = self._sample_range(gap_range)
            sampled_delay = None
            original_onset = float(base_ms) + sampled_gap
        adjustment = self._adjust_onset(original_onset, digit_onsets_ms)
        if adjustment.should_skip:
            if group_index >= len(self.groups) - 1:
                self._refractory_until_ms = original_onset + self.plan.timing.refractory_ms
                self.haptic_trial_index += 1
                self.state = REFRACTORY
            else:
                self._schedule_group(
                    group_index + 1,
                    base_ms=original_onset,
                    digit_onsets_ms=digit_onsets_ms,
                    timing_note="timed_grouped_after_previous_group_emit",
                    first_group=False,
                )
            return
        sampled: list[int] = []
        default_used: list[bool] = []
        for event in group.events:
            duration, used = self._sample_event_duration(event)
            sampled.append(duration)
            default_used.append(used)
        self._pending = _PendingTimedGroup(
            group_index=group_index,
            group=group,
            adjustment=adjustment,
            sampled_durations_ms=tuple(sampled),
            global_default_used=tuple(default_used),
            sampled_delay_ms=sampled_delay,
            sampled_gap_ms=sampled_gap,
            timing_note=timing_note,
        )
        self.state = PENDING_TIMED_GROUP

    def _emit_pending_group(
        self,
        *,
        actual_emit_ms: float,
        actual_zone_at_emit: str,
        pinch_distance: float | None,
        frame_index: int | None,
    ) -> list[ScheduledHapticEvent]:
        pending = self._pending
        if pending is None:
            raise RuntimeError("no pending haptic group to emit.")
        events: list[ScheduledHapticEvent] = []
        for offset, event in enumerate(pending.group.events):
            duration_ms = pending.sampled_durations_ms[offset]
            scheduled = ScheduledHapticEvent(
                haptic_trial_index=self.haptic_trial_index,
                event_index=pending.group.event_index + offset,
                event_name=event.name,
                modality=event.modality,
                command_label=event.command_label,
                command_id=event.command_id,
                end_command_label=event.end_command_label,
                end_command_id=event.end_command_id,
                channel_list=event.channel_list,
                matrix_sequence=event.matrix_sequence,
                simultaneous_group=pending.group.simultaneous_group,
                duration_ms=duration_ms,
                sampled_duration_ms=duration_ms,
                global_default_used=pending.global_default_used[offset],
                trigger_zone=event.trigger_zone,
                actual_zone_at_emit=str(actual_zone_at_emit),
                trigger_pinch_distance=(
                    float(pinch_distance) if pinch_distance is not None else None
                ),
                trigger_frame_index=int(frame_index) if frame_index is not None else None,
                actual_emit_monotonic_ms=float(actual_emit_ms),
                actual_emit_ms=float(actual_emit_ms),
                event_end_monotonic_ms=float(actual_emit_ms) + float(duration_ms),
                original_planned_onset_ms=pending.adjustment.original_planned_onset_ms,
                adjusted_onset_ms=pending.adjustment.adjusted_onset_ms,
                nearest_digit_onset_ms=pending.adjustment.nearest_digit_onset_ms,
                digit_onset_delta_ms=pending.adjustment.digit_onset_delta_ms,
                onset_was_delayed=pending.adjustment.onset_was_delayed,
                sync_warning=pending.adjustment.sync_warning,
                sampled_delay_ms=pending.sampled_delay_ms,
                sampled_gap_ms=pending.sampled_gap_ms,
                nback_trial_window=event.nback_trial_window,
                require_wrist_neutral_before_emit=event.require_wrist_neutral_before_emit,
                wrist_neutral_timeout_ms=event.wrist_neutral_timeout_ms,
                trial_gate_enabled=False,
                trial_gate_ignored=event.nback_trial_window is not None,
                wrist_neutral_gate_required=False,
                timing_note=pending.timing_note + ";zone_gate_ignored",
                end_reason="haptic_release" if event.name == "release" else "",
                haptic_episode_completed=event.name == "release",
            )
            events.append(scheduled)
        self._pending = None
        return events

    def _enter_refractory(self, events: list[ScheduledHapticEvent]) -> None:
        latest_end = max(
            float(event.event_end_monotonic_ms or event.actual_emit_monotonic_ms or 0.0)
            for event in events
        )
        self._refractory_until_ms = latest_end + float(self.plan.timing.refractory_ms)
        self.haptic_trial_index += 1
        self.state = REFRACTORY
        self._pending = None

    def _adjust_onset(
        self,
        original_onset_ms: float,
        digit_onsets_ms: Iterable[float] | None,
    ) -> OnsetAdjustment:
        return adjust_onset_away_from_digit_onsets(
            onset_ms=original_onset_ms,
            digit_onsets_ms=digit_onsets_ms,
            avoid_haptic_on_digit_onset=self.config.avoid_haptic_on_digit_onset,
            guard_ms=self.config.digit_onset_guard_ms,
            max_haptic_delay_ms=self.config.max_haptic_delay_ms,
            if_cannot_avoid=self.config.if_cannot_avoid,
        )

    def _sample_range(self, value: tuple[int, int]) -> int:
        lower, upper = value
        return int(self.rng.randint(int(lower), int(upper)))

    def _sample_event_duration(self, event: HapticPlanEvent) -> tuple[int, bool]:
        if event.duration_ms is not None:
            return int(event.duration_ms), False
        if event.duration_ms_range is not None:
            return self._sample_range(event.duration_ms_range), False
        return self._sample_range(self._default_duration_range(event)), True

    def _default_duration_range(self, event: HapticPlanEvent) -> tuple[int, int]:
        if event.name in {"contact", "release"}:
            return self.plan.haptic_defaults.release_duration_ms
        if event.modality == "matrix":
            return self.plan.haptic_defaults.matrix_duration_ms
        return self.plan.haptic_defaults.vibration_duration_ms


def _timed_groups(events: tuple[HapticPlanEvent, ...]) -> tuple[_TimedGroup, ...]:
    groups: list[_TimedGroup] = []
    index = 0
    while index < len(events):
        first = events[index]
        group_name = str(first.simultaneous_group or "")
        group_events = [first]
        next_index = index + 1
        if group_name:
            while (
                next_index < len(events)
                and str(events[next_index].simultaneous_group or "") == group_name
            ):
                group_events.append(events[next_index])
                next_index += 1
        groups.append(
            _TimedGroup(
                group_index=len(groups),
                event_index=index,
                events=tuple(group_events),
                simultaneous_group=group_name,
            )
        )
        index = next_index
    return tuple(groups)


def _nearest_digit_onset(onset_ms: float, digit_onsets_ms: list[float]) -> float | None:
    if not digit_onsets_ms:
        return None
    return min(digit_onsets_ms, key=lambda value: abs(onset_ms - value))


def _first_conflicting_digit(
    onset_ms: float,
    digit_onsets_ms: list[float],
    guard_ms: float,
) -> float | None:
    for digit_onset in digit_onsets_ms:
        if abs(onset_ms - digit_onset) < guard_ms:
            return digit_onset
    return None


def _finite_float(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number.")
    return result


def _non_negative_float(value: Any, name: str) -> float:
    result = _finite_float(value, name)
    if result < 0.0:
        raise ValueError(f"{name} must be non-negative.")
    return result
