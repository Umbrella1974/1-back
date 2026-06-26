"""Pure 1-back timeline helpers for the pinch+haptic dual-task runner."""

from __future__ import annotations

import math
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


NBACK_PHASE_NOT_STARTED = "not_started"
NBACK_PHASE_WAITING = "waiting"
NBACK_PHASE_FIXATION = "fixation"
NBACK_PHASE_STIMULUS = "stimulus"
NBACK_PHASE_BLANK = "blank"
NBACK_PHASE_COMPLETE = "complete"


@dataclass(frozen=True)
class NBackConfig:
    """Timing and response settings for a 1-back numeric task."""

    num_trials: int = 50
    target_ratio: float = 0.3
    number_min: int = 0
    number_max: int = 9
    fixation_duration_ms: int = 500
    stimulus_duration_ms: int = 500
    isi_min_ms: int = 1000
    isi_max_ms: int = 1500
    key_same: str = "left"
    key_different: str = "right"
    random_seed: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "num_trials", _positive_int(self.num_trials, "num_trials"))
        ratio = _finite_float(self.target_ratio, "target_ratio")
        if ratio < 0.0 or ratio > 1.0:
            raise ValueError("target_ratio must be between 0 and 1.")
        object.__setattr__(self, "target_ratio", ratio)
        number_min = _int_value(self.number_min, "number_min")
        number_max = _int_value(self.number_max, "number_max")
        if number_max <= number_min:
            raise ValueError("number_max must be greater than number_min.")
        object.__setattr__(self, "number_min", number_min)
        object.__setattr__(self, "number_max", number_max)
        for name in (
            "fixation_duration_ms",
            "stimulus_duration_ms",
            "isi_min_ms",
            "isi_max_ms",
        ):
            object.__setattr__(self, name, _non_negative_int(getattr(self, name), name))
        if self.stimulus_duration_ms <= 0:
            raise ValueError("stimulus_duration_ms must be positive.")
        if self.isi_max_ms < self.isi_min_ms:
            raise ValueError("isi_max_ms must be >= isi_min_ms.")
        object.__setattr__(self, "key_same", _key_name(self.key_same))
        object.__setattr__(self, "key_different", _key_name(self.key_different))
        if self.key_same == self.key_different:
            raise ValueError("key_same and key_different must be different.")
        if self.random_seed is not None:
            object.__setattr__(self, "random_seed", _int_value(self.random_seed, "random_seed"))


@dataclass(frozen=True)
class NBackTrial:
    """One scheduled 1-back stimulus."""

    stimulus_index: int
    stimulus: int
    is_target: bool
    fixation_onset_monotonic_ms: float
    stimulus_onset_monotonic_ms: float
    stimulus_offset_monotonic_ms: float
    response_window_end_monotonic_ms: float


@dataclass(frozen=True)
class NBackResponse:
    """One accepted response to a scheduled 1-back stimulus."""

    stimulus_index: int
    response_key: str
    response_same: bool
    response_monotonic_ms: float
    rt_ms: float
    correct: bool


@dataclass(frozen=True)
class NBackEventRecord:
    """CSV row for one finalized 1-back stimulus."""

    session_id: str
    wall_time_iso: str
    stimulus_index: int
    stimulus: int
    is_target: bool
    stimulus_onset_monotonic_ms: float
    response_key: str = ""
    response_monotonic_ms: float | None = None
    correct: bool = False
    rt_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_csv_row(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True)
class NBackTick:
    """Display state for one monotonic timestamp."""

    phase: str
    trial: NBackTrial | None


def generate_nback_sequence(
    config: NBackConfig,
    *,
    rng: random.Random | None = None,
) -> list[int]:
    """Generate a numeric 1-back sequence with the configured target ratio."""

    random_source = rng or random.Random(config.random_seed)
    numbers = list(range(config.number_min, config.number_max + 1))
    sequence: list[int] = []
    potential_targets = list(range(1, config.num_trials))
    target_count = min(
        len(potential_targets),
        int((config.num_trials - 1) * config.target_ratio),
    )
    target_indices = set(random_source.sample(potential_targets, target_count))

    for index in range(config.num_trials):
        if index == 0:
            value = random_source.choice(numbers)
        elif index in target_indices:
            value = sequence[index - 1]
        else:
            available = [item for item in numbers if item != sequence[index - 1]]
            if index >= 2 and sequence[index - 1] == sequence[index - 2]:
                available = [item for item in available if item != sequence[index - 1]]
            value = random_source.choice(available)
        sequence.append(value)
    return sequence


