"""Session-level seed resolution and deterministic child seed derivation."""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass
from typing import Any


MAX_SEED = 2**31 - 1


@dataclass(frozen=True)
class SessionSeedInfo:
    session_seed: int
    session_seed_source: str
    haptic_seed: int
    nback_seed: int

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


def session_seed_info_from_config(session_config: dict[str, Any]) -> SessionSeedInfo:
    value = session_config.get("session_seed")
    if value is None:
        session_seed = _generate_session_seed()
        source = "generated"
    else:
        session_seed = _seed_value(value, "session.session_seed")
        source = "config"
    return SessionSeedInfo(
        session_seed=session_seed,
        session_seed_source=source,
        haptic_seed=_derive_child_seed(session_seed, "haptic"),
        nback_seed=_derive_child_seed(session_seed, "nback"),
    )


def _generate_session_seed() -> int:
    return int(time.time_ns() % MAX_SEED) or 1


def _derive_child_seed(session_seed: int, label: str) -> int:
    payload = f"{int(session_seed)}:{label}".encode("ascii")
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
