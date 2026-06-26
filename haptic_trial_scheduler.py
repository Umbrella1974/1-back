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
    channel_list: tuple[int, ...] = field(default_factory=tuple)
    duration_ms: int = 0
    trigger_zone: str = ""
    actual_zone_at_emit: str = ""
    trigger_pinch_distance: float | None = None
    trigger_frame_index: int | None = None
    original_planned_onset_ms: float = 0.0
    adjusted_onset_ms: float = 0.0
    nearest_digit_onset_ms: float | None = None
    digit_onset_delta_ms: float | None = None
    onset_was_delayed: bool = False
    sync_warning: str = ""
    sampled_delay_ms: int | None = None
    sampled_gap_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["channel_list"] = list(self.channel_list)
        return payload


@dataclass(frozen=True)
class _PendingEvent:
    event_index: int
    event: HapticPlanEvent
    adjustment: OnsetAdjustment
    sampled_delay_ms: int | None = None
    sampled_gap_ms: int | None = None


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
                        actual_zone_at_emit=zone,
                        pinch_distance=pinch_distance,
                        frame_index=frame_index,
                    )
                )
                self.state = WAIT_CLOSED_ZONE
                return events

            if self.state == WAIT_CLOSED_ZONE:
                if zone == "closed_zone":
                    self._schedule_plan_event(1, digit_onsets_ms)
                return events

            if self.state == PENDING_PLAN_EVENT:
                pending = self._pending
                if pending is None or now < pending.adjustment.adjusted_onset_ms:
                    return events
                emitted = self._emit_pending(
                    actual_zone_at_emit=zone,
                    pinch_distance=pinch_distance,
                    frame_index=frame_index,
                )
                events.append(emitted)
                if emitted.event_index >= len(self.plan.events) - 1:
                    self._enter_refractory(emitted)
                    return events
                self._schedule_plan_event(emitted.event_index + 1, digit_onsets_ms)
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
        delay_range = event.onset_delay_ms or self.plan.timing.contact_onset_delay_ms
        sampled_delay = self._sample_range(delay_range)
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
            sampled_delay_ms=sampled_delay,
        )
        self.state = PENDING_CONTACT

    def _schedule_plan_event(
        self,
        event_index: int,
        digit_onsets_ms: Iterable[float] | None,
    ) -> None:
        if event_index >= len(self.plan.events):
            raise ValueError("event_index exceeds plan length.")
        if self._previous_event_end_ms is None:
            raise RuntimeError("cannot schedule plan event before contact end.")
        event = self.plan.events[event_index]
        gap_range = event.onset_gap_after_previous_ms or self.plan.timing.inter_event_gap_ms
        sampled_gap = self._sample_range(gap_range)
        original_onset = self._previous_event_end_ms + sampled_gap
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
                self._schedule_plan_event(event_index + 1, digit_onsets_ms)
            return
        self._pending = _PendingEvent(
            event_index=event_index,
            event=event,
            adjustment=adjustment,
            sampled_gap_ms=sampled_gap,
        )
        self.state = PENDING_PLAN_EVENT

    def _emit_pending(
        self,
        *,
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
            channel_list=event.channel_list,
            duration_ms=event.duration_ms,
            trigger_zone=event.trigger_zone,
            actual_zone_at_emit=str(actual_zone_at_emit),
            trigger_pinch_distance=(
                float(pinch_distance) if pinch_distance is not None else None
            ),
            trigger_frame_index=int(frame_index) if frame_index is not None else None,
            original_planned_onset_ms=adjustment.original_planned_onset_ms,
            adjusted_onset_ms=adjustment.adjusted_onset_ms,
            nearest_digit_onset_ms=adjustment.nearest_digit_onset_ms,
            digit_onset_delta_ms=adjustment.digit_onset_delta_ms,
            onset_was_delayed=adjustment.onset_was_delayed,
            sync_warning=adjustment.sync_warning,
            sampled_delay_ms=pending.sampled_delay_ms,
            sampled_gap_ms=pending.sampled_gap_ms,
        )
        self._previous_event_end_ms = (
            scheduled.adjusted_onset_ms + float(scheduled.duration_ms)
        )
        self._pending = None
        return scheduled

    def _enter_refractory(self, event: ScheduledHapticEvent) -> None:
        self._refractory_until_ms = (
            event.adjusted_onset_ms
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

    def _clear_pending(self) -> None:
        self._pending = None


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
