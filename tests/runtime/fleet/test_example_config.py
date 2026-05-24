"""The shipped example_orb_nq.yml + gold_bot.yml must parse + resolve cleanly."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.backtest.sim_client import SimExecutionClient
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.schedule import CustomWindows, MarketHours
from bot.runtime.fleet.spec import load_bot_specs
from bot.strategy.mean_reversion import MeanReversionStrategy
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


# ---- gold_bot.yml ---------------------------------------------------------


def test_gold_bot_loads() -> None:
    specs = load_bot_specs(_BOTS_DIR)
    spec = next(s for s in specs if s.name == "gold_bot")
    assert spec.enabled is True
    assert spec.symbol == "MGCH26"
    assert spec.strategy_id == "mean_reversion_bb"
    assert spec.schedule_type == "custom_windows"
    # All seven VSL-visible windows present.
    assert len(spec.schedule_params["windows"]) == 7


def test_gold_bot_resolves_through_registry() -> None:
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "gold_bot")
    reg = BotRegistry()
    resolved = reg.build(spec, broker=SimExecutionClient())
    assert isinstance(resolved.strategy, MeanReversionStrategy)
    assert isinstance(resolved.schedule, CustomWindows)
    assert resolved.strategy.symbol == "MGCH26"


def _at_et(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(
        year, month, day, hour, minute,
        tzinfo=ZoneInfo("America/New_York"),
    ).astimezone(UTC)


def test_gold_bot_schedule_admits_09_00_et() -> None:
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "gold_bot")
    sch = BotRegistry().build(spec, broker=SimExecutionClient()).schedule
    assert sch.should_trade(_at_et(2026, 5, 22, 9, 0))


def test_gold_bot_schedule_admits_23_30_et() -> None:
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "gold_bot")
    sch = BotRegistry().build(spec, broker=SimExecutionClient()).schedule
    assert sch.should_trade(_at_et(2026, 5, 22, 23, 30))


def test_gold_bot_schedule_admits_00_15_et_overnight() -> None:
    """Load-bearing overnight case: 00:15 ET is INSIDE the 23:00-01:30 window."""
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "gold_bot")
    sch = BotRegistry().build(spec, broker=SimExecutionClient()).schedule
    assert sch.should_trade(_at_et(2026, 5, 23, 0, 15))


def test_gold_bot_schedule_blocks_18_00_et() -> None:
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "gold_bot")
    sch = BotRegistry().build(spec, broker=SimExecutionClient()).schedule
    assert not sch.should_trade(_at_et(2026, 5, 22, 18, 0))


def test_gold_bot_schedule_blocks_03_00_et() -> None:
    """After the overnight window ends + before the news pre-window."""
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "gold_bot")
    sch = BotRegistry().build(spec, broker=SimExecutionClient()).schedule
    assert not sch.should_trade(_at_et(2026, 5, 22, 3, 0))
