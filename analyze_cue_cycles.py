"""Post-hoc tactile cue cycle metrics from haptic and wrist CSV logs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import median
from typing import Any


ACTION_EVENTS = {"left", "right", "up", "down", "slip"}
DEFAULT_RESPONSE_TIMEOUT_MS = 5000.0
DEFAULT_STABLE_MS = 150.0


def analyze_session(
    session_dir: str | Path,
    *,
    output_path: str | Path | None = None,
    response_timeout_ms: float = DEFAULT_RESPONSE_TIMEOUT_MS,
    stable_ms: float = DEFAULT_STABLE_MS,
) -> Path:
    target = Path(session_dir)
    summary = _read_json(target / "summary.json")
    haptic_rows = _read_csv(target / "haptic_events.csv")
    wrist_rows = _read_csv(target / "wrist_rotation_timeseries.csv")

    cues = [
        row
        for row in haptic_rows
        if str(row.get("event_name", "")).strip().lower() in ACTION_EVENTS
        and _float_or_none(row.get("actual_emit_ms") or row.get("monotonic_ms"))
        is not None
    ]
    metrics: list[dict[str, Any]] = []
    for index, cue in enumerate(cues):
        cue_name = str(cue.get("event_name", "")).strip().lower()
        onset_ms = float(cue.get("actual_emit_ms") or cue.get("monotonic_ms"))
        next_onset = (
            _float_or_none(cues[index + 1].get("actual_emit_ms") or cues[index + 1].get("monotonic_ms"))
            if index + 1 < len(cues)
            else None
        )
        search_end = onset_ms + float(response_timeout_ms)
        if next_onset is not None:
            search_end = min(search_end, next_onset)

        first_action = _first_stable_action(
            wrist_rows,
            start_ms=onset_ms,
            end_ms=search_end,
            stable_ms=stable_ms,
        )
        expected = _expected_action_for_event(cue_name)
        first_correct = (
            None if expected is None or first_action is None else first_action["action"] == expected
        )
        correction = None
        final_action = first_action
        if first_correct is False:
            correction = _first_stable_action(
                wrist_rows,
                start_ms=float(first_action["monotonic_ms"]),
                end_ms=search_end,
                stable_ms=stable_ms,
                expected_action=expected,
            )
            if correction is not None:
                final_action = correction

        neutral_start = (
            float(final_action["stable_until_ms"])
            if final_action is not None
            else onset_ms
        )
        neutral = _first_stable_neutral(
            wrist_rows,
            start_ms=neutral_start,
            end_ms=search_end,
            stable_ms=stable_ms,
        )
        metrics.append(
            {
                "session_id": summary.get("session_id", target.name),
                "participant_id": summary.get("participant_id", ""),
                "feedback_condition": summary.get("feedback_condition")
                or summary.get("condition_id", ""),
                "task_condition": summary.get("task_condition", "dual"),
                "plan_id": summary.get("haptic_plan_id", ""),
                "event_name": cue_name,
                "event_position": index + 1,
                "emit_trial_number": cue.get("emit_trial_number", ""),
                "cue_onset_ms": onset_ms,
                "next_cue_onset_ms": next_onset,
                "response_timeout_ms": float(response_timeout_ms),
                "expected_action": expected or "",
                "first_action": first_action["action"] if first_action else "",
                "first_action_ms": first_action["monotonic_ms"] if first_action else None,
                "first_response_correct": first_correct,
                "first_response_rt_ms": (
                    float(first_action["monotonic_ms"]) - onset_ms
                    if first_action is not None
                    else None
                ),
                "correction_action": correction["action"] if correction else "",
                "correction_ms": correction["monotonic_ms"] if correction else None,
                "correction_time_ms": (
                    float(correction["monotonic_ms"]) - onset_ms
                    if correction is not None
                    else None
                ),
                "final_action": final_action["action"] if final_action else "",
                "final_action_ms": final_action["monotonic_ms"] if final_action else None,
                "neutral_return_ms": neutral["monotonic_ms"] if neutral else None,
                "return_time_ms": (
                    float(neutral["monotonic_ms"]) - float(final_action["monotonic_ms"])
                    if neutral is not None and final_action is not None
                    else None
                ),
                "full_cycle_ms": (
                    float(neutral["monotonic_ms"]) - onset_ms
                    if neutral is not None
                    else None
                ),
            }
        )

    out_path = Path(output_path) if output_path is not None else target / "cue_cycle_metrics.csv"
    _write_metrics(out_path, metrics)
    _write_summary(target / "cue_cycle_summary.json", metrics)
    return out_path


def _first_stable_action(
    rows: list[dict[str, str]],
    *,
    start_ms: float,
    end_ms: float,
    stable_ms: float,
    expected_action: str | None = None,
) -> dict[str, Any] | None:
    labels = {"left", "right", "up", "down"}
    if expected_action is not None:
        labels = {expected_action}
    return _first_stable_label(rows, labels=labels, start_ms=start_ms, end_ms=end_ms, stable_ms=stable_ms)


def _first_stable_neutral(
    rows: list[dict[str, str]],
    *,
    start_ms: float,
    end_ms: float,
    stable_ms: float,
) -> dict[str, Any] | None:
    return _first_stable_label(rows, labels={"neutral"}, start_ms=start_ms, end_ms=end_ms, stable_ms=stable_ms)


def _first_stable_label(
    rows: list[dict[str, str]],
    *,
    labels: set[str],
    start_ms: float,
    end_ms: float,
    stable_ms: float,
) -> dict[str, Any] | None:
    active_label = ""
    active_start: float | None = None
    previous_ms: float | None = None
    for row in rows:
        current_ms = _float_or_none(row.get("monotonic_ms"))
        if current_ms is None or current_ms < start_ms:
            continue
        if current_ms > end_ms:
            break
        label = _row_action_label(row)
        if label in labels:
            if label != active_label:
                active_label = label
                active_start = current_ms
            previous_ms = current_ms
            if active_start is not None and current_ms - active_start >= stable_ms:
                return {
                    "action": label,
                    "monotonic_ms": active_start,
                    "stable_until_ms": current_ms,
                }
            continue
        active_label = ""
        active_start = None
        previous_ms = current_ms
    if (
        active_label in labels
        and active_start is not None
        and previous_ms is not None
        and previous_ms - active_start >= stable_ms
    ):
        return {
            "action": active_label,
            "monotonic_ms": active_start,
            "stable_until_ms": previous_ms,
        }
    return None


def _row_action_label(row: dict[str, str]) -> str:
    lr = str(row.get("wrist_rotation_class", "")).strip().lower()
    up_down = str(row.get("wrist_up_down_class", "")).strip().lower()
    if lr in {"left", "right"}:
        return lr
    if up_down in {"up", "down"}:
        return up_down
    if lr == "neutral" and up_down in {"neutral", "unknown", ""}:
        return "neutral"
    if up_down == "neutral" and lr in {"neutral", "unknown", ""}:
        return "neutral"
    return "unknown"


def _expected_action_for_event(event_name: str) -> str | None:
    if event_name in {"left", "right", "up", "down"}:
        return event_name
    return None


def _write_metrics(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "session_id",
        "participant_id",
        "feedback_condition",
        "task_condition",
        "plan_id",
        "event_name",
        "event_position",
        "emit_trial_number",
        "cue_onset_ms",
        "next_cue_onset_ms",
        "response_timeout_ms",
        "expected_action",
        "first_action",
        "first_action_ms",
        "first_response_correct",
        "first_response_rt_ms",
        "correction_action",
        "correction_ms",
        "correction_time_ms",
        "final_action",
        "final_action_ms",
        "neutral_return_ms",
        "return_time_ms",
        "full_cycle_ms",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    full_cycles = [
        float(row["full_cycle_ms"])
        for row in rows
        if row.get("full_cycle_ms") is not None
    ]
    payload = {
        "cue_count": len(rows),
        "full_cycle_valid_count": len(full_cycles),
        "full_cycle_ms_median": _percentile(full_cycles, 50),
        "full_cycle_ms_p90": _percentile(full_cycles, 90),
        "full_cycle_ms_p95": _percentile(full_cycles, 95),
        "full_cycle_ms_max": max(full_cycles) if full_cycles else None,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if pct == 50:
        return float(median(values))
    ordered = sorted(values)
    position = (len(ordered) - 1) * float(pct) / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze tactile cue response cycles.")
    parser.add_argument("session_dir")
    parser.add_argument("--output", default=None)
    parser.add_argument("--response-timeout-ms", type=float, default=DEFAULT_RESPONSE_TIMEOUT_MS)
    parser.add_argument("--stable-ms", type=float, default=DEFAULT_STABLE_MS)
    args = parser.parse_args()
    output = analyze_session(
        args.session_dir,
        output_path=args.output,
        response_timeout_ms=args.response_timeout_ms,
        stable_ms=args.stable_ms,
    )
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
