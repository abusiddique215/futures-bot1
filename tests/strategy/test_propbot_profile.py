"""PROPBOT_DEFAULTS + trend_ema_pullback registry wiring."""
from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Any

from bot.backtest.sim_client import SimExecutionClient
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.spec import BotSpec
from bot.strategy.profiles.propbot import PROPBOT_DEFAULTS
from bot.strategy.trend_following import TrendFollowingStrategy


def _spec(strategy_params: dict[str, Any] | None = None) -> BotSpec:
    return BotSpec(
        name="propbot_test",
        enabled=True,
        symbol="MNQ",
        strategy_id="trend_ema_pullback",
        strategy_params=strategy_params or {},
        risk_policy="efa_standard",
        risk_params={"mll_amount": 2_000},
        schedule_type="market_hours",
        schedule_params={"open_ct": "09:00", "close_ct": "14:30"},
        journal_path=Path("state/journal_propbot_test.db"),
    )


def test_defaults_match_plan_schema() -> None:
    """PROPBOT_DEFAULTS must mirror the BotSpec YAML schema (Plan 16 T3)."""
    assert PROPBOT_DEFAULTS["fast_ema"] == 20
    assert PROPBOT_DEFAULTS["slow_ema"] == 50
    assert PROPBOT_DEFAULTS["pullback_atr_mult"] == 0.5
    assert PROPBOT_DEFAULTS["reward_ratio"] == 1.5
    assert PROPBOT_DEFAULTS["max_trades_per_day"] == 1
    assert PROPBOT_DEFAULTS["session_end_ct"] == time(14, 30)


def test_registry_resolves_trend_ema_pullback() -> None:
    """Built-in 'trend_ema_pullback' factory yields a TrendFollowingStrategy."""
    reg = BotRegistry()
    resolved = reg.build(_spec(), broker=SimExecutionClient())
    assert isinstance(resolved.strategy, TrendFollowingStrategy)


def test_registry_yaml_overrides_apply() -> None:
    """YAML params override PROPBOT_DEFAULTS field-by-field."""
    reg = BotRegistry()
    resolved = reg.build(
        _spec({
            "fast_ema": 10,
            "slow_ema": 30,
            "max_trades_per_day": 3,
            "session_end_ct": "14:00",
        }),
        broker=SimExecutionClient(),
    )
    strat = resolved.strategy
    assert isinstance(strat, TrendFollowingStrategy)
    assert strat._fast_period == 10  # type: ignore[attr-defined]
    assert strat._slow_period == 30  # type: ignore[attr-defined]
    assert strat._max_trades_per_day == 3  # type: ignore[attr-defined]
    assert strat._session_end_ct == time(14, 0)  # type: ignore[attr-defined]


def test_registry_session_end_ct_accepts_python_time() -> None:
    """When strategy_params is a Python dict (not YAML), `time` values pass through."""
    reg = BotRegistry()
    resolved = reg.build(
        _spec({"session_end_ct": time(13, 45)}),
        broker=SimExecutionClient(),
    )
    strat = resolved.strategy
    assert isinstance(strat, TrendFollowingStrategy)
    assert strat._session_end_ct == time(13, 45)  # type: ignore[attr-defined]
