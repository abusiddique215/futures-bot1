"""ORBProfile Pydantic model + YAML loader."""
from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest


def test_orb_profile_defaults_applied() -> None:
    from bot.strategy.orb import ORBProfile
    p = ORBProfile()
    assert p.symbol == "MNQ"
    assert p.quantity == 1
    assert p.range_minutes == 5
    assert p.atr_mult == 1.0
    assert p.tp_r_multiple == 2.0
    assert p.session_start_et == time(9, 30)
    assert p.cutoff_time_et is None
    assert p.max_trades_per_day == 1


def test_orb_profile_rejects_invalid_atr_mult() -> None:
    from pydantic import ValidationError

    from bot.strategy.orb import ORBProfile
    with pytest.raises(ValidationError):
        ORBProfile(atr_mult=0.0)


def test_orb_profile_rejects_invalid_quantity() -> None:
    from pydantic import ValidationError

    from bot.strategy.orb import ORBProfile
    with pytest.raises(ValidationError):
        ORBProfile(quantity=0)


def test_load_surge_profile_from_yaml(tmp_path: Path) -> None:
    from bot.strategy.profile_loader import load_orb_profile

    profile = load_orb_profile(
        Path("config/profiles/surge.yml"),
    )
    assert profile.quantity == 2
    assert profile.atr_mult == 1.0
    assert profile.tp_r_multiple == 2.0
    assert profile.max_trades_per_day == 2
    assert profile.cutoff_time_et is None


def test_load_maintenance_profile_from_yaml() -> None:
    from bot.strategy.profile_loader import load_orb_profile

    profile = load_orb_profile(Path("config/profiles/maintenance.yml"))
    assert profile.quantity == 1
    assert profile.atr_mult == 0.8
    assert profile.tp_r_multiple == 1.5
    assert profile.max_trades_per_day == 1
    assert profile.cutoff_time_et == time(11, 30)


def test_load_profile_rejects_invalid_yaml(tmp_path: Path) -> None:
    from pydantic import ValidationError

    from bot.strategy.profile_loader import load_orb_profile
    bad = tmp_path / "bad.yml"
    bad.write_text("quantity: 0\natr_mult: 1.0\n")
    with pytest.raises(ValidationError):
        load_orb_profile(bad)
