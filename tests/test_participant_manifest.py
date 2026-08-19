from __future__ import annotations

import json
from pathlib import Path

import yaml

from run_pinch_haptic_1back import OperatorAbort
from run_participant_manifest import (
    load_participant_manifest,
    prepare_session_config,
    run_participant_manifest,
    validate_participant_manifest,
)


def test_manifest_validate_only_prepares_session_configs(tmp_path) -> None:
    motor_config = _write_dualtask_config(tmp_path / "only-motor.yaml", feedback="motor_only")
    matrix_config = _write_dualtask_config(tmp_path / "only-matrix.yaml", feedback="matrix_only")
    motor_plan = _write_plan(tmp_path / "motor-plan.yaml", plan_id="motor_plan_1", modality="vibration")
    matrix_plan = _write_plan(tmp_path / "matrix-plan.yaml", plan_id="matrix_plan_1", modality="matrix")
    manifest_path = _write_manifest(
        tmp_path / "manifest.yaml",
        tmp_path=tmp_path,
        sessions=[
            {
                "session_label": "motor_single_01",
                "order": 1,
                "task_type": "single",
                "feedback_type": "motor_only",
                "config": str(motor_config),
                "haptic_plan_config": str(motor_plan),
                "plan_id": "motor_plan_1",
            },
            {
                "session_label": "matrix_dual_01",
                "order": 2,
                "task_type": "dual",
                "feedback_type": "matrix_only",
                "config": str(matrix_config),
                "haptic_plan_config": str(matrix_plan),
                "plan_id": "matrix_plan_1",
            },
        ],
    )

    run_dir = run_participant_manifest(manifest_path, validate_only=True)
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))

    assert summary["validate_only"] is True
    assert summary["run_seed"] == 12345
    assert summary["prepared_session_count"] == 2
    assert summary["sessions"][0]["session_seed"] != summary["sessions"][1]["session_seed"]
    prepared_config = Path(summary["sessions"][0]["prepared_config"])
    payload = yaml.safe_load(prepared_config.read_text(encoding="utf-8"))
    assert payload["session"]["participant_id"] == "P001"
    assert payload["session"]["task_type"] == "single"
    assert payload["session"]["haptic_plan_config"] == str(motor_plan)
    assert payload["calibration_reuse"]["calibration_id"] == "P001_exp2_cal_v01"


def test_manifest_writes_cue_dispatch_mode_to_prepared_config(tmp_path) -> None:
    config = _write_dualtask_config(tmp_path / "combined.yaml", feedback="combined")
    plan = _write_plan(tmp_path / "combined-plan.yaml", plan_id="combined_plan_1", modality="vibration")
    manifest_path = _write_manifest(
        tmp_path / "manifest.yaml",
        tmp_path=tmp_path,
        sessions=[
            {
                "session_label": "combined_single_01",
                "order": 1,
                "task_type": "single",
                "feedback_type": "combined",
                "cue_dispatch_mode": "timed_grouped",
                "config": str(config),
                "haptic_plan_config": str(plan),
                "plan_id": "combined_plan_1",
            },
        ],
    )

    run_dir = run_participant_manifest(manifest_path, validate_only=True)
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    prepared_config = Path(summary["sessions"][0]["prepared_config"])
    payload = yaml.safe_load(prepared_config.read_text(encoding="utf-8"))

    assert summary["sessions"][0]["cue_dispatch_mode"] == "timed_grouped"
    assert payload["session"]["cue_dispatch_mode"] == "timed_grouped"


