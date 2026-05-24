"""BotRegistry — spec → ResolvedBot resolution."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.risk.efa_drawdown import EFAConsistencyDrawdown, EFAStandardEoDDrawdown
from bot.risk.gate import TopstepRiskGate
from bot.runtime.fleet.registry import BotRegistry, ResolvedBot
from bot.runtime.fleet.schedule import AlwaysOn, CustomWindows, MarketHours
from bot.runtime.fleet.spec import BotSpec
from bot.strategy.orb import OpeningRangeBreakoutStrategy
from bot.types import AccountState, Bar, OrderIntent


def _spec(
    *,
    strategy_id: str = "orb_5m",
    strategy_params: dict[str, Any] | None = None,
    risk_policy: str = "combine_intraday",
    risk_params: dict[str, Any] | None = None,
    schedule_type: str = "always",
    schedule_params: dict[str, Any] | None = None,
    name: str = "alpha",
) -> BotSpec:
    return BotSpec(
        name=name,
        enabled=True,
        symbol="MNQ",
        strategy_id=strategy_id,
        strategy_params=strategy_params or {},
        risk_policy=risk_policy,  # type: ignore[arg-type]
        risk_params=risk_params or {"start_balance": 50_000, "mll_amount": 2_000, "max_mini": 5},
        schedule_type=schedule_type,  # type: ignore[arg-type]
        schedule_params=schedule_params or {},
        journal_path=Path(f"state/journal_{name}.db"),
    )


def _broker() -> Any:
    return SimExecutionClient()


def test_builtin_orb_combine_always_resolves() -> None:
    reg = BotRegistry()
    spec = _spec()
    resolved = reg.build(spec, broker=_broker())
    assert isinstance(resolved, ResolvedBot)
    assert resolved.name == "alpha"
    assert isinstance(resolved.strategy, OpeningRangeBreakoutStrategy)
    assert isinstance(resolved.risk_gate, TopstepRiskGate)
    assert isinstance(resolved.schedule, AlwaysOn)
    assert resolved.journal_path == Path("state/journal_alpha.db")
    assert resolved.spec is spec


def test_market_hours_schedule_resolves() -> None:
    reg = BotRegistry()
    spec = _spec(
        schedule_type="market_hours",
        schedule_params={"open_ct": "08:30", "close_ct": "15:10"},
    )
    resolved = reg.build(spec, broker=_broker())
    assert isinstance(resolved.schedule, MarketHours)


def test_custom_windows_schedule_resolves() -> None:
    reg = BotRegistry()
    spec = _spec(
        schedule_type="custom_windows",
        schedule_params={"windows": [["08:30", "11:30"], ["13:30", "15:00"]]},
    )
    resolved = reg.build(spec, broker=_broker())
    assert isinstance(resolved.schedule, CustomWindows)


def test_efa_standard_policy_resolves() -> None:
    reg = BotRegistry()
    spec = _spec(risk_policy="efa_standard", risk_params={"mll_amount": 2_500})
    resolved = reg.build(spec, broker=_broker())
    assert isinstance(resolved.risk_gate.policy, EFAStandardEoDDrawdown)


def test_efa_consistency_policy_resolves() -> None:
    reg = BotRegistry()
    spec = _spec(risk_policy="efa_consistency", risk_params={"mll_amount": 2_500})
    resolved = reg.build(spec, broker=_broker())
    assert isinstance(resolved.risk_gate.policy, EFAConsistencyDrawdown)


def test_unknown_strategy_id_raises() -> None:
    reg = BotRegistry()
    spec = _spec(strategy_id="not_a_strategy")
    with pytest.raises(KeyError, match="not_a_strategy"):
        reg.build(spec, broker=_broker())


def test_unknown_risk_policy_raises() -> None:
    reg = BotRegistry()
    spec = _spec()
    # mutate to bypass Literal at runtime
    bad = BotSpec(
        **{**spec.__dict__, "risk_policy": "bogus"},  # type: ignore[arg-type]
    )
    with pytest.raises(KeyError, match="bogus"):
        reg.build(bad, broker=_broker())


def test_unknown_schedule_type_raises() -> None:
    reg = BotRegistry()
    spec = _spec()
    bad = BotSpec(**{**spec.__dict__, "schedule_type": "bogus"})  # type: ignore[arg-type]
    with pytest.raises(KeyError, match="bogus"):
        reg.build(bad, broker=_broker())


def test_custom_strategy_registration() -> None:
    reg = BotRegistry()

    class _Stub:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

        def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
            return []

    reg.register_strategy("stub", lambda p: _Stub(**p))
    spec = _spec(strategy_id="stub", strategy_params={"foo": 1})
    resolved = reg.build(spec, broker=_broker())
    assert isinstance(resolved.strategy, _Stub)
    assert resolved.strategy.kw == {"foo": 1}


def test_mean_reversion_bb_resolves_with_gold_defaults() -> None:
    """Verify the registry can resolve a MeanReversionStrategy from a spec.

    Uses GOLD_BOT_DEFAULTS directly so a future change to the defaults flows
    through both the YAML and this resolution test."""
    from bot.strategy.mean_reversion import MeanReversionStrategy
    from bot.strategy.profiles.gold_bot import GOLD_BOT_DEFAULTS

    reg = BotRegistry()
    spec = _spec(
        strategy_id="mean_reversion_bb",
        strategy_params=dict(GOLD_BOT_DEFAULTS),
        risk_policy="efa_standard",
        risk_params={"mll_amount": 2000},
        name="gold",
    )
    resolved = reg.build(spec, broker=_broker())
    assert isinstance(resolved.strategy, MeanReversionStrategy)
    assert resolved.strategy.symbol == "MGCH26"


def test_mean_reversion_bb_overrides_via_params() -> None:
    """Plans 18/20 will pass different params (e.g. ES symbol, tighter
    bb_period) into the same registered strategy."""
    from bot.strategy.mean_reversion import MeanReversionStrategy

    reg = BotRegistry()
    spec = _spec(
        strategy_id="mean_reversion_bb",
        strategy_params={
            "bb_period": 10,
            "bb_stddev": 1.5,
            "rsi_period": 7,
            "rsi_oversold": 25,
            "rsi_overbought": 75,
            "reward_ratio": 0.8,
            "max_trades_per_day": 5,
            "symbol": "MES",
            "quantity": 2,
        },
        risk_policy="efa_standard",
        risk_params={"mll_amount": 2500},
        name="es_scalper_preview",
    )
    resolved = reg.build(spec, broker=_broker())
    assert isinstance(resolved.strategy, MeanReversionStrategy)
    assert resolved.strategy.symbol == "MES"
    assert resolved.strategy.quantity == 2


def test_orb_params_round_trip() -> None:
    reg = BotRegistry()
    spec = _spec(strategy_params={
        "range_minutes": 10, "atr_mult": 1.5, "tp_r_multiple": 3.0, "max_trades_per_day": 2,
    })
    resolved = reg.build(spec, broker=_broker())
    strat = resolved.strategy
    assert isinstance(strat, OpeningRangeBreakoutStrategy)
    # access private profile to confirm wiring
    assert strat._profile.range_minutes == 10  # type: ignore[attr-defined]
    assert strat._profile.atr_mult == 1.5  # type: ignore[attr-defined]
