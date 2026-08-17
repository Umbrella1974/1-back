"""Command-line haptic identification test tool."""

from __future__ import annotations

import argparse
import csv
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from haptic_plan_config import HapticPlanEvent
from learn_haptic_patterns import (
    EVENT_LABELS,
    MODE_CONFIGS,
    LearningSession,
    _event_menu_label,
    load_learning_session,
    play_event_once_for_test,
)
from simple_haptic_sender import SimpleHapticSender


DEFAULT_REPEATS_PER_CUE = 3
MAX_REPLAYS = 2

RESULT_FIELDS = [
    "timestamp",
    "session_id",
    "mode_name",
    "trial_index",
    "true_event_name",
    "true_label",
    "answer_event_name",
    "answer_label",
    "is_correct",
    "reaction_time_sec",
    "replay_count",
    "status",
    "random_seed",
]

SEQUENCE_FIELDS = [
    "session_id",
    "mode_name",
    "trial_index",
    "event_name",
    "label",
    "random_seed",
]


@dataclass(frozen=True)
class HapticTestTrial:
    trial_index: int
    event: HapticPlanEvent


def main() -> int:
    parser = argparse.ArgumentParser(description="Random haptic identification test.")
    parser.add_argument("--mode", choices=sorted(MODE_CONFIGS), default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS_PER_CUE)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    session = _load_or_choose_session(args.mode, args.config)
    if args.repeats <= 0:
        raise ValueError("--repeats must be positive.")
    seed = args.seed if args.seed is not None else random.SystemRandom().randint(1, 2**31 - 1)
    run_haptic_test(session, repeats_per_cue=args.repeats, random_seed=seed)
    return 0


def run_haptic_test(
    session: LearningSession,
    *,
    repeats_per_cue: int = DEFAULT_REPEATS_PER_CUE,
    random_seed: int,
) -> Path:
    session_id = _make_test_session_id(session.mode_name)
    output_dir = Path("outputs") / "haptic_test_logs"
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / f"{session_id}_results.csv"
    sequence_path = output_dir / f"{session_id}_sequence.csv"
    trials = build_test_trials(session.events, repeats_per_cue=repeats_per_cue, random_seed=random_seed)
    write_sequence_csv(sequence_path, session_id=session_id, mode_name=session.mode_name, trials=trials, random_seed=random_seed)

    print(f"\nMode: {session.mode_name}")
    print(f"Trials: {len(trials)} ({len(session.events)} cues x {repeats_per_cue})")
    print(f"Random seed: {random_seed}")
    print(f"Sequence: {sequence_path}")
    print(f"Results: {result_path}")
    print("Answer options:")
    _print_answer_options(session.events)

    sender = SimpleHapticSender(session.sender_config, session_id=session_id)
    try:
        for trial in trials:
            status = _run_test_trial(
                session=session,
                session_id=session_id,
                trial=trial,
                sender=sender,
                result_path=result_path,
                random_seed=random_seed,
            )
            if status == "exit":
                print("Test aborted.")
                break
    finally:
        sender.close()
    print("Test complete.")
    return result_path


def build_test_trials(
    events: tuple[HapticPlanEvent, ...],
    *,
    repeats_per_cue: int,
    random_seed: int,
) -> list[HapticTestTrial]:
    pool: list[HapticPlanEvent] = []
    for event in events:
        pool.extend([event] * int(repeats_per_cue))
    rng = random.Random(int(random_seed))
    rng.shuffle(pool)
    return [HapticTestTrial(index + 1, event) for index, event in enumerate(pool)]


def write_sequence_csv(
    path: Path,
    *,
    session_id: str,
    mode_name: str,
    trials: list[HapticTestTrial],
    random_seed: int,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SEQUENCE_FIELDS)
        writer.writeheader()
        for trial in trials:
            writer.writerow(
                {
                    "session_id": session_id,
                    "mode_name": mode_name,
                    "trial_index": trial.trial_index,
                    "event_name": trial.event.name,
                    "label": _event_label(trial.event),
                    "random_seed": random_seed,
                }
            )


