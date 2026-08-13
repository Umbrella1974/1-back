from __future__ import annotations

import csv
import json

from analyze_cue_cycles import analyze_session


def test_analyze_cue_cycle_records_correction_and_neutral_return(tmp_path) -> None:
    session = tmp_path / "session-a"
    session.mkdir()
    (session / "summary.json").write_text(
        json.dumps(
            {
                "session_id": "session-a",
                "participant_id": "p03",
                "condition_id": "motor-dual-plan4",
                "haptic_plan_id": "only-motor",
            }
        ),
        encoding="utf-8",
    )
    _write_csv(
        session / "haptic_events.csv",
        [
            {
                "event_name": "left",
                "actual_emit_ms": "1000",
                "monotonic_ms": "1000",
                "emit_trial_number": "20",
            }
        ],
    )
    _write_csv(
        session / "wrist_rotation_timeseries.csv",
        [
            _wrist_row(1000, "neutral", "neutral"),
            _wrist_row(1100, "right", "neutral"),
            _wrist_row(1300, "right", "neutral"),
            _wrist_row(1500, "left", "neutral"),
            _wrist_row(1700, "left", "neutral"),
            _wrist_row(1900, "neutral", "neutral"),
            _wrist_row(2100, "neutral", "neutral"),
        ],
    )

    output = analyze_session(session, stable_ms=150, response_timeout_ms=5000)

    rows = _read_csv(output)
    summary = json.loads((session / "cue_cycle_summary.json").read_text(encoding="utf-8"))
    assert rows[0]["event_name"] == "left"
    assert rows[0]["first_action"] == "right"
    assert rows[0]["first_response_correct"] == "False"
    assert rows[0]["correction_action"] == "left"
    assert rows[0]["final_action"] == "left"
    assert rows[0]["neutral_return_ms"] == "1900.0"
    assert rows[0]["full_cycle_ms"] == "900.0"
    assert summary["cue_count"] == 1
    assert summary["full_cycle_ms_median"] == 900.0


def _write_csv(path, rows):
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _wrist_row(ms: float, lr: str, up_down: str) -> dict[str, str]:
    return {
        "monotonic_ms": str(float(ms)),
        "wrist_rotation_class": lr,
        "wrist_up_down_class": up_down,
    }
