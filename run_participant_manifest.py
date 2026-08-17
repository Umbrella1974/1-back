"""Participant-level manifest runner for Exp2 sessions."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from haptic_plan_config import load_haptic_plan_config
from run_pinch_haptic_1back import (
    OperatorAbort,
    TASK_TYPE_DUAL,
    TASK_TYPE_SINGLE,
    run_live_pinch_haptic_1back,
)
from run_pinch_haptic_dry_run import load_dualtask_config
from session_seeds import MAX_SEED


FEEDBACK_TYPES = {"combined", "motor_only", "matrix_only"}
TASK_TYPES = {TASK_TYPE_DUAL, TASK_TYPE_SINGLE, "tactile_only"}


@dataclass(frozen=True)
class ManifestSession:
    session_label: str
    order: int
    task_type: str
    feedback_type: str
    config_path: Path
    haptic_plan_config_path: Path
    plan_id: str = ""
    condition_id: str = ""


@dataclass(frozen=True)
class ParticipantManifest:
    path: Path
    participant_id: str
    run_id: str
    run_seed: int
    run_seed_source: str
    output_root: Path
    calibration_path: Path | None
    calibration_reuse: bool
    calibration_quick_check: bool
    sessions: tuple[ManifestSession, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedSession:
    manifest_session: ManifestSession
    session_seed: int
    haptic_seed: int
    nback_seed: int
    config_path: Path
    expected_plan_id: str


@dataclass
class ManifestValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


def run_participant_manifest(
    manifest_path: str | Path,
    *,
    validate_only: bool = False,
    start_order: int | None = None,
    only_order: int | None = None,
    calibration_in: str | Path | None = None,
    runner_fn: Callable[[str | Path], Path] = run_live_pinch_haptic_1back,
) -> Path:
    if start_order is not None and only_order is not None:
        raise ValueError("--start-order and --only-order cannot be used together.")
    manifest = load_participant_manifest(manifest_path)
    validation = validate_participant_manifest(manifest)
    if not validation.passed:
        raise ValueError("manifest validation failed:\n" + "\n".join(validation.errors))
    selected_sessions = _select_manifest_sessions(
        manifest.sessions,
        start_order=start_order,
        only_order=only_order,
    )
    if not selected_sessions:
        raise ValueError("no manifest sessions selected.")

    run_dir = manifest.output_root / manifest.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "run_summary.json"
    config_dir = run_dir / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    current_calibration_path = (
        Path(calibration_in) if calibration_in is not None else manifest.calibration_path
    )
    session_rows: list[dict[str, Any]] = []
    run_summary = _base_run_summary(manifest, validation)
    run_summary["selected_start_order"] = start_order
    run_summary["selected_only_order"] = only_order
    run_summary["resume_calibration_in"] = str(calibration_in or "")
    run_summary["selected_session_count"] = len(selected_sessions)
    run_summary["active_calibration_path"] = (
        str(current_calibration_path) if current_calibration_path is not None else ""
    )
    _write_json(summary_path, run_summary)

    if validate_only:
        prepared = [
            prepare_session_config(
                manifest,
                session,
                run_dir=run_dir,
                config_dir=config_dir,
                current_calibration_path=current_calibration_path,
            )
            for session in selected_sessions
        ]
        run_summary["validate_only"] = True
        run_summary["prepared_session_count"] = len(prepared)
        run_summary["sessions"] = [_prepared_session_row(item) for item in prepared]
        _write_json(summary_path, run_summary)
        return run_dir

    for session in selected_sessions:
        prepared = prepare_session_config(
            manifest,
            session,
            run_dir=run_dir,
            config_dir=config_dir,
            current_calibration_path=current_calibration_path,
        )
        row = _prepared_session_row(prepared)
        row["status"] = "running"
        session_rows.append(row)
        run_summary["sessions"] = session_rows
        run_summary["completed_session_count"] = _completed_count(session_rows)
        _write_json(summary_path, run_summary)
        try:
            output_path = runner_fn(prepared.config_path)
            row["status"] = "completed"
            row["output_path"] = str(output_path)
            session_summary = _read_session_summary(output_path)
            row["session_summary_path"] = str(Path(output_path) / "summary.json")
            row["calibration_id"] = session_summary.get("calibration_id", "")
            row["calibration_loaded_from_bundle"] = session_summary.get(
                "calibration_loaded_from_bundle",
                False,
            )
            row["calibration_saved_path"] = session_summary.get("calibration_saved_path", "")
            if _session_haptic_tcp_failed(session_summary):
                row["status"] = "failed"
                row["error"] = "haptic_tcp_failed"
                run_summary["sessions"] = session_rows
                run_summary["completed_session_count"] = _completed_count(session_rows)
                run_summary["failed_session_count"] = _failed_count(session_rows)
                run_summary["aborted_session_count"] = _aborted_count(session_rows)
                run_summary["end_wall_time_iso"] = _now_iso()
                _write_json(summary_path, run_summary)
                return run_dir
            saved_calibration = str(session_summary.get("calibration_saved_path", "") or "")
            if saved_calibration:
                current_calibration_path = Path(saved_calibration)
            elif current_calibration_path is not None:
                row["calibration_path_after_session"] = str(current_calibration_path)
        except OperatorAbort as exc:
            row["status"] = "aborted"
            row["error"] = str(exc)
            run_summary["sessions"] = session_rows
            run_summary["completed_session_count"] = _completed_count(session_rows)
            run_summary["failed_session_count"] = _failed_count(session_rows)
            run_summary["aborted_session_count"] = _aborted_count(session_rows)
            run_summary["end_wall_time_iso"] = _now_iso()
            _write_json(summary_path, run_summary)
            return run_dir
        except Exception as exc:
            row["status"] = "failed"
            row["error"] = str(exc)
            run_summary["sessions"] = session_rows
            run_summary["completed_session_count"] = _completed_count(session_rows)
            run_summary["failed_session_count"] = _failed_count(session_rows)
            run_summary["aborted_session_count"] = _aborted_count(session_rows)
            run_summary["end_wall_time_iso"] = _now_iso()
            _write_json(summary_path, run_summary)
            raise
        run_summary["sessions"] = session_rows
        run_summary["completed_session_count"] = _completed_count(session_rows)
        run_summary["failed_session_count"] = _failed_count(session_rows)
        run_summary["aborted_session_count"] = _aborted_count(session_rows)
        run_summary["active_calibration_path"] = (
            str(current_calibration_path) if current_calibration_path is not None else ""
        )
        _write_json(summary_path, run_summary)

    run_summary["end_wall_time_iso"] = _now_iso()
    _write_json(summary_path, run_summary)
    return run_dir


def load_participant_manifest(path: str | Path) -> ParticipantManifest:
    target = Path(path)
    payload = _load_yaml_mapping(target)
    base_dir = target.resolve().parent
    participant_id = str(payload.get("participant_id", "")).strip()
    run_id = str(payload.get("run_id", "")).strip()
    run_seed_value = payload.get("run_seed")
    run_seed_source = "config"
    if run_seed_value is None:
        run_seed = _generate_run_seed()
        run_seed_source = "generated"
    else:
        run_seed = _seed_value(run_seed_value, "run_seed")
    output_root = _resolve_path(payload.get("output_root", "outputs"), base_dir=base_dir)
    calibration_payload = payload.get("calibration", {}) or {}
    if not isinstance(calibration_payload, dict):
        raise ValueError("calibration section must be an object.")
    calibration_path = (
        _resolve_path(calibration_payload.get("path"), base_dir=base_dir)
        if calibration_payload.get("path") not in {None, ""}
        else None
    )
    sessions_payload = payload.get("sessions", [])
    if not isinstance(sessions_payload, list):
        raise ValueError("sessions must be a list.")
    sessions = tuple(
        _manifest_session_from_dict(item, base_dir=base_dir)
        for item in sessions_payload
    )
    return ParticipantManifest(
        path=target,
        participant_id=participant_id,
        run_id=run_id,
        run_seed=run_seed,
        run_seed_source=run_seed_source,
        output_root=output_root,
        calibration_path=calibration_path,
        calibration_reuse=bool(calibration_payload.get("reuse", True)),
        calibration_quick_check=bool(calibration_payload.get("quick_check", True)),
        sessions=tuple(sorted(sessions, key=lambda item: item.order)),
    )


def _select_manifest_sessions(
    sessions: tuple[ManifestSession, ...],
    *,
    start_order: int | None,
    only_order: int | None,
) -> tuple[ManifestSession, ...]:
    if only_order is not None:
        return tuple(session for session in sessions if session.order == int(only_order))
    if start_order is not None:
        return tuple(session for session in sessions if session.order >= int(start_order))
    return tuple(sessions)


def validate_participant_manifest(manifest: ParticipantManifest) -> ManifestValidationResult:
    result = ManifestValidationResult()
    if not manifest.participant_id:
        result.errors.append("participant_id is required.")
    if not manifest.run_id:
        result.errors.append("run_id is required.")
    if not manifest.sessions:
        result.errors.append("at least one session is required.")

    labels: set[str] = set()
    orders: set[int] = set()
    condition_keys: set[tuple[str, str, str]] = set()
    for session in manifest.sessions:
        if not session.session_label:
            result.errors.append("session_label is required.")
        if session.session_label in labels:
            result.errors.append(f"duplicate session_label: {session.session_label}")
        labels.add(session.session_label)
        if session.order in orders:
            result.errors.append(f"duplicate session order: {session.order}")
        orders.add(session.order)
        if session.task_type not in TASK_TYPES:
            result.errors.append(f"{session.session_label}: unsupported task_type {session.task_type}")
        if session.feedback_type not in FEEDBACK_TYPES:
            result.errors.append(
                f"{session.session_label}: unsupported feedback_type {session.feedback_type}"
            )
        if not session.config_path.exists():
            result.errors.append(f"{session.session_label}: config not found: {session.config_path}")
            continue
        if not session.haptic_plan_config_path.exists():
            result.errors.append(
                f"{session.session_label}: haptic plan not found: {session.haptic_plan_config_path}"
            )
            continue
        try:
            config = load_dualtask_config(session.config_path)
            plan = load_haptic_plan_config(session.haptic_plan_config_path)
        except Exception as exc:
            result.errors.append(f"{session.session_label}: config/plan load failed: {exc}")
            continue
        if session.plan_id and session.plan_id != plan.plan_id:
            result.errors.append(
                f"{session.session_label}: plan_id {session.plan_id} != loaded {plan.plan_id}"
            )
        _validate_feedback_config(session, config, result)
        duplicate_key = (session.task_type, session.feedback_type, plan.plan_id)
        if duplicate_key in condition_keys:
            result.warnings.append(
                f"duplicate task/feedback/plan combination: {duplicate_key}"
            )
        condition_keys.add(duplicate_key)
    return result


def prepare_session_config(
    manifest: ParticipantManifest,
    session: ManifestSession,
    *,
    run_dir: Path,
    config_dir: Path,
    current_calibration_path: Path | None,
) -> PreparedSession:
    config = copy.deepcopy(load_dualtask_config(session.config_path))
    plan = load_haptic_plan_config(session.haptic_plan_config_path)
    session_seed = _derive_seed(manifest.run_seed, f"session:{session.order}:{session.session_label}")
    haptic_seed = _derive_seed(session_seed, "haptic")
    nback_seed = _derive_seed(session_seed, "nback")
    session_config = config.setdefault("session", {})
    session_config["participant_id"] = manifest.participant_id
    session_config["condition_id"] = session.condition_id or _condition_id(session, plan.plan_id)
    session_config["task_type"] = _normalize_manifest_task_type(session.task_type)
    session_config["session_seed"] = session_seed
    session_config["session_id_prefix"] = f"{manifest.run_id}_{session.order:02d}_{session.session_label}"
    session_config["output_root"] = str(run_dir / "sessions")
    session_config["haptic_plan_config"] = str(session.haptic_plan_config_path)
    if manifest.calibration_reuse and current_calibration_path is not None:
        config["calibration_reuse"] = {
            "enabled": True,
            "calibration_in": str(current_calibration_path),
            "calibration_out": str(current_calibration_path),
            "calibration_id": current_calibration_path.stem,
            "quick_check_enabled": manifest.calibration_quick_check,
        }
    output_config = config_dir / f"{session.order:02d}_{session.session_label}.yaml"
    output_config.parent.mkdir(parents=True, exist_ok=True)
    _write_yaml(output_config, config)
    return PreparedSession(
        manifest_session=session,
        session_seed=session_seed,
        haptic_seed=haptic_seed,
        nback_seed=nback_seed,
        config_path=output_config,
        expected_plan_id=plan.plan_id,
    )


def _manifest_session_from_dict(payload: Any, *, base_dir: Path) -> ManifestSession:
    if not isinstance(payload, dict):
        raise ValueError("each session must be an object.")
    return ManifestSession(
        session_label=str(payload.get("session_label", "")).strip(),
        order=int(payload.get("order", 0)),
        task_type=_normalize_manifest_task_type(str(payload.get("task_type", "")).strip()),
        feedback_type=str(payload.get("feedback_type", "")).strip(),
        config_path=_resolve_path(payload.get("config"), base_dir=base_dir),
        haptic_plan_config_path=_resolve_path(payload.get("haptic_plan_config"), base_dir=base_dir),
        plan_id=str(payload.get("plan_id", "") or "").strip(),
        condition_id=str(payload.get("condition_id", "") or "").strip(),
    )


def _validate_feedback_config(
    session: ManifestSession,
    config: dict[str, Any],
    result: ManifestValidationResult,
) -> None:
    haptic = config.get("haptic", {}) or {}
    vibration_tcp = config.get("vibration_tcp", {}) or {}
    matrix_tcp = config.get("matrix_tcp", {}) or {}
    vibration_enabled = bool(haptic.get("vibration_enabled", False))
    matrix_enabled = bool(haptic.get("matrix_enabled", False))
    vibration_tcp_enabled = bool(vibration_tcp.get("enabled", False))
    matrix_tcp_enabled = bool(matrix_tcp.get("enabled", False))
    if session.feedback_type == "combined":
        expected = vibration_enabled and matrix_enabled and vibration_tcp_enabled and matrix_tcp_enabled
    elif session.feedback_type == "motor_only":
        expected = vibration_enabled and not matrix_enabled and vibration_tcp_enabled and not matrix_tcp_enabled
    elif session.feedback_type == "matrix_only":
        expected = matrix_enabled and not vibration_enabled and matrix_tcp_enabled and not vibration_tcp_enabled
    else:
        return
    if not expected:
        result.errors.append(
            f"{session.session_label}: feedback_type {session.feedback_type} does not match "
            "haptic/vibration_tcp/matrix_tcp enabled flags."
        )


def _base_run_summary(
    manifest: ParticipantManifest,
    validation: ManifestValidationResult,
) -> dict[str, Any]:
    return {
        "participant_id": manifest.participant_id,
        "run_id": manifest.run_id,
        "run_seed": manifest.run_seed,
        "run_seed_source": manifest.run_seed_source,
        "manifest_path": str(manifest.path),
        "start_wall_time_iso": _now_iso(),
        "end_wall_time_iso": "",
        "planned_session_count": len(manifest.sessions),
        "completed_session_count": 0,
        "failed_session_count": 0,
        "aborted_session_count": 0,
        "calibration_path": str(manifest.calibration_path) if manifest.calibration_path else "",
        "active_calibration_path": str(manifest.calibration_path) if manifest.calibration_path else "",
        "calibration_reuse": manifest.calibration_reuse,
        "calibration_quick_check": manifest.calibration_quick_check,
        "validation_warnings": list(validation.warnings),
        "sessions": [],
    }


def _prepared_session_row(prepared: PreparedSession) -> dict[str, Any]:
    session = prepared.manifest_session
    return {
        "session_label": session.session_label,
        "order": session.order,
        "task_type": _normalize_manifest_task_type(session.task_type),
        "feedback_type": session.feedback_type,
        "plan_id": prepared.expected_plan_id,
        "config": str(session.config_path),
        "haptic_plan_config": str(session.haptic_plan_config_path),
        "prepared_config": str(prepared.config_path),
        "condition_id": session.condition_id or _condition_id(session, prepared.expected_plan_id),
        "session_seed": prepared.session_seed,
        "haptic_seed": prepared.haptic_seed,
        "nback_seed": prepared.nback_seed,
        "status": "prepared",
        "output_path": "",
        "error": "",
    }


def _condition_id(session: ManifestSession, plan_id: str) -> str:
    return f"{session.feedback_type}_{_normalize_manifest_task_type(session.task_type)}_{plan_id}"


def _normalize_manifest_task_type(value: str) -> str:
    task = str(value).strip().lower()
    if task == "tactile_only":
        return TASK_TYPE_SINGLE
    return task


def _completed_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row.get("status") == "completed")


def _failed_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row.get("status") == "failed")


def _aborted_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row.get("status") == "aborted")


def _read_session_summary(output_path: str | Path) -> dict[str, Any]:
    summary_path = Path(output_path) / "summary.json"
    if not summary_path.exists():
        return {}
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _session_haptic_tcp_failed(summary: dict[str, Any]) -> bool:
    return bool(summary.get("haptic_tcp_failed")) or str(
        summary.get("end_reason", "")
    ) == "haptic_tcp_failed"


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("participant manifest requires PyYAML.") from exc
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("participant manifest must be an object.")
    return payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("participant manifest requires PyYAML.") from exc
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _resolve_path(value: Any, *, base_dir: Path) -> Path:
    if value is None or str(value).strip() == "":
        raise ValueError("path value is required.")
    path = Path(str(value))
    return path if path.is_absolute() else base_dir / path


def _generate_run_seed() -> int:
    return int(time.time_ns() % MAX_SEED) or 1


def _derive_seed(parent_seed: int, label: str) -> int:
    payload = f"{int(parent_seed)}:{label}".encode("ascii")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") % MAX_SEED or 1


def _seed_value(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer or null.")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer or null.") from exc
    if result <= 0:
        raise ValueError(f"{name} must be a positive integer or null.")
    return result


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an Exp2 participant manifest.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--start-order", type=int, default=None)
    parser.add_argument("--only-order", type=int, default=None)
    parser.add_argument("--calibration-in", default=None)
    args = parser.parse_args()
    run_dir = run_participant_manifest(
        args.manifest,
        validate_only=args.validate_only,
        start_order=args.start_order,
        only_order=args.only_order,
        calibration_in=args.calibration_in,
    )
    print(f"Run output: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