def test_manifest_allows_no_zone_plan_only_for_timed_grouped(tmp_path) -> None:
    config = _write_dualtask_config(tmp_path / "combined.yaml", feedback="combined")
    no_zone_plan = _write_plan(
        tmp_path / "combined-nozone.yaml",
        plan_id="combined_nozone_1",
        modality="vibration",
    )
    payload = yaml.safe_load(no_zone_plan.read_text(encoding="utf-8"))
    for event in payload["events"]:
        event.pop("trigger_zone", None)
    payload.pop("zones")
    no_zone_plan.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    timed_manifest = load_participant_manifest(
        _write_manifest(
            tmp_path / "timed_manifest.yaml",
            tmp_path=tmp_path,
            sessions=[
                {
                    "session_label": "combined_timed",
                    "order": 1,
                    "task_type": "single",
                    "feedback_type": "combined",
                    "cue_dispatch_mode": "timed_grouped",
                    "config": str(config),
                    "haptic_plan_config": str(no_zone_plan),
                    "plan_id": "combined_nozone_1",
                }
            ],
        )
    )
    zone_manifest = load_participant_manifest(
        _write_manifest(
            tmp_path / "zone_manifest.yaml",
            tmp_path=tmp_path,
            sessions=[
                {
                    "session_label": "combined_zone",
                    "order": 1,
                    "task_type": "single",
                    "feedback_type": "combined",
                    "config": str(config),
                    "haptic_plan_config": str(no_zone_plan),
                    "plan_id": "combined_nozone_1",
                }
            ],
        )
    )

    assert validate_participant_manifest(timed_manifest).passed is True
    zone_result = validate_participant_manifest(zone_manifest)
    assert zone_result.passed is False
    assert "zone_sequential requires trigger_zone" in zone_result.errors[0]


def test_manifest_validation_rejects_feedback_config_mismatch(tmp_path) -> None:
    config = _write_dualtask_config(tmp_path / "only-motor.yaml", feedback="motor_only")
    plan = _write_plan(tmp_path / "matrix-plan.yaml", plan_id="matrix_plan_1", modality="matrix")
    manifest = load_participant_manifest(
        _write_manifest(
            tmp_path / "manifest.yaml",
            tmp_path=tmp_path,
            sessions=[
                {
                    "session_label": "bad_matrix",
                    "order": 1,
                    "task_type": "single",
                    "feedback_type": "matrix_only",
                    "config": str(config),
                    "haptic_plan_config": str(plan),
                    "plan_id": "matrix_plan_1",
                }
            ],
        )
    )

    result = validate_participant_manifest(manifest)

    assert result.passed is False
    assert "feedback_type matrix_only does not match" in result.errors[0]


def test_manifest_runner_updates_calibration_path_from_session_summary(tmp_path) -> None:
    config = _write_dualtask_config(tmp_path / "only-motor.yaml", feedback="motor_only")
    plan = _write_plan(tmp_path / "motor-plan.yaml", plan_id="motor_plan_1", modality="vibration")
    manifest_path = _write_manifest(
        tmp_path / "manifest.yaml",
        tmp_path=tmp_path,
        sessions=[
            {
                "session_label": "motor_single_01",
                "order": 1,
                "task_type": "single",
                "feedback_type": "motor_only",
                "config": str(config),
                "haptic_plan_config": str(plan),
                "plan_id": "motor_plan_1",
            },
            {
                "session_label": "motor_single_02",
                "order": 2,
                "task_type": "single",
                "feedback_type": "motor_only",
                "config": str(config),
                "haptic_plan_config": str(plan),
                "plan_id": "motor_plan_1",
            },
        ],
    )
    calls: list[Path] = []

    def fake_runner(config_path: str | Path) -> Path:
        calls.append(Path(config_path))
        output_dir = tmp_path / f"session_{len(calls)}"
        output_dir.mkdir()
        summary = {
            "calibration_id": f"P001_exp2_cal_v0{len(calls)}",
            "calibration_loaded_from_bundle": len(calls) > 1,
            "calibration_saved_path": (
                str(tmp_path / "calibrations" / "P001_exp2_cal_v02.json")
                if len(calls) == 1
                else ""
            ),
        }
        (output_dir / "summary.json").write_text(
            json.dumps(summary),
            encoding="utf-8",
        )
        return output_dir

    run_dir = run_participant_manifest(manifest_path, runner_fn=fake_runner)
    run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    second_config = yaml.safe_load(calls[1].read_text(encoding="utf-8"))

    assert run_summary["completed_session_count"] == 2
    assert run_summary["active_calibration_path"].endswith("P001_exp2_cal_v02.json")
    assert second_config["calibration_reuse"]["calibration_in"].endswith(
        "P001_exp2_cal_v02.json"
    )


