"""The shipped example_orb_nq.yml must parse + resolve cleanly."""
from __future__ import annotations

from pathlib import Path

from bot.backtest.sim_client import SimExecutionClient
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.schedule import MarketHours
from bot.runtime.fleet.spec import load_bot_specs
from bot.strategy.orb import OpeningRangeBreakoutStrategy

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BOTS_DIR = _REPO_ROOT / "config" / "bots"


def test_example_loads() -> None:
    specs = load_bot_specs(_BOTS_DIR)
    assert any(s.name == "example_orb_nq" for s in specs)
    spec = next(s for s in specs if s.name == "example_orb_nq")
    assert spec.enabled is False  # ships disabled by default


def test_example_resolves_through_registry() -> None:
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "example_orb_nq")
    reg = BotRegistry()
    resolved = reg.build(spec, broker=SimExecutionClient())
    assert isinstance(resolved.strategy, OpeningRangeBreakoutStrategy)
    assert isinstance(resolved.schedule, MarketHours)
