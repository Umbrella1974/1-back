from __future__ import annotations

import csv
import json

from analyze_cue_response_metrics import analyze_root


def test_unified_analysis_scores_wrist_and_slip_without_baseline_return(tmp_path) -> None:
    session = tmp_path / "pinch_haptic_1back_test"
    session.mkdir()
    _write_json(
        session / "summary.json",
        {
            "session_id": "pinch_haptic_1back_test",
            "participant_id": "p01",
            "haptic_plan_id": "only-matrix-1",
        },
    )
    _write_json(
        session / "wrist_rotation_calibration.json",
        {
            "classification_margin": 0.15,
            "left_score_mean": 0.4,
            "right_score_mean": -0.4,
            "threshold": 0.0,
            "up_score_mean": 0.4,
            "down_score_mean": -0.4,
            "up_down_threshold": 0.0,
        },
    )
    _write_csv(
        session / "haptic_events.csv",
        [
            _haptic("contact", 500, 1),
            _haptic("left", 1000, 2, gate="False"),
            _haptic("slip", 3000, 3),
            _haptic("slip_matrix_step_2", 3100, 3, source="slip"),
            _haptic("up", 6000, 4),
            _haptic("right", 8000, 5),
            _haptic("down", 10000, 6),
            _haptic("release", 12000, 7),
        ],
    )
    _write_csv(
        session / "wrist_rotation_timeseries.csv",
        [
            _wrist(1000, 0.0, 0.0, "up", "up"),
            _wrist(1100, 0.0, 0.0, "up", "up"),
            _wrist(1200, 0.30, 0.0, "left", "up"),
            _wrist(1400, 0.30, 0.0, "left", "up"),
            _wrist(1600, 0.0, 0.0, "up", "up"),
            _wrist(1800, 0.0, 0.0, "up", "up"),
        ],
    )
    pinch_rows = []
    for ms in (2600, 2700, 2800, 2900):
        pinch_rows.append(_pinch(ms, 0.55))
    for ms in (4200, 4300, 4400):
        pinch_rows.append(_pinch(ms, 0.05))
    for ms in (4700, 4800, 4900):
        pinch_rows.append(_pinch(ms, 0.40))
    _write_csv(session / "pinch_timeseries.csv", pinch_rows)

    metrics_path, wrist_path, up_path, summary_path = analyze_root(
        tmp_path,
        output_dir=tmp_path / "analysis",
    )
    diagnostics_path = metrics_path.parent / "cue_response_diagnostics.csv"

    metrics = _read_csv(metrics_path)
    left = next(row for row in metrics if row["event_name"] == "left")
    slip = next(row for row in metrics if row["event_name"] == "slip")
    wrist = _read_csv(wrist_path)
    diagnostics = _read_csv(diagnostics_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert left["response_source"] == "wrist"
    assert left["trial_quality"] == "clean"
    assert left["response_quality"] == "clean"
    assert left["cycle_quality"] == "complete"
    assert left["offline_neutral_centered_gate_passed"] == "True"
    assert left["first_wrist_direction"] == "left"
    assert left["correct_response_rt_ms"] == "200.0"
    assert slip["response_source"] == "pinch"
    assert slip["trial_quality"] == "clean"
    assert slip["response_quality"] == "clean"
    assert slip["cycle_quality"] == "complete"
    assert slip["pinch_detected"] == "True"
    assert slip["release_detected"] == "True"
    assert slip["returned_to_precue_baseline"] == "False"
    assert float(slip["peak_closure_delta"]) > 0.45
    assert wrist[0]["online_gate_passed"] == "False"
    assert wrist[0]["offline_neutral_centered_gate_passed"] == "True"
    assert up_path.exists()
    assert diagnostics_path.exists()
    left_diagnostic = next(row for row in diagnostics if row["event_name"] == "left")
    slip_diagnostic = next(row for row in diagnostics if row["event_name"] == "slip")
    assert left_diagnostic["analysis_axis"] == "lr"
    assert left_diagnostic["first_excursion_direction"] == "left"
    assert slip_diagnostic["analysis_axis"] == "pinch_closure"
    assert slip_diagnostic["expected_excursion_direction"] == "pinch"
    assert slip_diagnostic["expected_excursion_detected"] == "True"
    assert summary["cue_count"] == 7
    assert summary["cue_response_diagnostic_count"] == 5
    assert summary["participant_id_missing_count"] == 0


def test_recoverable_wrist_trial_uses_correct_response_rt_not_preexisting_zero(tmp_path) -> None:
    session = tmp_path / "pinch_haptic_1back_recoverable"
    session.mkdir()
    _write_json(
        session / "summary.json",
        {
            "session_id": "pinch_haptic_1back_recoverable",
            "participant_id": "p01",
            "haptic_plan_id": "only-matrix-1",
        },
    )
    _write_json(
        session / "wrist_rotation_calibration.json",
        {
            "classification_margin": 0.15,
            "left_score_mean": 0.4,
            "right_score_mean": -0.4,
            "threshold": 0.0,
            "up_score_mean": 0.4,
            "down_score_mean": -0.4,
            "up_down_threshold": 0.0,
        },
    )
    _write_csv(
        session / "haptic_events.csv",
        [
            _haptic("contact", 500, 1),
            _haptic("left", 1000, 2, gate="False"),
            _haptic("slip", 3000, 3),
            _haptic("up", 5000, 4),
            _haptic("right", 7000, 5),
            _haptic("down", 9000, 6),
            _haptic("release", 11000, 7),
        ],
    )
    _write_csv(
        session / "wrist_rotation_timeseries.csv",
        [
            _wrist(900, -0.30, 0.0, "right", "neutral"),
            _wrist(1000, -0.30, 0.0, "right", "neutral"),
            _wrist(1100, -0.30, 0.0, "right", "neutral"),
            _wrist(1200, 0.0, 0.0, "neutral", "neutral"),
            _wrist(1300, 0.30, 0.0, "left", "neutral"),
            _wrist(1500, 0.30, 0.0, "left", "neutral"),
            _wrist(1700, 0.0, 0.0, "neutral", "neutral"),
            _wrist(1900, 0.0, 0.0, "neutral", "neutral"),
        ],
    )
    _write_csv(
        session / "pinch_timeseries.csv",
        [_pinch(ms, 0.55) for ms in (2500, 2600, 2700, 2800, 2900, 3100, 3200)],
    )

    metrics_path, _, _, _ = analyze_root(tmp_path, output_dir=tmp_path / "analysis")

    left = next(row for row in _read_csv(metrics_path) if row["event_name"] == "left")

    assert left["pre_existing_response_at_cue"] == "right"
    assert left["response_quality"] == "recoverable"
    assert left["first_response"] == "right"
    assert left["first_response_rt_ms"] == ""
    assert left["correct_response_rt_ms"] == "300.0"
    assert left["response_rt_ms"] == "300.0"
    assert left["was_corrected"] == "True"
    assert left["correction_time_ms"] == "300.0"


def test_first_excursion_can_capture_short_up_before_down_overshoot(tmp_path) -> None:
    session = tmp_path / "pinch_haptic_1back_up_overshoot"
    session.mkdir()
    _write_json(
        session / "summary.json",
        {
            "session_id": "pinch_haptic_1back_up_overshoot",
            "participant_id": "p01",
            "haptic_plan_id": "only-matrix-1",
        },
    )
    _write_json(
        session / "wrist_rotation_calibration.json",
        {
            "classification_margin": 0.15,
            "left_score_mean": 0.4,
            "right_score_mean": -0.4,
            "threshold": 0.0,
            "up_score_mean": 0.4,
            "down_score_mean": -0.4,
            "up_down_threshold": 0.0,
        },
    )
    _write_csv(
        session / "haptic_events.csv",
        [
            _haptic("contact", 500, 1),
            _haptic("left", 1000, 2),
            _haptic("slip", 3000, 3),
            _haptic("up", 5000, 4),
            _haptic("right", 7000, 5),
            _haptic("down", 9000, 6),
            _haptic("release", 11000, 7),
        ],
    )
    _write_csv(
        session / "wrist_rotation_timeseries.csv",
        [
            _wrist(4900, 0.0, 0.0, "neutral", "neutral"),
            _wrist(5000, 0.0, 0.0, "neutral", "neutral"),
            _wrist(5050, 0.0, 0.12, "neutral", "neutral"),
            _wrist(5100, 0.0, 0.12, "neutral", "neutral"),
            _wrist(5150, 0.0, -0.30, "neutral", "down"),
            _wrist(5200, 0.0, -0.30, "neutral", "down"),
            _wrist(5350, 0.0, -0.30, "neutral", "down"),
            _wrist(5550, 0.0, 0.0, "neutral", "neutral"),
            _wrist(5750, 0.0, 0.0, "neutral", "neutral"),
        ],
    )
    _write_csv(session / "pinch_timeseries.csv", [_pinch(ms, 0.55) for ms in (2500, 2600)])

    metrics_path, _, _, _ = analyze_root(tmp_path, output_dir=tmp_path / "analysis")

    up_metric = next(row for row in _read_csv(metrics_path) if row["event_name"] == "up")
    diagnostics = _read_csv(metrics_path.parent / "cue_response_diagnostics.csv")
    up_diagnostic = next(row for row in diagnostics if row["event_name"] == "up")

    assert up_metric["first_response"] == "down"
    assert up_metric["response_quality"] == "contaminated"
    assert up_diagnostic["analysis_axis"] == "ud"
    assert up_diagnostic["first_excursion_direction"] == "up"
    assert up_diagnostic["expected_excursion_detected"] == "True"
    assert up_diagnostic["reversal_detected"] == "True"
    assert up_diagnostic["reversal_direction"] == "down"
    assert up_diagnostic["stable_matches_first_excursion"] == "False"


def _haptic(name: str, ms: float, trial: int, *, gate: str = "", source: str = "") -> dict[str, str]:
    return {
        "event_name": name,
        "source_event_name": source,
        "actual_emit_ms": str(float(ms)),
        "monotonic_ms": str(float(ms)),
        "emit_trial_number": str(trial),
        "wrist_neutral_gate_passed": gate,
    }


def _wrist(ms: float, lr_score: float, ud_score: float, lr_class: str, ud_class: str) -> dict[str, str]:
    return {
        "monotonic_ms": str(float(ms)),
        "wrist_rotation_score": str(float(lr_score)),
        "wrist_up_down_score": str(float(ud_score)),
        "wrist_rotation_class": lr_class,
        "wrist_up_down_class": ud_class,
    }


def _pinch(ms: float, distance: float) -> dict[str, str]:
    return {
        "monotonic_ms": str(float(ms)),
        "pinch_distance": str(float(distance)),
        "min_distance": "0.0",
        "max_distance": "1.0",
    }


def _write_json(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path, rows) -> None:
    fields = sorted({field for row in rows for field in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