def test_manifest_runner_can_start_from_order_with_calibration_override(tmp_path) -> None:
    config = _write_dualtask_config(tmp_path / "only-motor.yaml", feedback="motor_only")
    plan = _write_plan(tmp_path / "motor-plan.yaml", plan_id="motor_plan_1", modality="vibration")
    resume_cal = tmp_path / "calibrations" / "resume_cal.json"
    manifest_path = _write_manifest(
        tmp_path / "manifest.yaml",
        tmp_path=tmp_path,
        sessions=[
            {
                "session_label": "motor_single_01",
                "order": 1,
                "task_type": "single",
                "feedback_type": "motor_only",
                "config": str(config),
                "haptic_plan_config": str(plan),
                "plan_id": "motor_plan_1",
            },
            {
                "session_label": "motor_single_02",
                "order": 2,
                "task_type": "single",
                "feedback_type": "motor_only",
                "config": str(config),
                "haptic_plan_config": str(plan),
                "plan_id": "motor_plan_1",
            },
        ],
    )
    calls: list[Path] = []

    def fake_runner(config_path: str | Path) -> Path:
        calls.append(Path(config_path))
        output_dir = tmp_path / f"resume_session_{len(calls)}"
        output_dir.mkdir()
        (output_dir / "summary.json").write_text("{}", encoding="utf-8")
        return output_dir

    run_dir = run_participant_manifest(
        manifest_path,
        start_order=2,
        calibration_in=resume_cal,
        runner_fn=fake_runner,
    )
    run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    prepared_config = yaml.safe_load(calls[0].read_text(encoding="utf-8"))

    assert len(calls) == 1
    assert run_summary["selected_start_order"] == 2
    assert run_summary["sessions"][0]["order"] == 2
    assert prepared_config["calibration_reuse"]["calibration_in"] == str(resume_cal)


def test_manifest_runner_marks_haptic_tcp_failure_and_stops(tmp_path) -> None:
    config = _write_dualtask_config(tmp_path / "only-motor.yaml", feedback="motor_only")
    plan = _write_plan(tmp_path / "motor-plan.yaml", plan_id="motor_plan_1", modality="vibration")
    manifest_path = _write_manifest(
        tmp_path / "manifest.yaml",
        tmp_path=tmp_path,
        sessions=[
            {
                "session_label": "motor_single_01",
                "order": 1,
                "task_type": "single",
                "feedback_type": "motor_only",
                "config": str(config),
                "haptic_plan_config": str(plan),
                "plan_id": "motor_plan_1",
            },
            {
                "session_label": "motor_single_02",
                "order": 2,
                "task_type": "single",
                "feedback_type": "motor_only",
                "config": str(config),
                "haptic_plan_config": str(plan),
                "plan_id": "motor_plan_1",
            },
        ],
    )
    calls = 0

    def fake_runner(config_path: str | Path) -> Path:
        nonlocal calls
        calls += 1
        output_dir = tmp_path / f"failed_session_{calls}"
        output_dir.mkdir()
        (output_dir / "summary.json").write_text(
            json.dumps({"haptic_tcp_failed": True, "end_reason": "haptic_tcp_failed"}),
            encoding="utf-8",
        )
        return output_dir

    run_dir = run_participant_manifest(manifest_path, runner_fn=fake_runner)
    run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))

    assert calls == 1
    assert run_summary["failed_session_count"] == 1
    assert run_summary["sessions"][0]["status"] == "failed"
    assert run_summary["sessions"][0]["error"] == "haptic_tcp_failed"


def test_manifest_runner_records_operator_abort_without_traceback(tmp_path) -> None:
    config = _write_dualtask_config(tmp_path / "only-motor.yaml", feedback="motor_only")
    plan = _write_plan(tmp_path / "motor-plan.yaml", plan_id="motor_plan_1", modality="vibration")
    manifest_path = _write_manifest(
        tmp_path / "manifest.yaml",
        tmp_path=tmp_path,
        sessions=[
            {
                "session_label": "motor_single_01",
                "order": 1,
                "task_type": "single",
                "feedback_type": "motor_only",
                "config": str(config),
                "haptic_plan_config": str(plan),
                "plan_id": "motor_plan_1",
            },
            {
                "session_label": "motor_single_02",
                "order": 2,
                "task_type": "single",
                "feedback_type": "motor_only",
                "config": str(config),
                "haptic_plan_config": str(plan),
                "plan_id": "motor_plan_1",
            },
        ],
    )
    calls = 0

    def fake_runner(config_path: str | Path) -> Path:
        nonlocal calls
        calls += 1
        raise OperatorAbort("operator_aborted")

    run_dir = run_participant_manifest(manifest_path, runner_fn=fake_runner)
    run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))

    assert calls == 1
    assert run_summary["aborted_session_count"] == 1
    assert run_summary["sessions"][0]["status"] == "aborted"
    assert len(run_summary["sessions"]) == 1