class NBackTimeline:
    """Precomputed 1-back onset timeline with first-response logging."""

    def __init__(
        self,
        config: NBackConfig,
        *,
        sequence: Iterable[int] | None = None,
        isi_ms: Iterable[int] | None = None,
        wall_time_fn: Any | None = None,
    ) -> None:
        self.config = config
        self._rng = random.Random(config.random_seed)
        self.sequence = (
            _validate_sequence(sequence, config)
            if sequence is not None
            else generate_nback_sequence(config, rng=self._rng)
        )
        self._isi_ms = (
            _validate_isi(isi_ms, config)
            if isi_ms is not None
            else [
                self._rng.randint(config.isi_min_ms, config.isi_max_ms)
                for _ in range(config.num_trials)
            ]
        )
        self.wall_time_fn = wall_time_fn or time.time
        self._start_ms: float | None = None
        self._trials: list[NBackTrial] = []
        self._responses: dict[int, NBackResponse] = {}
        self._finalized_indices: set[int] = set()

    @property
    def started(self) -> bool:
        return self._start_ms is not None

    @property
    def trials(self) -> tuple[NBackTrial, ...]:
        return tuple(self._trials)

    @property
    def digit_onsets_ms(self) -> list[float]:
        return [trial.stimulus_onset_monotonic_ms for trial in self._trials]

    @property
    def end_monotonic_ms(self) -> float | None:
        if not self._trials:
            return None
        return self._trials[-1].response_window_end_monotonic_ms

    @property
    def response_count(self) -> int:
        return len(self._responses)

    def start(self, start_monotonic_ms: float) -> None:
        """Schedule all trials relative to one monotonic start timestamp."""

        start = _finite_float(start_monotonic_ms, "start_monotonic_ms")
        self._start_ms = start
        self._responses.clear()
        self._finalized_indices.clear()
        self._trials = []
        cursor = start
        for index, stimulus in enumerate(self.sequence):
            fixation_onset = cursor
            stimulus_onset = fixation_onset + float(self.config.fixation_duration_ms)
            stimulus_offset = stimulus_onset + float(self.config.stimulus_duration_ms)
            response_end = stimulus_offset + float(self._isi_ms[index])
            previous = self.sequence[index - 1] if index > 0 else None
            self._trials.append(
                NBackTrial(
                    stimulus_index=index,
                    stimulus=int(stimulus),
                    is_target=bool(previous is not None and stimulus == previous),
                    fixation_onset_monotonic_ms=fixation_onset,
                    stimulus_onset_monotonic_ms=stimulus_onset,
                    stimulus_offset_monotonic_ms=stimulus_offset,
                    response_window_end_monotonic_ms=response_end,
                )
            )
            cursor = response_end

    def tick(self, now_ms: float) -> NBackTick:
        """Return the display phase and active trial for the current time."""

        if not self.started:
            return NBackTick(phase=NBACK_PHASE_NOT_STARTED, trial=None)
        now = _finite_float(now_ms, "now_ms")
        if self._trials and now < self._trials[0].fixation_onset_monotonic_ms:
            return NBackTick(phase=NBACK_PHASE_WAITING, trial=None)
        for trial in self._trials:
            if trial.fixation_onset_monotonic_ms <= now < trial.stimulus_onset_monotonic_ms:
                return NBackTick(phase=NBACK_PHASE_FIXATION, trial=trial)
            if trial.stimulus_onset_monotonic_ms <= now < trial.stimulus_offset_monotonic_ms:
                return NBackTick(phase=NBACK_PHASE_STIMULUS, trial=trial)
            if trial.stimulus_offset_monotonic_ms <= now < trial.response_window_end_monotonic_ms:
                return NBackTick(phase=NBACK_PHASE_BLANK, trial=trial)
        return NBackTick(phase=NBACK_PHASE_COMPLETE, trial=None)

    def record_response(
        self,
        key_name: str,
        response_monotonic_ms: float,
    ) -> NBackResponse | None:
        """Record the first valid response in the active response window."""

        if not self.started:
            return None
        key = _key_name(key_name)
        response_same = self._key_to_response(key)
        if response_same is None:
            return None
        now = _finite_float(response_monotonic_ms, "response_monotonic_ms")
        trial = self._response_trial_at(now)
        if trial is None or trial.stimulus_index in self._responses:
            return None
        rt_ms = now - trial.stimulus_onset_monotonic_ms
        response = NBackResponse(
            stimulus_index=trial.stimulus_index,
            response_key=key,
            response_same=response_same,
            response_monotonic_ms=now,
            rt_ms=rt_ms,
            correct=bool(response_same == trial.is_target),
        )
        self._responses[trial.stimulus_index] = response
        return response

    def finalize_until(
        self,
        now_ms: float,
        *,
        session_id: str,
    ) -> list[NBackEventRecord]:
        """Finalize all trials whose response windows have ended."""

        if not self.started:
            return []
        now = _finite_float(now_ms, "now_ms")
        rows: list[NBackEventRecord] = []
        for trial in self._trials:
            if trial.stimulus_index in self._finalized_indices:
                continue
            if trial.response_window_end_monotonic_ms > now:
                break
            rows.append(self._make_event_record(trial, session_id=session_id))
            self._finalized_indices.add(trial.stimulus_index)
        return rows

    def finalize_all(self, *, session_id: str) -> list[NBackEventRecord]:
        """Finalize all remaining trials."""

        if not self._trials:
            return []
        return self.finalize_until(
            self._trials[-1].response_window_end_monotonic_ms,
            session_id=session_id,
        )

    def is_complete(self, now_ms: float) -> bool:
        """Return true once the timeline has ended and all trials are finalized."""

        if not self.started or self.end_monotonic_ms is None:
            return False
        return (
            _finite_float(now_ms, "now_ms") >= self.end_monotonic_ms
            and len(self._finalized_indices) >= len(self._trials)
        )

    def _response_trial_at(self, now_ms: float) -> NBackTrial | None:
        for trial in self._trials:
            if (
                trial.stimulus_onset_monotonic_ms
                <= now_ms
                < trial.response_window_end_monotonic_ms
            ):
                return trial
        return None

    def _key_to_response(self, key: str) -> bool | None:
        if key == self.config.key_same:
            return True
        if key == self.config.key_different:
            return False
        return None

    def _make_event_record(
        self,
        trial: NBackTrial,
        *,
        session_id: str,
    ) -> NBackEventRecord:
        response = self._responses.get(trial.stimulus_index)
        return NBackEventRecord(
            session_id=session_id,
            wall_time_iso=datetime.fromtimestamp(float(self.wall_time_fn()), timezone.utc).isoformat(),
            stimulus_index=trial.stimulus_index,
            stimulus=trial.stimulus,
            is_target=trial.is_target,
            stimulus_onset_monotonic_ms=trial.stimulus_onset_monotonic_ms,
            response_key=response.response_key if response is not None else "",
            response_monotonic_ms=(
                response.response_monotonic_ms if response is not None else None
            ),
            correct=response.correct if response is not None else False,
            rt_ms=response.rt_ms if response is not None else None,
        )


def _validate_sequence(value: Iterable[int], config: NBackConfig) -> list[int]:
    sequence = [_int_value(item, "sequence item") for item in value]
    if len(sequence) != config.num_trials:
        raise ValueError("sequence length must equal num_trials.")
    for item in sequence:
        if item < config.number_min or item > config.number_max:
            raise ValueError("sequence item is outside configured number range.")
    return sequence


def _validate_isi(value: Iterable[int], config: NBackConfig) -> list[int]:
    items = [_non_negative_int(item, "isi_ms item") for item in value]
    if len(items) != config.num_trials:
        raise ValueError("isi_ms length must equal num_trials.")
    return items


def _key_name(value: Any) -> str:
    text = str(value).strip().lower()
    if not text:
        raise ValueError("key name must be non-empty.")
    return text


def _int_value(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _positive_int(value: Any, name: str) -> int:
    result = _int_value(value, name)
    if result <= 0:
        raise ValueError(f"{name} must be positive.")
    return result


def _non_negative_int(value: Any, name: str) -> int:
    result = _int_value(value, name)
    if result < 0:
        raise ValueError(f"{name} must be non-negative.")
    return result


def _finite_float(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number.")
    return result