def _run_test_trial(
    *,
    session: LearningSession,
    session_id: str,
    trial: HapticTestTrial,
    sender: SimpleHapticSender,
    result_path: Path,
    random_seed: int,
) -> str:
    replay_count = 0
    while True:
        choice = input(f"\nTrial {trial.trial_index}: Enter to play, q to quit > ").strip().lower()
        if choice in {"q", "quit", "exit"}:
            return "exit"
        if not choice:
            break
        print("Invalid choice.")

    try:
        start_time = _play_test_event(sender, trial.event)
    except Exception as exc:
        print(f"Send failed: {exc}")
        append_result_csv(
            result_path,
            make_result_row(
                session_id=session_id,
                mode_name=session.mode_name,
                trial_index=trial.trial_index,
                true_event=trial.event,
                answer_event=None,
                reaction_time_sec="",
                replay_count=replay_count,
                status="send_failed",
                random_seed=random_seed,
            ),
        )
        return "exit"

    while True:
        _print_answer_options(session.events)
        choice = input("Answer (number/label/r/q): ").strip()
        action, answer_event = parse_answer(choice, session.events)
        if action == "invalid":
            continue
        if action == "quit":
            return "exit"
        if action == "replay":
            if replay_count >= MAX_REPLAYS:
                print("Max replay reached; recording unanswered trial.")
                append_result_csv(
                    result_path,
                    make_result_row(
                        session_id=session_id,
                        mode_name=session.mode_name,
                        trial_index=trial.trial_index,
                        true_event=trial.event,
                        answer_event=None,
                        reaction_time_sec="",
                        replay_count=replay_count,
                        status="exceeded_replay",
                        random_seed=random_seed,
                    ),
                )
                return "continue"
            replay_count += 1
            start_time = _play_test_event(sender, trial.event)
            continue

        reaction_time_sec = f"{time.perf_counter() - start_time:.6f}"
        row = make_result_row(
            session_id=session_id,
            mode_name=session.mode_name,
            trial_index=trial.trial_index,
            true_event=trial.event,
            answer_event=answer_event,
            reaction_time_sec=reaction_time_sec,
            replay_count=replay_count,
            status="answered",
            random_seed=random_seed,
        )
        append_result_csv(result_path, row)
        print(f"Recorded: {row['answer_label']} correct={row['is_correct']} RT={reaction_time_sec}s")
        return "continue"


def _play_test_event(sender: SimpleHapticSender, event: HapticPlanEvent) -> float:
    print(f"Playing cue: {_event_menu_label(event)}")
    start_time = time.perf_counter()
    play_event_once_for_test(sender, event)
    return start_time


def parse_answer(
    choice: str,
    events: tuple[HapticPlanEvent, ...],
) -> tuple[str, HapticPlanEvent | None]:
    normalized = choice.strip()
    if normalized.lower() in {"r", "replay"}:
        return "replay", None
    if normalized.lower() in {"q", "quit", "exit"}:
        return "quit", None
    if normalized.isdigit():
        index = int(normalized) - 1
        if 0 <= index < len(events):
            return "answer", events[index]
        print("Invalid answer number.")
        return "invalid", None
    for event in events:
        if normalized.lower() in {event.name.lower(), _event_label(event).lower()}:
            return "answer", event
    print("Invalid answer.")
    return "invalid", None


def make_result_row(
    *,
    session_id: str,
    mode_name: str,
    trial_index: int,
    true_event: HapticPlanEvent,
    answer_event: HapticPlanEvent | None,
    reaction_time_sec: str,
    replay_count: int,
    status: str,
    random_seed: int,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "session_id": session_id,
        "mode_name": mode_name,
        "trial_index": trial_index,
        "true_event_name": true_event.name,
        "true_label": _event_label(true_event),
        "answer_event_name": answer_event.name if answer_event is not None else "",
        "answer_label": _event_label(answer_event) if answer_event is not None else "",
        "is_correct": bool(answer_event is not None and answer_event.name == true_event.name),
        "reaction_time_sec": reaction_time_sec,
        "replay_count": int(replay_count),
        "status": status,
        "random_seed": int(random_seed),
    }


def append_result_csv(path: Path, row: dict[str, Any]) -> None:
    mode = "a" if path.exists() else "w"
    with path.open(mode, newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        if mode == "w":
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in RESULT_FIELDS})


def _load_or_choose_session(mode: str | None, config_path: str | None) -> LearningSession:
    if config_path:
        return load_learning_session(config_path, mode_name=mode or Path(config_path).stem)
    if mode:
        return load_learning_session(MODE_CONFIGS[mode], mode_name=mode)
    choices = list(MODE_CONFIGS)
    while True:
        print("\nSelect haptic test mode:")
        for index, name in enumerate(choices, start=1):
            print(f"  [{index}] {name} ({MODE_CONFIGS[name]})")
        choice = input("> ").strip().lower()
        if choice in {"q", "quit", "exit"}:
            raise SystemExit(0)
        if choice.isdigit() and 1 <= int(choice) <= len(choices):
            selected = choices[int(choice) - 1]
            return load_learning_session(MODE_CONFIGS[selected], mode_name=selected)
        print("Invalid choice.")


def _print_answer_options(events: tuple[HapticPlanEvent, ...]) -> None:
    for index, event in enumerate(events, start=1):
        print(f"  {index}. {_event_label(event)}")
    print("  r. replay")
    print("  q. quit")


def _event_label(event: HapticPlanEvent | None) -> str:
    if event is None:
        return ""
    return EVENT_LABELS.get(event.name, event.name)


def _make_test_session_id(mode_name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_mode = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_"
        for ch in str(mode_name)
    )
    return f"haptic_test_{safe_mode}_{stamp}"


if __name__ == "__main__":
    raise SystemExit(main())
