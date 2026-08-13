from __future__ import annotations

import pytest

from session_seeds import session_seed_info_from_config


def test_session_seed_derives_independent_reproducible_child_seeds() -> None:
    first = session_seed_info_from_config({"session_seed": 381274})
    second = session_seed_info_from_config({"session_seed": 381274})

    assert first == second
    assert first.session_seed == 381274
    assert first.session_seed_source == "config"
    assert first.haptic_seed != first.nback_seed


def test_session_seed_is_generated_when_missing() -> None:
    info = session_seed_info_from_config({})

    assert info.session_seed > 0
    assert info.session_seed_source == "generated"
    assert info.haptic_seed > 0
    assert info.nback_seed > 0


def test_session_seed_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="session.session_seed"):
        session_seed_info_from_config({"session_seed": 0})
