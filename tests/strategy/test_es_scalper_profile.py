"""ES_SCALPER_DEFAULTS structure + registry wiring for "mean_reversion_bb".

Mirrors `tests/strategy/test_propbot_profile.py`. The ES Scalper profile
reuses Plan 17's MeanReversionStrategy with tighter parameters (shorter
BB, smaller TP via reward_ratio, higher daily trade cap) for a scalper
ethos on ES/MES.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from bot.backtest.sim_client import SimExecutionClient
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.spec import BotSpec
from bot.strategy.mean_reversion import MeanReversionStrategy
from bot.strategy.profiles.es_scalper import ES_SCALPER_DEFAULTS


def _spec(strategy_params: dict[str, Any] | None = None) -> BotSpec:
    return BotSpec(
        name="es_scalper_test",
        enabled=True,
        symbol="MES",
        strategy_id="mean_reversion_bb",
        strategy_params=strategy_params or {"symbol": "MES"},
        risk_policy="efa_standard",
        risk_params={"mll_amount": 2_000},
        schedule_type="market_hours",
        schedule_params={"open_ct": "08:30", "close_ct": "14:45"},
        journal_path=Path("state/journal_es_scalper_test.db"),
    )


def test_defaults_match_plan_schema() -> None:
    """ES_SCALPER_DEFAULTS must mirror the BotSpec YAML schema (Plan 18 T1)."""
    assert ES_SCALPER_DEFAULTS["bb_period"] == 10
    assert ES_SCALPER_DEFAULTS["bb_stddev"] == 1.5
    assert ES_SCALPER_DEFAULTS["rsi_period"] == 9
    assert ES_SCALPER_DEFAULTS["rsi_oversold"] == 35.0
    assert ES_SCALPER_DEFAULTS["rsi_overbought"] == 65.0
    assert ES_SCALPER_DEFAULTS["reward_ratio"] == 0.75
    assert ES_SCALPER_DEFAULTS["max_trades_per_day"] == 10
    assert ES_SCALPER_DEFAULTS["symbol"] == "MES"


def test_defaults_construct_mean_reversion_strategy() -> None:
    """Defaults are valid kwargs for MeanReversionStrategy."""
    strat = MeanReversionStrategy(**ES_SCALPER_DEFAULTS)
    assert isinstance(strat, MeanReversionStrategy)
    assert strat.symbol == "MES"


def test_registry_resolves_mean_reversion_bb_with_es_defaults() -> None:
    """Built-in 'mean_reversion_bb' factory yields a MeanReversionStrategy
    when fed ES_SCALPER_DEFAULTS."""
    reg = BotRegistry()
    resolved = reg.build(_spec(dict(ES_SCALPER_DEFAULTS)), broker=SimExecutionClient())
    assert isinstance(resolved.strategy, MeanReversionStrategy)
    assert resolved.strategy.symbol == "MES"