def test_prepare_session_config_derives_reproducible_seeds(tmp_path) -> None:
    config = _write_dualtask_config(tmp_path / "only-motor.yaml", feedback="motor_only")
    plan = _write_plan(tmp_path / "motor-plan.yaml", plan_id="motor_plan_1", modality="vibration")
    manifest = load_participant_manifest(
        _write_manifest(
            tmp_path / "manifest.yaml",
            tmp_path=tmp_path,
            sessions=[
                {
                    "session_label": "motor_single_01",
                    "order": 1,
                    "task_type": "single",
                    "feedback_type": "motor_only",
                    "config": str(config),
                    "haptic_plan_config": str(plan),
                    "plan_id": "motor_plan_1",
                }
            ],
        )
    )

    first = prepare_session_config(
        manifest,
        manifest.sessions[0],
        run_dir=tmp_path / "run_a",
        config_dir=tmp_path / "run_a" / "configs",
        current_calibration_path=manifest.calibration_path,
    )
    second = prepare_session_config(
        manifest,
        manifest.sessions[0],
        run_dir=tmp_path / "run_b",
        config_dir=tmp_path / "run_b" / "configs",
        current_calibration_path=manifest.calibration_path,
    )

    assert first.session_seed == second.session_seed
    assert first.haptic_seed == second.haptic_seed
    assert first.nback_seed == second.nback_seed


def _write_manifest(path: Path, *, tmp_path: Path, sessions: list[dict]) -> Path:
    payload = {
        "participant_id": "P001",
        "run_id": "P001_exp2_001",
        "run_seed": 12345,
        "output_root": str(tmp_path / "outputs"),
        "calibration": {
            "path": str(tmp_path / "calibrations" / "P001_exp2_cal_v01.json"),
            "reuse": True,
            "quick_check": True,
        },
        "sessions": sessions,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _write_dualtask_config(path: Path, *, feedback: str) -> Path:
    vibration = feedback in {"motor_only", "combined"}
    matrix = feedback in {"matrix_only", "combined"}
    payload = {
        "session": {
            "session_id_prefix": "pinch_haptic_1back",
            "output_root": "outputs",
            "participant_id": "",
            "condition_id": "",
            "duration_s": 10,
            "haptic_plan_config": "unused.yaml",
        },
        "haptic": {
            "vibration_enabled": vibration,
            "matrix_enabled": matrix,
            "visual_text_cue_enabled": False,
        },
        "vibration_tcp": {"enabled": vibration},
        "matrix_tcp": {"enabled": matrix},
        "sync": {},
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _write_plan(path: Path, *, plan_id: str, modality: str) -> Path:
    contact = (
        {
            "name": "contact",
            "modality": "matrix",
            "channel_list": [1],
            "duration_ms": 100,
            "trigger_zone": "open_zone",
        }
        if modality == "matrix"
        else {
            "name": "contact",
            "modality": "vibration",
            "command_id": 1,
            "duration_ms": 100,
            "trigger_zone": "open_zone",
        }
    )
    release = (
        {
            "name": "release",
            "modality": "matrix",
            "channel_list": [2],
            "duration_ms": 100,
            "trigger_zone": "closed_zone",
        }
        if modality == "matrix"
        else {
            "name": "release",
            "modality": "vibration",
            "command_id": 2,
            "duration_ms": 100,
            "trigger_zone": "closed_zone",
        }
    )
    payload = {
        "plan_id": plan_id,
        "description": "",
        "random_seed": 1,
        "timing": {
            "contact_onset_delay_ms": [0, 0],
            "inter_event_gap_ms": [0, 0],
            "refractory_ms": 0,
        },
        "zones": {
            "open_zone": {"lower": "auto_a", "upper": "auto_max"},
            "closed_zone": {"lower": "auto_min", "upper": "auto_a"},
        },
        "events": [contact, release],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path
