"""SURGEBOT_DEFAULTS structure + registry wiring for "orb_5m_tiered"."""
from __future__ import annotations

from pathlib import Path

import yaml

from bot.backtest.sim_client import SimExecutionClient
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.spec import BotSpec
from bot.strategy.orb import OpeningRangeBreakoutStrategy
from bot.strategy.profiles.surgebot import SURGEBOT_DEFAULTS
from bot.strategy.tiered_sizing import TieredSizingDecorator


def _spec(strategy_params: dict[str, object]) -> BotSpec:
    return BotSpec(
        name="surge_test",
        enabled=True,
        symbol="MNQ",
        strategy_id="orb_5m_tiered",
        strategy_params=strategy_params,
        risk_policy="combine_intraday",
        risk_params={"start_balance": 50_000, "mll_amount": 2_000, "max_mini": 5},
        schedule_type="market_hours",
        schedule_params={"open_ct": "08:30", "close_ct": "15:00"},
        journal_path=Path("state/journal_surge_test.db"),
    )


def test_defaults_have_required_top_level_keys() -> None:
    assert set(SURGEBOT_DEFAULTS.keys()) == {"strategy", "tiered"}


def test_defaults_use_real_orb_field_names() -> None:
    strat = SURGEBOT_DEFAULTS["strategy"]
    # Real ORBProfile fields (NOT atr_multiplier / reward_ratio).
    assert "atr_mult" in strat
    assert "tp_r_multiple" in strat
    assert "atr_multiplier" not in strat
    assert "reward_ratio" not in strat


def test_defaults_round_trip_through_yaml() -> None:
    raw = yaml.safe_dump(SURGEBOT_DEFAULTS)
    restored = yaml.safe_load(raw)
    assert restored["strategy"]["range_minutes"] == 5
    # YAML normalises tuples to lists — confirmed.
    assert restored["tiered"]["tier_breakpoints"][0] == [0.0, 1]


def test_registry_resolves_orb_5m_tiered() -> None:
    reg = BotRegistry()
    spec = _spec(SURGEBOT_DEFAULTS)
    resolved = reg.build(spec, broker=SimExecutionClient())
    assert isinstance(resolved.strategy, TieredSizingDecorator)


def test_registry_orb_5m_tiered_inner_is_orb() -> None:
    reg = BotRegistry()
    spec = _spec(SURGEBOT_DEFAULTS)
    resolved = reg.build(spec, broker=SimExecutionClient())
    # decorator holds the inner strategy; assert it's the ORB instance.
    inner = resolved.strategy._inner  # type: ignore[attr-defined]
    assert isinstance(inner, OpeningRangeBreakoutStrategy)


def test_registry_orb_5m_tiered_accepts_yaml_list_of_lists_breakpoints() -> None:
    """A YAML-loaded spec hands the decorator list-of-lists; it must accept that."""
    reg = BotRegistry()
    spec = _spec({
        "strategy": SURGEBOT_DEFAULTS["strategy"],
        "tiered": {
            "tier_breakpoints": [[0, 1], [500, 2], [1500, 4], [2500, 5]],
            "symbol": "MNQ",
        },
    })
    resolved = reg.build(spec, broker=SimExecutionClient())
    assert isinstance(resolved.strategy, TieredSizingDecorator)
