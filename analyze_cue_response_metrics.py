"""Unified offline cue-response metrics for wrist and slip S-R mappings."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any, Callable


DETECTOR_VERSION = "pilot_v0.3"
WRIST_EVENTS = {"left", "right", "up", "down"}
PINCH_EVENTS = {"slip"}
PINCH_STATE_EVENTS = {"contact", "release"}
SEMANTIC_EVENTS = WRIST_EVENTS | PINCH_EVENTS | {"contact", "release"}
BASELINE_WINDOW_MS = 500.0
STABLE_MS = 150.0
EXCURSION_STABLE_MS = 50.0
PINCH_MIN_DELTA = 0.05
BASELINE_RETURN_MIN_DELTA = 0.03
SATURATED_CLOSURE = 0.90


UNIFIED_FIELDS = [
    "session_id",
    "participant_id",
    "condition",
    "task_type",
    "nback_enabled",
    "plan_id",
    "event_name",
    "event_position",
    "emit_trial_number",
    "response_source",
    "expected_response",
    "cue_onset_ms",
    "next_cue_onset_ms",
    "response_onset_ms",
    "response_rt_ms",
    "first_response_onset_ms",
    "first_response_rt_ms",
    "correct_response_onset_ms",
    "correct_response_rt_ms",
    "first_response",
    "first_response_correct",
    "was_corrected",
    "correction_time_ms",
    "eventual_correct",
    "response_sequence_complete",
    "response_end_ms",
    "full_cycle_ms",
    "response_quality",
    "response_quality_reason",
    "cycle_quality",
    "cycle_quality_reason",
    "trial_quality",
    "quality_reason",
    "detector_version",
]

WRIST_EXTRA_FIELDS = [
    "first_wrist_direction",
    "correct_wrist_direction",
    "neutral_return_ms",
    "neutral_return_completion_ms",
    "lr_score_at_onset",
    "ud_score_at_onset",
    "old_lr_class_at_onset",
    "old_ud_class_at_onset",
    "offline_lr_class_at_onset",
    "offline_ud_class_at_onset",
    "online_gate_passed",
    "old_lr_neutral_lower",
    "old_lr_neutral_upper",
    "old_lr_zero_in_neutral_region",
    "old_ud_neutral_lower",
    "old_ud_neutral_upper",
    "old_ud_zero_in_neutral_region",
    "offline_neutral_centered_gate_passed",
    "lr_neutral_centered_sanity_passed",
    "ud_neutral_centered_sanity_passed",
    "pre_existing_response_at_cue",
]

SLIP_EXTRA_FIELDS = [
    "pinch_reference_quality_passed",
    "pinch_reference_quality_reason",
    "contact_reference_available",
    "pre_cue_pinch_state",
    "post_cue_target_state",
    "baseline_pinch_distance",
    "distance_to_open",
    "distance_to_contact",
    "distance_to_pinch",
    "baseline_reference_position",
    "entered_open_reference",
    "entered_contact_reference",
    "entered_pinch_reference",
    "open_reference_onset_ms",
    "contact_reference_onset_ms",
    "pinch_reference_onset_ms",
    "baseline_closure",
    "baseline_closure_mad",
    "baseline_stability",
    "pinch_onset_ms",
    "pinch_rt_ms",
    "pinch_detected",
    "peak_closure",
    "peak_closure_delta",
    "peak_time_ms",
    "release_onset_ms",
    "release_completion_ms",
    "release_drop",
    "release_detected",
    "return_to_precue_baseline_ms",
    "return_to_precue_baseline_completion_ms",
    "returned_to_precue_baseline",
]

OUTPUT_FIELDS = UNIFIED_FIELDS + WRIST_EXTRA_FIELDS + SLIP_EXTRA_FIELDS

UP_DIAGNOSTIC_FIELDS = [
    "session_id",
    "participant_id",
    "condition",
    "task_type",
    "nback_enabled",
    "plan_id",
    "event_position",
    "emit_trial_number",
    "cue_onset_ms",
    "pre_cue_state",
    "offline_lr_class_at_onset",
    "offline_ud_class_at_onset",
    "first_stable_direction",
    "first_direction_rt_ms",
    "max_up_score_after_cue",
    "min_down_score_after_cue",
    "eventual_up_detected",
    "correct_response_onset_ms",
    "correct_response_rt_ms",
    "was_corrected",
    "response_quality",
    "cycle_quality",
    "quality_reason",
]

CUE_DIAGNOSTIC_FIELDS = [
    "session_id",
    "participant_id",
    "condition",
    "plan_id",
    "event_name",
    "event_position",
    "emit_trial_number",
    "cue_onset_ms",
    "next_cue_onset_ms",
    "response_source",
    "analysis_axis",
    "expected_excursion_direction",
    "baseline_center",
    "baseline_mad",
    "excursion_threshold",
    "pre_cue_value",
    "value_at_onset",
    "first_excursion_direction",
    "first_excursion_onset_ms",
    "first_excursion_rt_ms",
    "first_excursion_peak_value",
    "first_excursion_peak_delta",
    "first_excursion_peak_ms",
    "first_excursion_duration_ms",
    "expected_excursion_detected",
    "expected_excursion_onset_ms",
    "expected_excursion_rt_ms",
    "reversal_detected",
    "reversal_direction",
    "reversal_onset_ms",
    "reversal_rt_ms",
    "overshoot_peak_value",
    "overshoot_peak_delta",
    "overshoot_peak_ms",
    "first_stable_direction",
    "first_stable_rt_ms",
    "stable_matches_first_excursion",
    "response_quality",
    "cycle_quality",
    "quality_reason",
    "detector_version",
]


def analyze_root(
    root_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> tuple[Path, Path, Path, Path]:
    root = Path(root_dir)
    out_dir = Path(output_dir) if output_dir is not None else root
    out_dir.mkdir(parents=True, exist_ok=True)
    cue_rows: list[dict[str, Any]] = []
    wrist_rows: list[dict[str, Any]] = []
    up_rows: list[dict[str, Any]] = []
    diagnostic_rows: list[dict[str, Any]] = []
    for session_dir in _session_dirs(root):
        summary = _read_json(session_dir / "summary.json")
        haptics = _read_csv(session_dir / "haptic_events.csv")
        semantic_haptics = _semantic_haptic_rows(haptics)
        if not _is_analyzable_session(summary, semantic_haptics):
            continue
        wrist_calibration = _read_json(session_dir / "wrist_rotation_calibration.json")
        pinch_calibration = _read_json(session_dir / "calibration.json")
        wrist = _read_csv(session_dir / "wrist_rotation_timeseries.csv")
        pinch = _read_csv(session_dir / "pinch_timeseries.csv")
        for event_position, cue in enumerate(semantic_haptics, start=1):
            event_name = _text(cue.get("event_name")).lower()
            if event_name not in SEMANTIC_EVENTS:
                continue
            next_onset = _next_semantic_onset(semantic_haptics, event_position - 1)
            if event_name in WRIST_EVENTS:
                row, audit, up_diagnostic = _analyze_wrist_cue(
                    cue,
                    event_position=event_position,
                    next_onset_ms=next_onset,
                    summary=summary,
                    wrist_rows=wrist,
                    calibration=wrist_calibration,
                )
                cue_rows.append(row)
                wrist_rows.append(audit)
                diagnostic_rows.append(
                    _wrist_excursion_diagnostic_row(
                        row,
                        wrist_rows=wrist,
                        calibration=wrist_calibration,
                    )
                )
                if up_diagnostic is not None:
                    up_rows.append(up_diagnostic)
            elif event_name in PINCH_EVENTS:
                row = _analyze_slip_cue(
                    cue,
                    event_position=event_position,
                    next_onset_ms=next_onset,
                    summary=summary,
                    pinch_rows=pinch,
                    pinch_calibration=pinch_calibration,
                )
                cue_rows.append(row)
                diagnostic_rows.append(_pinch_excursion_diagnostic_row(row, pinch_rows=pinch))
            elif event_name in PINCH_STATE_EVENTS:
                row = _analyze_pinch_state_cue(
                    cue,
                    event_position=event_position,
                    next_onset_ms=next_onset,
                    summary=summary,
                    pinch_rows=pinch,
                    pinch_calibration=pinch_calibration,
                )
                cue_rows.append(row)
                diagnostic_rows.append(_pinch_excursion_diagnostic_row(row, pinch_rows=pinch))
            else:
                cue_rows.append(
                    _empty_event_row(
                        cue,
                        event_position=event_position,
                        next_onset_ms=next_onset,
                        summary=summary,
                    )
                )
    metrics_path = out_dir / "cue_response_metrics.csv"
    wrist_path = out_dir / "wrist_neutral_reclass.csv"
    up_path = out_dir / "up_diagnostics.csv"
    diagnostics_path = out_dir / "cue_response_diagnostics.csv"
    summary_path = out_dir / "cue_response_summary.json"
    _write_csv(metrics_path, cue_rows, OUTPUT_FIELDS)
    _write_csv(wrist_path, wrist_rows, WRIST_AUDIT_FIELDS)
    _write_csv(up_path, up_rows, UP_DIAGNOSTIC_FIELDS)
    _write_csv(diagnostics_path, diagnostic_rows, CUE_DIAGNOSTIC_FIELDS)
    summary_path.write_text(
        json.dumps(
            _summary_payload(cue_rows, wrist_rows, up_rows, diagnostic_rows),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return metrics_path, wrist_path, up_path, summary_path


WRIST_AUDIT_FIELDS = [
    "session_id",
    "condition",
    "plan_id",
    "event_name",
    "event_position",
    "emit_trial_number",
    "cue_onset_ms",
    "online_gate_passed",
    "old_lr_class_at_onset",
    "old_ud_class_at_onset",
    "offline_lr_class_at_onset",
    "offline_ud_class_at_onset",
    "offline_neutral_centered_gate_passed",
    "lr_score_at_onset",
    "ud_score_at_onset",
    "old_lr_neutral_lower",
    "old_lr_neutral_upper",
    "old_lr_zero_in_neutral_region",
    "old_ud_neutral_lower",
    "old_ud_neutral_upper",
    "old_ud_zero_in_neutral_region",
    "lr_neutral_centered_sanity_passed",
    "ud_neutral_centered_sanity_passed",
]


def _analyze_wrist_cue(
    cue: dict[str, str],
    *,
    event_position: int,
    next_onset_ms: float | None,
    summary: dict[str, Any],
    wrist_rows: list[dict[str, str]],
    calibration: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    event_name = _text(cue.get("event_name")).lower()
    onset = _float_or_none(cue.get("actual_emit_ms") or cue.get("monotonic_ms"))
    base = _base_row(cue, event_position, next_onset_ms, summary)
    base.update(
        {
            "response_source": "wrist",
            "expected_response": event_name,
            "detector_version": DETECTOR_VERSION,
        }
    )
    if onset is None or not wrist_rows:
        base.update(
            {
                "trial_quality": "insufficient_wrist_data",
                "quality_reason": "missing_onset_or_wrist_timeseries",
                "response_quality": "insufficient_wrist_data",
                "response_quality_reason": "missing_onset_or_wrist_timeseries",
                "cycle_quality": "not_applicable",
                "cycle_quality_reason": "missing_onset_or_wrist_timeseries",
            }
        )
        filled = _fill_output_row(base)
        return filled, _wrist_audit_row(base), _up_diagnostic_row(base) if event_name == "up" else None

    onset_row = _nearest_row(wrist_rows, onset)
    pre_cue_row = _last_row_before(wrist_rows, onset)
    onset_lr = _offline_lr_label(onset_row, calibration)
    onset_ud = _offline_ud_label(onset_row, calibration)
    pre_cue_state = _offline_wrist_action_label(pre_cue_row, calibration) if pre_cue_row else ""
    pre_existing_action = _offline_wrist_action_label(onset_row, calibration)
    if pre_existing_action not in WRIST_EVENTS:
        pre_existing_action = ""
    old_lr_region = _old_region(calibration, axis="lr")
    old_ud_region = _old_region(calibration, axis="ud")
    lr_sanity = _centered_sanity(calibration, axis="lr")
    ud_sanity = _centered_sanity(calibration, axis="ud")
    audit_values = {
        "lr_score_at_onset": _float_or_none(onset_row.get("wrist_rotation_score") if onset_row else None),
        "ud_score_at_onset": _float_or_none(onset_row.get("wrist_up_down_score") if onset_row else None),
        "old_lr_class_at_onset": onset_row.get("wrist_rotation_class", "") if onset_row else "",
        "old_ud_class_at_onset": onset_row.get("wrist_up_down_class", "") if onset_row else "",
        "offline_lr_class_at_onset": onset_lr,
        "offline_ud_class_at_onset": onset_ud,
        "online_gate_passed": cue.get("wrist_neutral_gate_passed", ""),
        "old_lr_neutral_lower": old_lr_region.get("lower"),
        "old_lr_neutral_upper": old_lr_region.get("upper"),
        "old_lr_zero_in_neutral_region": old_lr_region.get("zero_in_region"),
        "old_ud_neutral_lower": old_ud_region.get("lower"),
        "old_ud_neutral_upper": old_ud_region.get("upper"),
        "old_ud_zero_in_neutral_region": old_ud_region.get("zero_in_region"),
        "offline_neutral_centered_gate_passed": onset_lr == "neutral" and onset_ud == "neutral",
        "lr_neutral_centered_sanity_passed": lr_sanity,
        "ud_neutral_centered_sanity_passed": ud_sanity,
        "pre_existing_response_at_cue": pre_existing_action,
    }
    base.update(audit_values)

    end = next_onset_ms if next_onset_ms is not None else onset + 8000.0
    response_search_start = _next_after_pre_existing_wrist_state(
        wrist_rows,
        calibration,
        start_ms=onset,
        end_ms=end,
        pre_existing_action=pre_existing_action,
    )
    first_action = _first_stable_wrist_action(
        wrist_rows,
        calibration,
        start_ms=response_search_start,
        end_ms=end,
        stable_ms=STABLE_MS,
    )
    pre_existing_correct = pre_existing_action == event_name
    pre_existing_wrong = pre_existing_action in WRIST_EVENTS and pre_existing_action != event_name
    first_response_label = pre_existing_action if pre_existing_action else (
        first_action["action"] if first_action else ""
    )
    first_response_onset = None if pre_existing_action else (
        first_action["monotonic_ms"] if first_action else None
    )
    first_response_rt = None if pre_existing_action else (
        float(first_action["monotonic_ms"]) - onset if first_action else None
    )
    first_correct = (
        pre_existing_correct
        if pre_existing_action
        else (None if first_action is None else first_action["action"] == event_name)
    )
    correction = None
    final_action = first_action
    if pre_existing_wrong:
        correction = _first_stable_wrist_action(
            wrist_rows,
            calibration,
            start_ms=response_search_start,
            end_ms=end,
            stable_ms=STABLE_MS,
            expected_action=event_name,
        )
        final_action = correction
    elif first_correct is False:
        correction = _first_stable_wrist_action(
            wrist_rows,
            calibration,
            start_ms=float(first_action["monotonic_ms"]),
            end_ms=end,
            stable_ms=STABLE_MS,
            expected_action=event_name,
        )
        if correction is not None:
            final_action = correction
    elif pre_existing_correct:
        final_action = None
    eventual_correct = (
        True if pre_existing_correct else (
            None if final_action is None else final_action["action"] == event_name
        )
    )
    correct_action = None
    if pre_existing_correct:
        correct_action = None
    elif first_correct is True:
        correct_action = first_action
    elif correction is not None:
        correct_action = correction
    neutral = None
    if correct_action is not None:
        neutral = _first_stable_wrist_neutral(
            wrist_rows,
            calibration,
            start_ms=float(correct_action["stable_until_ms"]),
            end_ms=end,
            stable_ms=STABLE_MS,
        )
    clean_at_onset = onset_lr == "neutral" and onset_ud == "neutral"
    if pre_existing_correct:
        response_quality, response_reason = "contaminated", "pre_existing_correct_action_at_cue"
    elif correct_action is None and first_action is None and not pre_existing_wrong:
        response_quality, response_reason = "contaminated", "no_stable_wrist_action_before_next_cue"
    elif eventual_correct is not True:
        response_quality, response_reason = "contaminated", "no_correct_wrist_action_before_next_cue"
    elif clean_at_onset:
        response_quality, response_reason = "clean", ""
    else:
        response_quality, response_reason = "recoverable", "cue_onset_not_neutral_by_offline_classifier"
    if correct_action is None:
        cycle_quality, cycle_reason = "not_applicable", "no_correct_wrist_action_before_next_cue"
    elif neutral is None:
        cycle_quality, cycle_reason = "incomplete_return", "neutral_return_not_detected_before_next_cue"
    else:
        cycle_quality, cycle_reason = "complete", ""
    quality = response_quality
    reason = response_reason

    base.update(
        {
            "response_onset_ms": correct_action["monotonic_ms"] if correct_action else None,
            "response_rt_ms": (
                float(correct_action["monotonic_ms"]) - onset if correct_action else None
            ),
            "first_response_onset_ms": first_response_onset,
            "first_response_rt_ms": first_response_rt,
            "correct_response_onset_ms": (
                correct_action["monotonic_ms"] if correct_action else None
            ),
            "correct_response_rt_ms": (
                float(correct_action["monotonic_ms"]) - onset if correct_action else None
            ),
            "first_response": first_response_label,
            "first_response_correct": first_correct,
            "was_corrected": correction is not None,
            "correction_time_ms": (
                float(correction["monotonic_ms"]) - onset if correction else None
            ),
            "eventual_correct": eventual_correct,
            "response_end_ms": neutral["stable_until_ms"] if neutral else None,
            "full_cycle_ms": (
                float(neutral["stable_until_ms"]) - onset if neutral else None
            ),
            "response_quality": response_quality,
            "response_quality_reason": response_reason,
            "cycle_quality": cycle_quality,
            "cycle_quality_reason": cycle_reason,
            "trial_quality": quality,
            "quality_reason": reason,
            "first_wrist_direction": first_response_label,
            "correct_wrist_direction": correct_action["action"] if correct_action else "",
            "neutral_return_ms": neutral["monotonic_ms"] if neutral else None,
            "neutral_return_completion_ms": neutral["stable_until_ms"] if neutral else None,
        }
    )
    if event_name == "up":
        base.update(
            _up_window_fields(
                wrist_rows,
                onset_ms=onset,
                end_ms=end,
                calibration=calibration,
                pre_cue_state=pre_cue_state,
            )
        )
    filled = _fill_output_row(base)
    return filled, _wrist_audit_row(base), _up_diagnostic_row(base) if event_name == "up" else None


def _analyze_pinch_state_cue(
    cue: dict[str, str],
    *,
    event_position: int,
    next_onset_ms: float | None,
    summary: dict[str, Any],
    pinch_rows: list[dict[str, str]],
    pinch_calibration: dict[str, Any],
) -> dict[str, Any]:
    event_name = _text(cue.get("event_name")).lower()
    onset = _float_or_none(cue.get("actual_emit_ms") or cue.get("monotonic_ms"))
    base = _base_row(cue, event_position, next_onset_ms, summary)
    expected_direction = "closing" if event_name == "contact" else "opening"
    target_state = "contact" if event_name == "contact" else "open"
    base.update(
        {
            "response_source": "pinch",
            "expected_response": (
                "open_to_contact" if event_name == "contact" else "contact_to_open"
            ),
            "post_cue_target_state": target_state,
            "detector_version": DETECTOR_VERSION,
        }
    )
    if onset is None or not pinch_rows:
        base.update(
            {
                "trial_quality": "insufficient_pinch_data",
                "quality_reason": "missing_onset_or_pinch_timeseries",
                "response_quality": "insufficient_pinch_data",
                "response_quality_reason": "missing_onset_or_pinch_timeseries",
                "cycle_quality": "not_applicable",
                "cycle_quality_reason": "missing_onset_or_pinch_timeseries",
            }
        )
        return _fill_output_row(base)

    samples = _pinch_closure_samples(pinch_rows)
    reference = _pinch_reference_model(pinch_calibration)
    baseline = [
        item
        for item in samples
        if onset - BASELINE_WINDOW_MS <= item["monotonic_ms"] < onset
    ]
    if len(baseline) < 3:
        base.update(
            {
                **_pinch_reference_fields(reference, None),
                "trial_quality": "insufficient_pinch_data",
                "quality_reason": "too_few_baseline_samples",
                "response_quality": "insufficient_pinch_data",
                "response_quality_reason": "too_few_baseline_samples",
                "cycle_quality": "not_applicable",
                "cycle_quality_reason": "too_few_baseline_samples",
            }
        )
        return _fill_output_row(base)
    baseline_values = [item["pinch_distance"] for item in baseline]
    baseline_distance = median(baseline_values)
    baseline_mad = _mad(baseline_values, baseline_distance)
    base.update(
        {
            **_pinch_reference_fields(reference, baseline_distance),
            "baseline_pinch_distance": baseline_distance,
            "baseline_stability": baseline_mad,
            "pre_cue_pinch_state": _pinch_state_for_distance(baseline_distance, reference),
        }
    )
    if not reference.get("available"):
        reason = "pinch_reference_quality_insufficient"
        if not reference.get("contact_reference_available"):
            reason = "contact_reference_not_available"
        base.update(
            {
                "trial_quality": "insufficient_pinch_reference",
                "quality_reason": reason,
                "response_quality": "insufficient_pinch_reference",
                "response_quality_reason": reason,
                "cycle_quality": "not_applicable",
                "cycle_quality_reason": reason,
                "response_sequence_complete": False,
            }
        )
        return _fill_output_row(base)

    end = next_onset_ms if next_onset_ms is not None else onset + 8000.0
    window = [item for item in samples if onset <= item["monotonic_ms"] < end]
    if len(window) < 3:
        base.update(
            {
                "trial_quality": "insufficient_pinch_data",
                "quality_reason": "too_few_response_samples",
                "response_quality": "insufficient_pinch_data",
                "response_quality_reason": "too_few_response_samples",
                "cycle_quality": "not_applicable",
                "cycle_quality_reason": "too_few_response_samples",
            }
        )
        return _fill_output_row(base)

    movement_threshold = max(
        baseline_mad * 4.0,
        float(reference.get("open_mad") or 0.0) * 4.0,
        float(reference.get("contact_mad") or 0.0) * 4.0,
        float(reference.get("pinch_mad") or 0.0) * 4.0,
        1e-6,
    )
    first_response = _first_stable_pinch_direction(
        window,
        baseline_distance=baseline_distance,
        threshold=movement_threshold,
        stable_ms=EXCURSION_STABLE_MS,
    )
    correct_response = None
    if first_response is not None and first_response["direction"] == expected_direction:
        correct_response = first_response
    else:
        correct_response = _first_stable_pinch_direction(
            window,
            baseline_distance=baseline_distance,
            threshold=movement_threshold,
            stable_ms=EXCURSION_STABLE_MS,
            expected_direction=expected_direction,
        )
    target = _first_stable_pinch_state(
        window,
        reference,
        state=target_state,
        stable_ms=STABLE_MS,
    )
    first_correct = (
        None if first_response is None else first_response["direction"] == expected_direction
    )
    sequence_complete = target is not None
    if correct_response is None:
        response_quality, response_reason = "contaminated", "no_correct_pinch_direction_before_next_cue"
    else:
        response_quality, response_reason = "clean", ""
    if sequence_complete:
        cycle_quality, cycle_reason = "complete", ""
        trial_quality, reason = response_quality, response_reason
    else:
        cycle_quality, cycle_reason = "incomplete_target_state", f"no_stable_{target_state}_reference_before_next_cue"
        trial_quality, reason = "partial_no_target_state", cycle_reason
    base.update(
        {
            "response_onset_ms": correct_response["monotonic_ms"] if correct_response else None,
            "response_rt_ms": (
                float(correct_response["monotonic_ms"]) - onset if correct_response else None
            ),
            "first_response_onset_ms": (
                first_response["monotonic_ms"] if first_response else None
            ),
            "first_response_rt_ms": (
                float(first_response["monotonic_ms"]) - onset if first_response else None
            ),
            "correct_response_onset_ms": (
                correct_response["monotonic_ms"] if correct_response else None
            ),
            "correct_response_rt_ms": (
                float(correct_response["monotonic_ms"]) - onset if correct_response else None
            ),
            "first_response": first_response["direction"] if first_response else "",
            "first_response_correct": first_correct,
            "was_corrected": first_correct is False and correct_response is not None,
            "correction_time_ms": (
                float(correct_response["monotonic_ms"]) - onset
                if first_correct is False and correct_response is not None
                else None
            ),
            "eventual_correct": sequence_complete,
            "response_sequence_complete": sequence_complete,
            "response_end_ms": target["stable_until_ms"] if target else None,
            "full_cycle_ms": float(target["stable_until_ms"]) - onset if target else None,
            "entered_open_reference": target_state == "open" and target is not None,
            "entered_contact_reference": target_state == "contact" and target is not None,
            "open_reference_onset_ms": (
                target["monotonic_ms"] if target_state == "open" and target else None
            ),
            "contact_reference_onset_ms": (
                target["monotonic_ms"] if target_state == "contact" and target else None
            ),
            "response_quality": response_quality,
            "response_quality_reason": response_reason,
            "cycle_quality": cycle_quality,
            "cycle_quality_reason": cycle_reason,
            "trial_quality": trial_quality,
            "quality_reason": reason,
        }
    )
    return _fill_output_row(base)


def _analyze_slip_cue(
    cue: dict[str, str],
    *,
    event_position: int,
    next_onset_ms: float | None,
    summary: dict[str, Any],
    pinch_rows: list[dict[str, str]],
    pinch_calibration: dict[str, Any],
) -> dict[str, Any]:
    onset = _float_or_none(cue.get("actual_emit_ms") or cue.get("monotonic_ms"))
    base = _base_row(cue, event_position, next_onset_ms, summary)
    base.update(
        {
            "response_source": "pinch",
            "expected_response": "pinch_then_release",
            "detector_version": DETECTOR_VERSION,
        }
    )
    if onset is None or not pinch_rows:
        base.update(
            {
                "trial_quality": "insufficient_pinch_data",
                "quality_reason": "missing_onset_or_pinch_timeseries",
                "response_quality": "insufficient_pinch_data",
                "response_quality_reason": "missing_onset_or_pinch_timeseries",
                "cycle_quality": "not_applicable",
                "cycle_quality_reason": "missing_onset_or_pinch_timeseries",
            }
        )
        return _fill_output_row(base)

    samples = _pinch_closure_samples(pinch_rows)
    reference = _pinch_reference_model(pinch_calibration)
    baseline = [
        item
        for item in samples
        if onset - BASELINE_WINDOW_MS <= item["monotonic_ms"] < onset
    ]
    if len(baseline) < 3:
        base.update(
            {
                "trial_quality": "insufficient_pinch_data",
                "quality_reason": "too_few_baseline_samples",
                "response_quality": "insufficient_pinch_data",
                "response_quality_reason": "too_few_baseline_samples",
                "cycle_quality": "not_applicable",
                "cycle_quality_reason": "too_few_baseline_samples",
            }
        )
        return _fill_output_row(base)
    baseline_values = [item["closure"] for item in baseline]
    baseline_distance_values = [item["pinch_distance"] for item in baseline]
    baseline_closure = median(baseline_values)
    baseline_distance = median(baseline_distance_values)
    baseline_mad = _mad(baseline_values, baseline_closure)
    threshold = max(PINCH_MIN_DELTA, 3.0 * baseline_mad)
    return_tolerance = max(BASELINE_RETURN_MIN_DELTA, 2.0 * baseline_mad)
    end = next_onset_ms if next_onset_ms is not None else onset + 8000.0
    window = [item for item in samples if onset <= item["monotonic_ms"] < end]
    if len(window) < 3:
        base.update(
            {
                "baseline_closure": baseline_closure,
                "baseline_closure_mad": baseline_mad,
                "baseline_stability": baseline_mad,
                "trial_quality": "insufficient_pinch_data",
                "quality_reason": "too_few_response_samples",
                "response_quality": "insufficient_pinch_data",
                "response_quality_reason": "too_few_response_samples",
                "cycle_quality": "not_applicable",
                "cycle_quality_reason": "too_few_response_samples",
            }
        )
        return _fill_output_row(base)
    pinch = _first_stable_closure(
        window,
        condition=lambda value: value >= baseline_closure + threshold,
        stable_ms=STABLE_MS,
    )
    peak = max(window, key=lambda item: item["closure"])
    release = None
    returned = None
    if pinch is not None:
        after_peak = [item for item in window if item["monotonic_ms"] >= peak["monotonic_ms"]]
        release = _first_stable_closure(
            after_peak,
            condition=lambda value: value <= peak["closure"] - threshold,
            stable_ms=STABLE_MS,
        )
        returned = _first_stable_closure(
            after_peak,
            condition=lambda value: value <= baseline_closure + return_tolerance,
            stable_ms=STABLE_MS,
        )
    contact_reference = None
    if pinch is not None and reference.get("available"):
        after_peak = [item for item in window if item["monotonic_ms"] >= peak["monotonic_ms"]]
        contact_reference = _first_stable_pinch_state(
            after_peak,
            reference,
            state="contact",
            stable_ms=STABLE_MS,
        )
    pinch_detected = pinch is not None
    release_detected = release is not None
    response_sequence_complete = (
        pinch_detected
        and (
            contact_reference is not None
            if reference.get("available")
            else release_detected
        )
    )
    if pinch_detected and release_detected and response_sequence_complete:
        response_quality, response_reason = "clean", ""
        cycle_quality, cycle_reason = "complete", ""
        quality, reason = "clean", ""
    elif pinch_detected and release_detected and reference.get("available"):
        response_quality, response_reason = "clean", ""
        cycle_quality, cycle_reason = "incomplete_contact_return", "no_stable_contact_reference_return_before_next_cue"
        quality, reason = "partial_no_contact_return", cycle_reason
    elif baseline_closure >= SATURATED_CLOSURE and not pinch_detected:
        response_quality, response_reason = (
            "already_saturated",
            "baseline_closure_too_high_to_detect_extra_pinch",
        )
        cycle_quality, cycle_reason = "not_applicable", response_reason
        quality, reason = response_quality, response_reason
    elif not pinch_detected:
        response_quality, response_reason = (
            "no_pinch_increase",
            "no_stable_closure_increase_before_next_cue",
        )
        cycle_quality, cycle_reason = "not_applicable", response_reason
        quality, reason = response_quality, response_reason
    else:
        response_quality, response_reason = "clean", ""
        cycle_quality, cycle_reason = "incomplete_release", "no_stable_reopening_before_next_cue"
        quality, reason = "partial_no_release", cycle_reason

    base.update(
        {
            "baseline_closure": baseline_closure,
            "baseline_pinch_distance": baseline_distance,
            "baseline_closure_mad": baseline_mad,
            "baseline_stability": baseline_mad,
            **_pinch_reference_fields(reference, baseline_distance),
            "pre_cue_pinch_state": _pinch_state_for_distance(baseline_distance, reference),
            "post_cue_target_state": "contact",
            "pinch_onset_ms": pinch["monotonic_ms"] if pinch else None,
            "pinch_rt_ms": float(pinch["monotonic_ms"]) - onset if pinch else None,
            "pinch_detected": pinch_detected,
            "pinch_reference_onset_ms": pinch["monotonic_ms"] if pinch else None,
            "peak_closure": peak["closure"],
            "peak_closure_delta": peak["closure"] - baseline_closure,
            "peak_time_ms": peak["monotonic_ms"],
            "release_onset_ms": release["monotonic_ms"] if release else None,
            "release_completion_ms": release["stable_until_ms"] if release else None,
            "release_drop": (
                peak["closure"] - float(release["closure"]) if release else None
            ),
            "release_detected": release_detected,
            "return_to_precue_baseline_ms": returned["monotonic_ms"] if returned else None,
            "return_to_precue_baseline_completion_ms": (
                returned["stable_until_ms"] if returned else None
            ),
            "returned_to_precue_baseline": returned is not None,
            "entered_contact_reference": contact_reference is not None,
            "contact_reference_onset_ms": (
                contact_reference["monotonic_ms"] if contact_reference else None
            ),
            "response_onset_ms": pinch["monotonic_ms"] if pinch else None,
            "response_rt_ms": float(pinch["monotonic_ms"]) - onset if pinch else None,
            "first_response_onset_ms": pinch["monotonic_ms"] if pinch else None,
            "first_response_rt_ms": float(pinch["monotonic_ms"]) - onset if pinch else None,
            "correct_response_onset_ms": pinch["monotonic_ms"] if pinch else None,
            "correct_response_rt_ms": float(pinch["monotonic_ms"]) - onset if pinch else None,
            "first_response": "pinch" if pinch_detected else "",
            "first_response_correct": pinch_detected,
            "was_corrected": False,
            "correction_time_ms": None,
            "eventual_correct": response_sequence_complete,
            "response_sequence_complete": response_sequence_complete,
            "response_end_ms": (
                contact_reference["stable_until_ms"]
                if contact_reference
                else (release["stable_until_ms"] if release else None)
            ),
            "full_cycle_ms": (
                float(
                    contact_reference["stable_until_ms"]
                    if contact_reference
                    else release["stable_until_ms"]
                )
                - onset
                if contact_reference or release
                else None
            ),
            "response_quality": response_quality,
            "response_quality_reason": response_reason,
            "cycle_quality": cycle_quality,
            "cycle_quality_reason": cycle_reason,
            "trial_quality": quality,
            "quality_reason": reason,
        }
    )
    return _fill_output_row(base)


def _empty_event_row(
    cue: dict[str, str],
    *,
    event_position: int,
    next_onset_ms: float | None,
    summary: dict[str, Any],
) -> dict[str, Any]:
    row = _base_row(cue, event_position, next_onset_ms, summary)
    row.update(
        {
            "response_source": "",
            "expected_response": "",
            "response_quality": "not_scored",
            "response_quality_reason": "no_s_r_mapping_defined",
            "cycle_quality": "not_scored",
            "cycle_quality_reason": "no_s_r_mapping_defined",
            "trial_quality": "not_scored",
            "quality_reason": "no_s_r_mapping_defined",
            "detector_version": DETECTOR_VERSION,
        }
    )
    return _fill_output_row(row)


def _first_stable_wrist_action(
    rows: list[dict[str, str]],
    calibration: dict[str, Any],
    *,
    start_ms: float,
    end_ms: float,
    stable_ms: float,
    expected_action: str | None = None,
) -> dict[str, Any] | None:
    labels = {expected_action} if expected_action else WRIST_EVENTS
    return _first_stable_wrist_label(
        rows,
        calibration,
        labels=labels,
        start_ms=start_ms,
        end_ms=end_ms,
        stable_ms=stable_ms,
    )


def _first_stable_wrist_neutral(
    rows: list[dict[str, str]],
    calibration: dict[str, Any],
    *,
    start_ms: float,
    end_ms: float,
    stable_ms: float,
) -> dict[str, Any] | None:
    return _first_stable_wrist_label(
        rows,
        calibration,
        labels={"neutral"},
        start_ms=start_ms,
        end_ms=end_ms,
        stable_ms=stable_ms,
    )


def _first_stable_wrist_label(
    rows: list[dict[str, str]],
    calibration: dict[str, Any],
    *,
    labels: set[str],
    start_ms: float,
    end_ms: float,
    stable_ms: float,
) -> dict[str, Any] | None:
    active_label = ""
    active_start: float | None = None
    active_row: dict[str, str] | None = None
    previous_ms: float | None = None
    previous_row: dict[str, str] | None = None
    for row in rows:
        current_ms = _float_or_none(row.get("monotonic_ms"))
        if current_ms is None or current_ms < start_ms:
            continue
        if current_ms > end_ms:
            break
        label = _offline_wrist_action_label(row, calibration)
        if label in labels:
            if label != active_label:
                active_label = label
                active_start = current_ms
                active_row = row
            previous_ms = current_ms
            previous_row = row
            if active_start is not None and current_ms - active_start >= stable_ms:
                return {
                    "action": label,
                    "monotonic_ms": active_start,
                    "stable_until_ms": current_ms,
                    "row": active_row,
                }
            continue
        active_label = ""
        active_start = None
        active_row = None
        previous_ms = current_ms
        previous_row = row
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
            "row": active_row or previous_row,
        }
    return None


def _next_after_pre_existing_wrist_state(
    rows: list[dict[str, str]],
    calibration: dict[str, Any],
    *,
    start_ms: float,
    end_ms: float,
    pre_existing_action: str,
) -> float:
    if pre_existing_action not in WRIST_EVENTS:
        return start_ms
    for row in rows:
        current_ms = _float_or_none(row.get("monotonic_ms"))
        if current_ms is None or current_ms < start_ms:
            continue
        if current_ms > end_ms:
            break
        if _offline_wrist_action_label(row, calibration) != pre_existing_action:
            return current_ms
    return end_ms


def _up_window_fields(
    rows: list[dict[str, str]],
    *,
    onset_ms: float,
    end_ms: float,
    calibration: dict[str, Any],
    pre_cue_state: str,
) -> dict[str, Any]:
    window = [
        row
        for row in rows
        if (ms := _float_or_none(row.get("monotonic_ms"))) is not None
        and onset_ms <= ms < end_ms
    ]
    up_scores = [
        value
        for row in window
        if (value := _float_or_none(row.get("wrist_up_down_score"))) is not None
    ]
    return {
        "pre_cue_state": pre_cue_state,
        "max_up_score_after_cue": max(up_scores) if up_scores else None,
        "min_down_score_after_cue": min(up_scores) if up_scores else None,
    }


def _up_diagnostic_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = {field: row.get(field, "") for field in UP_DIAGNOSTIC_FIELDS}
    payload["first_stable_direction"] = row.get("first_response", "")
    payload["first_direction_rt_ms"] = row.get("first_response_rt_ms", "")
    payload["eventual_up_detected"] = row.get("eventual_correct", "")
    return payload


def _wrist_excursion_diagnostic_row(
    row: dict[str, Any],
    *,
    wrist_rows: list[dict[str, str]],
    calibration: dict[str, Any],
) -> dict[str, Any]:
    event_name = _text(row.get("event_name")).lower()
    axis = "lr" if event_name in {"left", "right"} else "ud"
    value_field = "wrist_rotation_score" if axis == "lr" else "wrist_up_down_score"
    if axis == "lr":
        first_label = "left"
        second_label = "right"
        first_mean = _float_or_none(calibration.get("left_score_mean"))
        second_mean = _float_or_none(calibration.get("right_score_mean"))
    else:
        first_label = "up"
        second_label = "down"
        first_mean = _float_or_none(calibration.get("up_score_mean"))
        second_mean = _float_or_none(calibration.get("down_score_mean"))
    onset = _float_or_none(row.get("cue_onset_ms"))
    end = _float_or_none(row.get("next_cue_onset_ms"))
    if onset is None:
        return _fill_diagnostic_row(
            _base_diagnostic_row(row, response_source="wrist", analysis_axis=axis)
        )
    if end is None:
        end = onset + 8000.0
    samples = _score_samples(wrist_rows, value_field=value_field)
    diagnostic = _axis_excursion_diagnostic(
        samples,
        onset_ms=onset,
        end_ms=end,
        expected_direction=event_name,
        first_label=first_label,
        first_mean=first_mean,
        second_label=second_label,
        second_mean=second_mean,
    )
    diagnostic.update(
        _base_diagnostic_row(row, response_source="wrist", analysis_axis=axis)
    )
    diagnostic.update(
        {
            "first_stable_direction": row.get("first_response", ""),
            "first_stable_rt_ms": row.get("first_response_rt_ms", ""),
            "stable_matches_first_excursion": (
                _text(row.get("first_response"))
                == _text(diagnostic.get("first_excursion_direction"))
                if _text(row.get("first_response")) and _text(diagnostic.get("first_excursion_direction"))
                else ""
            ),
        }
    )
    return _fill_diagnostic_row(diagnostic)


def _pinch_excursion_diagnostic_row(
    row: dict[str, Any],
    *,
    pinch_rows: list[dict[str, str]],
) -> dict[str, Any]:
    onset = _float_or_none(row.get("cue_onset_ms"))
    end = _float_or_none(row.get("next_cue_onset_ms"))
    event_name = _text(row.get("event_name")).lower()
    expected_direction = "release" if event_name == "release" else "pinch"
    if onset is None:
        return _fill_diagnostic_row(
            _base_diagnostic_row(row, response_source="pinch", analysis_axis="pinch_closure")
        )
    if end is None:
        end = onset + 8000.0
    closure_samples = [
        {"monotonic_ms": sample["monotonic_ms"], "value": sample["closure"]}
        for sample in _pinch_closure_samples(pinch_rows)
    ]
    diagnostic = _axis_excursion_diagnostic(
        closure_samples,
        onset_ms=onset,
        end_ms=end,
        expected_direction=expected_direction,
        first_label="pinch",
        first_mean=1.0,
        second_label="release",
        second_mean=0.0,
        threshold_floor=PINCH_MIN_DELTA,
    )
    diagnostic.update(
        _base_diagnostic_row(row, response_source="pinch", analysis_axis="pinch_closure")
    )
    diagnostic.update(
        {
            "expected_excursion_direction": expected_direction,
            "first_stable_direction": _pinch_response_as_excursion_label(
                row.get("first_response", "")
            ),
            "first_stable_rt_ms": row.get("first_response_rt_ms", ""),
            "stable_matches_first_excursion": (
                _pinch_response_as_excursion_label(row.get("first_response", ""))
                == _text(diagnostic.get("first_excursion_direction"))
                if _pinch_response_as_excursion_label(row.get("first_response", ""))
                and _text(diagnostic.get("first_excursion_direction"))
                else ""
            ),
        }
    )
    return _fill_diagnostic_row(diagnostic)


def _pinch_response_as_excursion_label(value: Any) -> str:
    text = _text(value).lower()
    if text == "closing":
        return "pinch"
    if text == "opening":
        return "release"
    return text


def _base_diagnostic_row(
    row: dict[str, Any],
    *,
    response_source: str,
    analysis_axis: str,
) -> dict[str, Any]:
    return {
        "session_id": row.get("session_id", ""),
        "participant_id": row.get("participant_id", ""),
        "condition": row.get("condition", ""),
        "task_type": row.get("task_type", ""),
        "nback_enabled": row.get("nback_enabled", ""),
        "plan_id": row.get("plan_id", ""),
        "event_name": row.get("event_name", ""),
        "event_position": row.get("event_position", ""),
        "emit_trial_number": row.get("emit_trial_number", ""),
        "cue_onset_ms": row.get("cue_onset_ms", ""),
        "next_cue_onset_ms": row.get("next_cue_onset_ms", ""),
        "response_source": response_source,
        "analysis_axis": analysis_axis,
        "expected_excursion_direction": row.get("event_name", ""),
        "response_quality": row.get("response_quality", ""),
        "cycle_quality": row.get("cycle_quality", ""),
        "quality_reason": row.get("quality_reason", ""),
        "detector_version": DETECTOR_VERSION,
    }


def _axis_excursion_diagnostic(
    samples: list[dict[str, float]],
    *,
    onset_ms: float,
    end_ms: float,
    expected_direction: str,
    first_label: str,
    first_mean: float | None,
    second_label: str,
    second_mean: float | None,
    threshold_floor: float = 0.03,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "expected_excursion_direction": expected_direction,
    }
    if first_mean is None or second_mean is None:
        return result
    baseline_values = [
        item["value"]
        for item in samples
        if onset_ms - BASELINE_WINDOW_MS <= item["monotonic_ms"] < onset_ms
    ]
    if baseline_values:
        baseline_center = median(baseline_values)
        baseline_mad = _mad(baseline_values, baseline_center)
    else:
        pre_sample = _last_numeric_sample_before(samples, onset_ms)
        baseline_center = pre_sample["value"] if pre_sample else 0.0
        baseline_mad = 0.0
    threshold = max(
        threshold_floor,
        baseline_mad * 4.0,
        min(abs(first_mean - baseline_center), abs(second_mean - baseline_center)) * 0.20,
    )
    pre_sample = _last_numeric_sample_before(samples, onset_ms)
    onset_sample = _nearest_numeric_sample(samples, onset_ms)
    result.update(
        {
            "baseline_center": baseline_center,
            "baseline_mad": baseline_mad,
            "excursion_threshold": threshold,
            "pre_cue_value": pre_sample["value"] if pre_sample else None,
            "value_at_onset": onset_sample["value"] if onset_sample else None,
        }
    )
    first = _first_stable_excursion(
        samples,
        start_ms=onset_ms,
        end_ms=end_ms,
        baseline_center=baseline_center,
        threshold=threshold,
        first_label=first_label,
        first_mean=first_mean,
        second_label=second_label,
        second_mean=second_mean,
    )
    expected = _first_stable_excursion(
        samples,
        start_ms=onset_ms,
        end_ms=end_ms,
        baseline_center=baseline_center,
        threshold=threshold,
        first_label=first_label,
        first_mean=first_mean,
        second_label=second_label,
        second_mean=second_mean,
        expected_label=expected_direction,
    )
    if expected is not None:
        result.update(
            {
                "expected_excursion_detected": True,
                "expected_excursion_onset_ms": expected["monotonic_ms"],
                "expected_excursion_rt_ms": expected["monotonic_ms"] - onset_ms,
            }
        )
    else:
        result["expected_excursion_detected"] = False
    if first is None:
        return result
    opposite_label = second_label if first["direction"] == first_label else first_label
    reversal = _first_stable_excursion(
        samples,
        start_ms=float(first["stable_until_ms"]),
        end_ms=end_ms,
        baseline_center=baseline_center,
        threshold=threshold,
        first_label=first_label,
        first_mean=first_mean,
        second_label=second_label,
        second_mean=second_mean,
        expected_label=opposite_label,
    )
    peak_end = float(reversal["monotonic_ms"]) if reversal else end_ms
    peak = _directional_peak(
        samples,
        start_ms=float(first["monotonic_ms"]),
        end_ms=peak_end,
        baseline_center=baseline_center,
        label=first["direction"],
        label_mean=first_mean if first["direction"] == first_label else second_mean,
    )
    result.update(
        {
            "first_excursion_direction": first["direction"],
            "first_excursion_onset_ms": first["monotonic_ms"],
            "first_excursion_rt_ms": first["monotonic_ms"] - onset_ms,
            "first_excursion_peak_value": peak.get("value"),
            "first_excursion_peak_delta": peak.get("delta"),
            "first_excursion_peak_ms": peak.get("monotonic_ms"),
            "first_excursion_duration_ms": (
                float(reversal["monotonic_ms"]) - float(first["monotonic_ms"])
                if reversal
                else None
            ),
            "reversal_detected": reversal is not None,
            "reversal_direction": opposite_label if reversal else "",
            "reversal_onset_ms": reversal["monotonic_ms"] if reversal else None,
            "reversal_rt_ms": reversal["monotonic_ms"] - onset_ms if reversal else None,
        }
    )
    if reversal is not None:
        overshoot = _directional_peak(
            samples,
            start_ms=float(reversal["monotonic_ms"]),
            end_ms=end_ms,
            baseline_center=baseline_center,
            label=opposite_label,
            label_mean=first_mean if opposite_label == first_label else second_mean,
        )
        result.update(
            {
                "overshoot_peak_value": overshoot.get("value"),
                "overshoot_peak_delta": overshoot.get("delta"),
                "overshoot_peak_ms": overshoot.get("monotonic_ms"),
            }
        )
    return result


def _first_stable_excursion(
    samples: list[dict[str, float]],
    *,
    start_ms: float,
    end_ms: float,
    baseline_center: float,
    threshold: float,
    first_label: str,
    first_mean: float,
    second_label: str,
    second_mean: float,
    expected_label: str | None = None,
) -> dict[str, Any] | None:
    active_label = ""
    active_start: dict[str, float] | None = None
    previous: dict[str, float] | None = None
    labels = {expected_label} if expected_label else {first_label, second_label}
    for sample in samples:
        current_ms = sample["monotonic_ms"]
        if current_ms < start_ms:
            continue
        if current_ms > end_ms:
            break
        label = _axis_excursion_label(
            sample["value"],
            baseline_center=baseline_center,
            threshold=threshold,
            first_label=first_label,
            first_mean=first_mean,
            second_label=second_label,
            second_mean=second_mean,
        )
        if label in labels:
            if label != active_label:
                active_label = label
                active_start = sample
            previous = sample
            if active_start is not None and current_ms - active_start["monotonic_ms"] >= EXCURSION_STABLE_MS:
                return {
                    "direction": label,
                    "monotonic_ms": active_start["monotonic_ms"],
                    "stable_until_ms": current_ms,
                    "value": active_start["value"],
                }
            continue
        active_label = ""
        active_start = None
        previous = sample
    if (
        active_label in labels
        and active_start is not None
        and previous is not None
        and previous["monotonic_ms"] - active_start["monotonic_ms"] >= EXCURSION_STABLE_MS
    ):
        return {
            "direction": active_label,
            "monotonic_ms": active_start["monotonic_ms"],
            "stable_until_ms": previous["monotonic_ms"],
            "value": active_start["value"],
        }
    return None


def _axis_excursion_label(
    value: float,
    *,
    baseline_center: float,
    threshold: float,
    first_label: str,
    first_mean: float,
    second_label: str,
    second_mean: float,
) -> str:
    delta = value - baseline_center
    if abs(delta) < threshold:
        return ""
    first_delta = first_mean - baseline_center
    second_delta = second_mean - baseline_center
    first_projection = _direction_projection(delta, first_delta)
    second_projection = _direction_projection(delta, second_delta)
    if first_projection <= 0.0 and second_projection <= 0.0:
        return ""
    return first_label if first_projection >= second_projection else second_label


def _direction_projection(delta: float, direction_delta: float) -> float:
    if abs(direction_delta) < 1e-9:
        return -math.inf
    return delta / direction_delta


def _directional_peak(
    samples: list[dict[str, float]],
    *,
    start_ms: float,
    end_ms: float,
    baseline_center: float,
    label: str,
    label_mean: float,
) -> dict[str, float | None]:
    direction_delta = label_mean - baseline_center
    best: dict[str, float] | None = None
    best_projection = -math.inf
    for sample in samples:
        current_ms = sample["monotonic_ms"]
        if current_ms < start_ms:
            continue
        if current_ms > end_ms:
            break
        delta = sample["value"] - baseline_center
        projection = _direction_projection(delta, direction_delta)
        if projection > best_projection:
            best_projection = projection
            best = sample
    if best is None:
        return {"value": None, "delta": None, "monotonic_ms": None}
    return {
        "value": best["value"],
        "delta": abs(best["value"] - baseline_center),
        "monotonic_ms": best["monotonic_ms"],
    }


def _score_samples(rows: list[dict[str, str]], *, value_field: str) -> list[dict[str, float]]:
    samples: list[dict[str, float]] = []
    for row in rows:
        ms = _float_or_none(row.get("monotonic_ms"))
        value = _float_or_none(row.get(value_field))
        if ms is None or value is None:
            continue
        samples.append({"monotonic_ms": ms, "value": value})
    return samples


def _nearest_numeric_sample(samples: list[dict[str, float]], target_ms: float) -> dict[str, float] | None:
    best: dict[str, float] | None = None
    best_delta = math.inf
    for sample in samples:
        delta = abs(sample["monotonic_ms"] - target_ms)
        if delta < best_delta:
            best = sample
            best_delta = delta
    return best


def _last_numeric_sample_before(samples: list[dict[str, float]], target_ms: float) -> dict[str, float] | None:
    best: dict[str, float] | None = None
    best_ms = -math.inf
    for sample in samples:
        current_ms = sample["monotonic_ms"]
        if current_ms >= target_ms:
            continue
        if current_ms > best_ms:
            best = sample
            best_ms = current_ms
    return best


def _offline_wrist_action_label(row: dict[str, str], calibration: dict[str, Any]) -> str:
    lr = _offline_lr_label(row, calibration)
    ud = _offline_ud_label(row, calibration)
    if lr in {"left", "right"}:
        return lr
    if ud in {"up", "down"}:
        return ud
    if lr == "neutral" and ud == "neutral":
        return "neutral"
    return "unknown"


def _offline_lr_label(row: dict[str, str] | None, calibration: dict[str, Any]) -> str:
    if row is None:
        return "unknown"
    return _neutral_centered_label(
        _float_or_none(row.get("wrist_rotation_score")),
        first_mean=_float_or_none(calibration.get("left_score_mean")),
        first_label="left",
        second_mean=_float_or_none(calibration.get("right_score_mean")),
        second_label="right",
    )


def _offline_ud_label(row: dict[str, str] | None, calibration: dict[str, Any]) -> str:
    if row is None:
        return "unknown"
    return _neutral_centered_label(
        _float_or_none(row.get("wrist_up_down_score")),
        first_mean=_float_or_none(calibration.get("up_score_mean")),
        first_label="up",
        second_mean=_float_or_none(calibration.get("down_score_mean")),
        second_label="down",
    )


def _neutral_centered_label(
    score: float | None,
    *,
    first_mean: float | None,
    first_label: str,
    second_mean: float | None,
    second_label: str,
) -> str:
    if score is None or first_mean is None or second_mean is None:
        return "unknown"
    if first_mean * second_mean < 0.0:
        lower = min(first_mean / 2.0, second_mean / 2.0)
        upper = max(first_mean / 2.0, second_mean / 2.0)
        if lower <= score <= upper:
            return "neutral"
        return first_label if abs(score - first_mean) <= abs(score - second_mean) else second_label
    distances = [
        (abs(score), "neutral"),
        (abs(score - first_mean), first_label),
        (abs(score - second_mean), second_label),
    ]
    return min(distances, key=lambda item: item[0])[1]


def _centered_sanity(calibration: dict[str, Any], *, axis: str) -> bool:
    if axis == "lr":
        first = _float_or_none(calibration.get("left_score_mean"))
        second = _float_or_none(calibration.get("right_score_mean"))
    else:
        first = _float_or_none(calibration.get("up_score_mean"))
        second = _float_or_none(calibration.get("down_score_mean"))
    return first is not None and second is not None and first * second < 0.0


def _old_region(calibration: dict[str, Any], *, axis: str) -> dict[str, Any]:
    if axis == "lr":
        existing = calibration.get("lr_old_neutral_region")
        threshold = _float_or_none(calibration.get("threshold"))
        first = _float_or_none(calibration.get("left_score_mean"))
        second = _float_or_none(calibration.get("right_score_mean"))
    else:
        existing = calibration.get("up_down_old_neutral_region")
        threshold = _float_or_none(calibration.get("up_down_threshold"))
        first = _float_or_none(calibration.get("up_score_mean"))
        second = _float_or_none(calibration.get("down_score_mean"))
    if isinstance(existing, dict) and "lower" in existing:
        return dict(existing)
    if threshold is None or first is None or second is None:
        return {"lower": None, "upper": None, "zero_in_region": None}
    margin = abs(first - second) * float(calibration.get("classification_margin", 0.15))
    lower = threshold - margin
    upper = threshold + margin
    return {"lower": lower, "upper": upper, "zero_in_region": lower <= 0.0 <= upper}


def _first_stable_closure(
    rows: list[dict[str, float]],
    *,
    condition: Callable[[float], bool],
    stable_ms: float,
) -> dict[str, float] | None:
    active_start: dict[str, float] | None = None
    previous: dict[str, float] | None = None
    for row in rows:
        if condition(float(row["closure"])):
            if active_start is None:
                active_start = row
            previous = row
            if row["monotonic_ms"] - active_start["monotonic_ms"] >= stable_ms:
                return {
                    "monotonic_ms": active_start["monotonic_ms"],
                    "stable_until_ms": row["monotonic_ms"],
                    "closure": row["closure"],
                }
            continue
        active_start = None
        previous = row
    if (
        active_start is not None
        and previous is not None
        and previous["monotonic_ms"] - active_start["monotonic_ms"] >= stable_ms
    ):
        return {
            "monotonic_ms": active_start["monotonic_ms"],
            "stable_until_ms": previous["monotonic_ms"],
            "closure": previous["closure"],
        }
    return None


def _pinch_closure_samples(rows: list[dict[str, str]]) -> list[dict[str, float]]:
    samples: list[dict[str, float]] = []
    for row in rows:
        ms = _float_or_none(row.get("monotonic_ms"))
        distance = _float_or_none(row.get("pinch_distance"))
        min_distance = _float_or_none(row.get("min_distance"))
        max_distance = _float_or_none(row.get("max_distance"))
        if (
            ms is None
            or distance is None
            or min_distance is None
            or max_distance is None
            or max_distance <= min_distance
        ):
            continue
        closure = (max_distance - distance) / (max_distance - min_distance)
        samples.append({"monotonic_ms": ms, "closure": closure, "pinch_distance": distance})
    return samples


def _pinch_reference_model(calibration: dict[str, Any]) -> dict[str, Any]:
    open_distance = _float_or_none(calibration.get("open_distance_median"))
    contact_distance = _float_or_none(calibration.get("contact_distance_median"))
    pinch_distance = _float_or_none(calibration.get("pinch_distance_median"))
    open_contact_boundary = _float_or_none(calibration.get("open_contact_boundary"))
    contact_pinch_boundary = _float_or_none(calibration.get("contact_pinch_boundary"))
    quality = _bool_value(calibration.get("pinch_reference_quality_passed"))
    reason = _text(calibration.get("pinch_reference_quality_reason"))
    contact_available = contact_distance is not None
    if (
        open_contact_boundary is None
        and open_distance is not None
        and contact_distance is not None
    ):
        open_contact_boundary = (open_distance + contact_distance) / 2.0
    if (
        contact_pinch_boundary is None
        and contact_distance is not None
        and pinch_distance is not None
    ):
        contact_pinch_boundary = (contact_distance + pinch_distance) / 2.0
    available = (
        quality is True
        and open_distance is not None
        and contact_distance is not None
        and pinch_distance is not None
        and open_contact_boundary is not None
        and contact_pinch_boundary is not None
    )
    return {
        "available": available,
        "quality_passed": quality,
        "quality_reason": reason,
        "contact_reference_available": contact_available,
        "open_distance": open_distance,
        "contact_distance": contact_distance,
        "pinch_distance": pinch_distance,
        "open_mad": _float_or_none(calibration.get("open_distance_mad")),
        "contact_mad": _float_or_none(calibration.get("contact_distance_mad")),
        "pinch_mad": _float_or_none(calibration.get("pinch_distance_mad")),
        "open_contact_boundary": open_contact_boundary,
        "contact_pinch_boundary": contact_pinch_boundary,
    }


def _pinch_reference_fields(
    reference: dict[str, Any],
    distance: float | None,
) -> dict[str, Any]:
    return {
        "pinch_reference_quality_passed": reference.get("quality_passed"),
        "pinch_reference_quality_reason": reference.get("quality_reason", ""),
        "contact_reference_available": reference.get("contact_reference_available", False),
        "distance_to_open": _reference_distance(distance, reference.get("open_distance")),
        "distance_to_contact": _reference_distance(distance, reference.get("contact_distance")),
        "distance_to_pinch": _reference_distance(distance, reference.get("pinch_distance")),
        "baseline_reference_position": _pinch_reference_position(distance, reference),
    }


def _reference_distance(value: float | None, reference_value: Any) -> float | None:
    reference_float = _float_or_none(reference_value)
    if value is None or reference_float is None:
        return None
    return abs(float(value) - reference_float)


def _pinch_reference_position(
    distance: float | None,
    reference: dict[str, Any],
) -> float | None:
    if distance is None:
        return None
    open_distance = _float_or_none(reference.get("open_distance"))
    contact_distance = _float_or_none(reference.get("contact_distance"))
    pinch_distance = _float_or_none(reference.get("pinch_distance"))
    if open_distance is None or contact_distance is None or pinch_distance is None:
        return None
    if not (open_distance > contact_distance > pinch_distance):
        return None
    value = float(distance)
    if value >= contact_distance:
        return (open_distance - value) / (open_distance - contact_distance)
    return 1.0 + (contact_distance - value) / (contact_distance - pinch_distance)


def _pinch_state_for_distance(
    distance: float | None,
    reference: dict[str, Any],
) -> str:
    if distance is None or not reference.get("available"):
        return ""
    open_contact_boundary = _float_or_none(reference.get("open_contact_boundary"))
    contact_pinch_boundary = _float_or_none(reference.get("contact_pinch_boundary"))
    if open_contact_boundary is None or contact_pinch_boundary is None:
        return ""
    value = float(distance)
    if value >= open_contact_boundary:
        return "open"
    if value <= contact_pinch_boundary:
        return "pinch"
    return "contact"


def _first_stable_pinch_direction(
    rows: list[dict[str, float]],
    *,
    baseline_distance: float,
    threshold: float,
    stable_ms: float,
    expected_direction: str | None = None,
) -> dict[str, Any] | None:
    labels = {expected_direction} if expected_direction else {"opening", "closing"}
    active_label = ""
    active_start: dict[str, float] | None = None
    previous: dict[str, float] | None = None
    for row in rows:
        value = float(row["pinch_distance"])
        if value <= baseline_distance - threshold:
            label = "closing"
        elif value >= baseline_distance + threshold:
            label = "opening"
        else:
            label = ""
        if label in labels:
            if label != active_label:
                active_label = label
                active_start = row
            previous = row
            if active_start is not None and row["monotonic_ms"] - active_start["monotonic_ms"] >= stable_ms:
                return {
                    "direction": label,
                    "monotonic_ms": active_start["monotonic_ms"],
                    "stable_until_ms": row["monotonic_ms"],
                    "pinch_distance": active_start["pinch_distance"],
                }
            continue
        active_label = ""
        active_start = None
        previous = row
    if (
        active_label in labels
        and active_start is not None
        and previous is not None
        and previous["monotonic_ms"] - active_start["monotonic_ms"] >= stable_ms
    ):
        return {
            "direction": active_label,
            "monotonic_ms": active_start["monotonic_ms"],
            "stable_until_ms": previous["monotonic_ms"],
            "pinch_distance": active_start["pinch_distance"],
        }
    return None


def _first_stable_pinch_state(
    rows: list[dict[str, float]],
    reference: dict[str, Any],
    *,
    state: str,
    stable_ms: float,
) -> dict[str, Any] | None:
    active_start: dict[str, float] | None = None
    previous: dict[str, float] | None = None
    for row in rows:
        if _pinch_state_for_distance(row["pinch_distance"], reference) == state:
            if active_start is None:
                active_start = row
            previous = row
            if row["monotonic_ms"] - active_start["monotonic_ms"] >= stable_ms:
                return {
                    "state": state,
                    "monotonic_ms": active_start["monotonic_ms"],
                    "stable_until_ms": row["monotonic_ms"],
                    "pinch_distance": active_start["pinch_distance"],
                }
            continue
        active_start = None
        previous = row
    if (
        active_start is not None
        and previous is not None
        and previous["monotonic_ms"] - active_start["monotonic_ms"] >= stable_ms
    ):
        return {
            "state": state,
            "monotonic_ms": active_start["monotonic_ms"],
            "stable_until_ms": previous["monotonic_ms"],
            "pinch_distance": active_start["pinch_distance"],
        }
    return None


def _semantic_haptic_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result = []
    for row in rows:
        if _text(row.get("source_event_name")):
            continue
        if _float_or_none(row.get("actual_emit_ms") or row.get("monotonic_ms")) is None:
            continue
        result.append(row)
    return result


def _is_analyzable_session(summary: dict[str, Any], semantic_haptics: list[dict[str, str]]) -> bool:
    plan_id = _text(summary.get("haptic_plan_id"))
    return (
        (plan_id.startswith("dual-") or plan_id.startswith("only-matrix-"))
        and len(semantic_haptics) >= 7
    )


def _session_dirs(root: Path) -> list[Path]:
    if (root / "summary.json").exists():
        return [root]
    return sorted(path for path in root.iterdir() if path.is_dir())


def _next_semantic_onset(rows: list[dict[str, str]], index: int) -> float | None:
    if index + 1 >= len(rows):
        return None
    return _float_or_none(rows[index + 1].get("actual_emit_ms") or rows[index + 1].get("monotonic_ms"))


def _base_row(
    cue: dict[str, str],
    event_position: int,
    next_onset_ms: float | None,
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "session_id": summary.get("session_id", cue.get("session_id", "")),
        "participant_id": summary.get("participant_id", ""),
        "condition": _condition_from_plan(_text(summary.get("haptic_plan_id"))),
        "task_type": _text(summary.get("task_type")) or "dual",
        "nback_enabled": summary.get("nback_enabled", True),
        "plan_id": summary.get("haptic_plan_id", ""),
        "event_name": _text(cue.get("event_name")).lower(),
        "event_position": event_position,
        "emit_trial_number": cue.get("emit_trial_number", ""),
        "cue_onset_ms": _float_or_none(cue.get("actual_emit_ms") or cue.get("monotonic_ms")),
        "next_cue_onset_ms": next_onset_ms,
    }


def _condition_from_plan(plan_id: str) -> str:
    if plan_id.startswith("dual-"):
        return "dual"
    if plan_id.startswith("only-matrix-"):
        return "matrix-only"
    if plan_id.startswith("only-motor-"):
        return "motor-only"
    return ""


def _nearest_row(rows: list[dict[str, str]], target_ms: float) -> dict[str, str] | None:
    best: dict[str, str] | None = None
    best_delta = math.inf
    for row in rows:
        ms = _float_or_none(row.get("monotonic_ms"))
        if ms is None:
            continue
        delta = abs(ms - target_ms)
        if delta < best_delta:
            best = row
            best_delta = delta
    return best


def _last_row_before(rows: list[dict[str, str]], target_ms: float) -> dict[str, str] | None:
    best: dict[str, str] | None = None
    best_ms = -math.inf
    for row in rows:
        ms = _float_or_none(row.get("monotonic_ms"))
        if ms is None or ms >= target_ms:
            continue
        if ms > best_ms:
            best = row
            best_ms = ms
    return best


def _mad(values: list[float], center: float) -> float:
    if not values:
        return 0.0
    return median([abs(item - center) for item in values])


def _append_reason(reason: str, addition: str) -> str:
    return f"{reason};{addition}" if reason else addition


def _wrist_audit_row(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field, "") for field in WRIST_AUDIT_FIELDS}


def _fill_output_row(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field, "") for field in OUTPUT_FIELDS}


def _fill_diagnostic_row(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field, "") for field in CUE_DIAGNOSTIC_FIELDS}


def _summary_payload(
    cue_rows: list[dict[str, Any]],
    wrist_rows: list[dict[str, Any]],
    up_rows: list[dict[str, Any]],
    diagnostic_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    by_condition = Counter(_text(row.get("condition")) for row in cue_rows)
    by_task_type = Counter(_text(row.get("task_type")) for row in cue_rows)
    by_quality = Counter(_text(row.get("trial_quality")) for row in cue_rows)
    by_response_quality = Counter(_text(row.get("response_quality")) for row in cue_rows)
    by_cycle_quality = Counter(_text(row.get("cycle_quality")) for row in cue_rows)
    by_event_quality = Counter(
        f"{row.get('event_name')}:{row.get('trial_quality')}" for row in cue_rows
    )
    by_first_excursion = Counter(
        f"{row.get('event_name')}:{row.get('first_excursion_direction') or 'none'}"
        for row in diagnostic_rows
    )
    gate_false = [
        row
        for row in wrist_rows
        if _text(row.get("online_gate_passed")).lower() == "false"
    ]
    return {
        "detector_version": DETECTOR_VERSION,
        "cue_count": len(cue_rows),
        "wrist_audit_count": len(wrist_rows),
        "up_diagnostic_count": len(up_rows),
        "cue_response_diagnostic_count": len(diagnostic_rows),
        "first_excursion_counts": dict(by_first_excursion),
        "stable_first_excursion_mismatch_count": sum(
            1
            for row in diagnostic_rows
            if _bool_value(row.get("stable_matches_first_excursion")) is False
        ),
        "participant_id_missing_count": sum(
            1 for row in cue_rows if not _text(row.get("participant_id"))
        ),
        "condition_counts": dict(by_condition),
        "task_type_counts": dict(by_task_type),
        "quality_counts": dict(by_quality),
        "response_quality_counts": dict(by_response_quality),
        "cycle_quality_counts": dict(by_cycle_quality),
        "event_quality_counts": dict(by_event_quality),
        "online_wrist_gate_false_count": len(gate_false),
        "online_wrist_gate_false_offline_neutral_count": sum(
            1
            for row in gate_false
            if _bool_value(row.get("offline_neutral_centered_gate_passed")) is True
        ),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
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
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _bool_value(value: Any) -> bool | None:
    text = _text(value).lower()
    if text == "true":
        return True
    if text == "false":
        return False
    if isinstance(value, bool):
        return value
    return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze unified tactile cue responses.")
    parser.add_argument("root_dir", help="A session directory or a directory containing sessions.")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    metrics, wrist, up, summary = analyze_root(args.root_dir, output_dir=args.output_dir)
    diagnostics = metrics.parent / "cue_response_diagnostics.csv"
    print(f"Wrote {metrics}")
    print(f"Wrote {wrist}")
    print(f"Wrote {up}")
    print(f"Wrote {diagnostics}")
    print(f"Wrote {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
