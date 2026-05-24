"""config/bots/surgebot_nq.yml must parse + resolve cleanly."""
from __future__ import annotations

from pathlib import Path

from bot.backtest.sim_client import SimExecutionClient
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.schedule import MarketHours
from bot.runtime.fleet.spec import load_bot_specs
from bot.strategy.orb import OpeningRangeBreakoutStrategy
from bot.strategy.tiered_sizing import TieredSizingDecorator

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BOTS_DIR = _REPO_ROOT / "config" / "bots"


def test_surgebot_yml_loads() -> None:
    specs = load_bot_specs(_BOTS_DIR)
    assert any(s.name == "surgebot_nq" for s in specs)


def test_surgebot_yml_ships_disabled() -> None:
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "surgebot_nq")
    # Don't auto-start the bot when the fleet boots — operator flips it on.
    assert spec.enabled is False


def test_surgebot_yml_resolves_to_tiered_decorator() -> None:
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "surgebot_nq")
    reg = BotRegistry()
    resolved = reg.build(spec, broker=SimExecutionClient())
    assert isinstance(resolved.strategy, TieredSizingDecorator)
    # decorator wraps an ORB instance.
    inner = resolved.strategy._inner  # type: ignore[attr-defined]
    assert isinstance(inner, OpeningRangeBreakoutStrategy)


def test_surgebot_yml_schedule_is_market_hours() -> None:
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "surgebot_nq")
    reg = BotRegistry()
    resolved = reg.build(spec, broker=SimExecutionClient())
    assert isinstance(resolved.schedule, MarketHours)


def test_surgebot_yml_journal_path_is_per_bot() -> None:
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "surgebot_nq")
    assert spec.journal_path == Path("state/journal_surgebot_nq.db")
