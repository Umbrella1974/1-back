"""Dry-run a haptic plan through the scheduler and disabled sender."""

from __future__ import annotations

import argparse
from pathlib import Path

from haptic_plan_config import HapticPlanConfig, load_haptic_plan_config
from haptic_trial_scheduler import HapticTrialScheduler
from simple_haptic_sender import SimpleHapticSender


def dry_run_haptic_plan(
    plan: HapticPlanConfig,
    *,
    out_path: str | Path,
    session_id: str = "dry_run",
    start_ms: float = 1000.0,
    digit_onsets_ms: list[float] | None = None,
) -> Path:
    """Simulate one haptic trial and write disabled-mode haptic_events.csv."""

    scheduler = HapticTrialScheduler(plan)
    sender = SimpleHapticSender(session_id=session_id)
    now_ms = float(start_ms)
    frame_index = 0
    emitted_count = 0

    while emitted_count < len(plan.events):
        zone = _zone_for_scheduler_state(scheduler.state)
        events = scheduler.update(
            zone=zone,
            now_ms=now_ms,
            pinch_distance=0.08 if zone == "open_zone" else 0.02,
            frame_index=frame_index,
            digit_onsets_ms=digit_onsets_ms,
        )
        for event in events:
            sender.record_scheduled_event(event)
            emitted_count += 1
        next_onset = _next_pending_onset_ms(scheduler)
        if next_onset is not None:
            now_ms = next_onset
        else:
            now_ms += 1.0
        frame_index += 1

    return sender.write_csv(out_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run a haptic plan to CSV.")
    parser.add_argument("--plan", default="haptic_plan_config_example.yaml")
    parser.add_argument("--out", default="outputs/dry_run_haptic_events.csv")
    parser.add_argument("--session-id", default="dry_run")
    parser.add_argument("--start-ms", type=float, default=1000.0)
    parser.add_argument(
        "--digit-onsets",
        default="",
        help="Optional comma-separated digit onset times in ms.",
    )
    args = parser.parse_args()

    plan = load_haptic_plan_config(args.plan)
    path = dry_run_haptic_plan(
        plan,
        out_path=args.out,
        session_id=args.session_id,
        start_ms=args.start_ms,
        digit_onsets_ms=_parse_digit_onsets(args.digit_onsets),
    )
    print(f"Wrote {path}")
    return 0


def _zone_for_scheduler_state(state: str) -> str:
    if state in {"WAIT_OPEN_ZONE", "PENDING_CONTACT", "REFRACTORY"}:
        return "open_zone"
    return "closed_zone"


def _next_pending_onset_ms(scheduler: HapticTrialScheduler) -> float | None:
    pending = getattr(scheduler, "_pending", None)
    adjustment = getattr(pending, "adjustment", None)
    value = getattr(adjustment, "adjusted_onset_ms", None)
    return float(value) if value is not None else None


def _parse_digit_onsets(raw: str) -> list[float] | None:
    text = str(raw).strip()
    if not text:
        return None
    return [float(item.strip()) for item in text.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())

