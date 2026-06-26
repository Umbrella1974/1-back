"""Haptic trial plan config parsing and validation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


LEGAL_MIDDLE_EVENTS = {"slip", "left", "right"}
LEGAL_EVENT_NAMES = {"contact", "release", *LEGAL_MIDDLE_EVENTS}
LEGAL_MODALITIES = {"vibration", "matrix"}
LEGAL_ONSET_POLICY_TYPES = {"when_enter_zone", "after_zone_transition", "after_previous"}
AUTO_ZONE_VALUES = {"auto_min", "auto_a", "auto_max"}


@dataclass(frozen=True)
class HapticOnsetPolicy:
    type: str
    zone: str | None = None
    from_zone: str | None = None
    to_zone: str | None = None
    gap_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HapticPlanEvent:
    name: str
    modality: str
    duration_ms: int
    trigger_zone: str
    onset_policy: HapticOnsetPolicy
    command_label: str | None = None
    command_id: int | None = None
    channel_list: tuple[int, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["channel_list"] = list(self.channel_list)
        return payload


@dataclass(frozen=True)
class HapticZoneSpec:
    lower: str | float
    upper: str | float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HapticPlanConfig:
    plan_id: str
    description: str
    random_seed: int | None
    events: tuple[HapticPlanEvent, ...]
    zones: dict[str, HapticZoneSpec]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "description": self.description,
            "random_seed": self.random_seed,
            "events": [event.to_dict() for event in self.events],
            "zones": {name: zone.to_dict() for name, zone in self.zones.items()},
        }


def load_haptic_plan_config(path: str | Path) -> HapticPlanConfig:
    """Load and validate a haptic plan config from YAML or JSON."""

    target = Path(path)
    payload = _load_mapping(target)
    return haptic_plan_config_from_dict(payload)


def haptic_plan_config_from_dict(payload: dict[str, Any]) -> HapticPlanConfig:
    """Validate a haptic plan config payload."""

    if not isinstance(payload, dict):
        raise ValueError("haptic plan config must be an object.")
    allowed = {"plan_id", "description", "random_seed", "events", "zones"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown haptic plan config keys: {', '.join(unknown)}")

    plan_id = str(payload.get("plan_id", "")).strip()
    if not plan_id:
        raise ValueError("plan_id is required.")
    random_seed = payload.get("random_seed")
    if random_seed is not None:
        random_seed = _int_value(random_seed, "random_seed")
    zones = _parse_zones(payload.get("zones"))
    events = _parse_events(payload.get("events"), zones)
    _validate_event_order(events)
    return HapticPlanConfig(
        plan_id=plan_id,
        description=str(payload.get("description", "")),
        random_seed=random_seed,
        events=tuple(events),
        zones=zones,
    )


def _parse_events(
    value: Any,
    zones: dict[str, HapticZoneSpec],
) -> list[HapticPlanEvent]:
    if not isinstance(value, list) or not value:
        raise ValueError("events must be a non-empty list.")
    events = [_parse_event(item, index, zones) for index, item in enumerate(value)]
    return events


def _parse_event(
    payload: Any,
    index: int,
    zones: dict[str, HapticZoneSpec],
) -> HapticPlanEvent:
    name_prefix = f"events[{index}]"
    if not isinstance(payload, dict):
        raise ValueError(f"{name_prefix} must be an object.")
    allowed = {
        "name",
        "modality",
        "command_label",
        "command_id",
        "duration_ms",
        "trigger_zone",
        "onset_policy",
        "channel_list",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown {name_prefix} keys: {', '.join(unknown)}")

    event_name = str(payload.get("name", "")).strip()
    if event_name not in LEGAL_EVENT_NAMES:
        raise ValueError(f"{name_prefix}.name must be one of: {', '.join(sorted(LEGAL_EVENT_NAMES))}.")
    modality = str(payload.get("modality", "")).strip()
    if modality not in LEGAL_MODALITIES:
        raise ValueError(f"{name_prefix}.modality must be vibration or matrix.")
    expected_modality = "matrix" if event_name in {"left", "right"} else "vibration"
    if modality != expected_modality:
        raise ValueError(f"{name_prefix}.{event_name} must use modality {expected_modality}.")

    trigger_zone = str(payload.get("trigger_zone", "")).strip()
    if trigger_zone not in zones:
        raise ValueError(f"{name_prefix}.trigger_zone references unknown zone: {trigger_zone}")
    duration_ms = _positive_int(payload.get("duration_ms"), f"{name_prefix}.duration_ms")
    onset_policy = _parse_onset_policy(payload.get("onset_policy"), name_prefix, zones)
    command_label = _optional_str(payload.get("command_label"))
    command_id = (
        _positive_int(payload.get("command_id"), f"{name_prefix}.command_id")
        if payload.get("command_id") is not None
        else None
    )
    channel_list = _channel_list(payload.get("channel_list", ()), f"{name_prefix}.channel_list")

    if modality == "vibration" and command_label is None and command_id is None:
        raise ValueError(f"{name_prefix} vibration event requires command_label or command_id.")
    if modality == "matrix" and not channel_list:
        raise ValueError(f"{name_prefix} matrix event requires non-empty channel_list.")

    return HapticPlanEvent(
        name=event_name,
        modality=modality,
        duration_ms=duration_ms,
        trigger_zone=trigger_zone,
        onset_policy=onset_policy,
        command_label=command_label,
        command_id=command_id,
        channel_list=channel_list,
    )


def _validate_event_order(events: list[HapticPlanEvent]) -> None:
    if len(events) < 2:
        raise ValueError("events must contain at least contact and release.")
    if events[0].name != "contact":
        raise ValueError("first haptic plan event must be contact.")
    if events[-1].name != "release":
        raise ValueError("last haptic plan event must be release.")
    for index, event in enumerate(events[1:-1], start=1):
        if event.name not in LEGAL_MIDDLE_EVENTS:
            raise ValueError(
                f"middle haptic plan event at index {index} must be slip, left, or right."
            )


def _parse_onset_policy(
    payload: Any,
    event_prefix: str,
    zones: dict[str, HapticZoneSpec],
) -> HapticOnsetPolicy:
    name = f"{event_prefix}.onset_policy"
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be an object.")
    allowed = {"type", "zone", "from_zone", "to_zone", "gap_ms"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown {name} keys: {', '.join(unknown)}")
    policy_type = str(payload.get("type", "")).strip()
    if policy_type not in LEGAL_ONSET_POLICY_TYPES:
        raise ValueError(f"{name}.type must be one of: {', '.join(sorted(LEGAL_ONSET_POLICY_TYPES))}.")
    zone = _optional_zone(payload.get("zone"), zones, f"{name}.zone")
    from_zone = _optional_zone(payload.get("from_zone"), zones, f"{name}.from_zone")
    to_zone = _optional_zone(payload.get("to_zone"), zones, f"{name}.to_zone")
    gap_ms = (
        _non_negative_int(payload.get("gap_ms"), f"{name}.gap_ms")
        if payload.get("gap_ms") is not None
        else 0
    )
    if policy_type == "when_enter_zone" and zone is None:
        raise ValueError(f"{name}.zone is required for when_enter_zone.")
    if policy_type == "after_zone_transition" and (from_zone is None or to_zone is None):
        raise ValueError(f"{name}.from_zone and {name}.to_zone are required for after_zone_transition.")
    return HapticOnsetPolicy(
        type=policy_type,
        zone=zone,
        from_zone=from_zone,
        to_zone=to_zone,
        gap_ms=gap_ms,
    )


def _parse_zones(value: Any) -> dict[str, HapticZoneSpec]:
    if not isinstance(value, dict) or not value:
        raise ValueError("zones must be a non-empty object.")
    zones: dict[str, HapticZoneSpec] = {}
    for zone_name, zone_payload in value.items():
        name = str(zone_name).strip()
        if not name:
            raise ValueError("zone names must be non-empty.")
        if not isinstance(zone_payload, dict):
            raise ValueError(f"zones.{name} must be an object.")
        allowed = {"lower", "upper"}
        unknown = sorted(set(zone_payload) - allowed)
        if unknown:
            raise ValueError(f"unknown zones.{name} keys: {', '.join(unknown)}")
        zones[name] = HapticZoneSpec(
            lower=_zone_bound(zone_payload.get("lower"), f"zones.{name}.lower"),
            upper=_zone_bound(zone_payload.get("upper"), f"zones.{name}.upper"),
        )
    return zones


def _load_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"haptic plan config not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("YAML haptic plan configs require PyYAML.") from exc
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        raise ValueError("haptic plan config must be .json, .yaml, or .yml")
    if not isinstance(payload, dict):
        raise ValueError("haptic plan config must be an object.")
    return payload


def _optional_zone(
    value: Any,
    zones: dict[str, HapticZoneSpec],
    name: str,
) -> str | None:
    if value is None:
        return None
    zone = str(value).strip()
    if zone not in zones:
        raise ValueError(f"{name} references unknown zone: {zone}")
    return zone


def _zone_bound(value: Any, name: str) -> str | float:
    if isinstance(value, str):
        bound = value.strip()
        if bound not in AUTO_ZONE_VALUES:
            raise ValueError(f"{name} must be auto_min, auto_a, auto_max, or a number.")
        return bound
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be auto_min, auto_a, auto_max, or a number.") from exc


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _channel_list(value: Any, name: str) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise ValueError(f"{name} must be a list.")
    channels: list[int] = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, int):
            raise ValueError(f"{name} channels must be integers.")
        if channel < 0 or channel > 127:
            raise ValueError(f"{name} channel must be in 0..127.")
        channels.append(int(channel))
    return tuple(channels)


def _int_value(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer.")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    return result


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

