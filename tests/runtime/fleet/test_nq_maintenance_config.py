"""nq_maintenance.yml — Plan 20 BotSpec round-trip + LiveOnlyGuard interaction.

Mirrors `test_propbot_config.py` + adds assertions that:
  * The shipped YAML resolves cleanly through the registry (no guard trip).
  * Swapping to `combine_intraday` trips `IncompatibleBotSpecError`.
  * The AlwaysOn schedule admits bars at every probed hour.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
from bot.runtime.fleet.live_only_guard import IncompatibleBotSpecError
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.schedule import AlwaysOn
from bot.runtime.fleet.spec import BotSpec, load_bot_specs
from bot.strategy.mean_reversion import MeanReversionStrategy

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BOTS_DIR = _REPO_ROOT / "config" / "bots"


def _nq_spec() -> BotSpec:
    return next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "nq_maintenance")


def test_yaml_parses_with_expected_fields() -> None:
    spec = _nq_spec()
    assert spec.enabled is False  # ships disabled
    assert spec.symbol == "MNQH26"
    assert spec.strategy_id == "mean_reversion_bb"
    assert spec.risk_policy == "efa_standard"
    assert spec.risk_params == {"mll_amount": 2000}
    assert spec.schedule_type == "always"
    assert spec.schedule_params == {}
    assert spec.journal_path == Path("state/journal_nq_maintenance.db")


def test_strategy_params_match_profile_defaults() -> None:
    """YAML strategy_params should mirror NQ_MAINTENANCE_DEFAULTS exactly
    on the wire-format keys (quantity isn't surfaced — defaults to 1)."""
    from bot.strategy.profiles.nq_maintenance import NQ_MAINTENANCE_DEFAULTS

    p = _nq_spec().strategy_params
    for key in (
        "bb_period", "bb_stddev", "rsi_period",
        "rsi_oversold", "rsi_overbought", "reward_ratio",
        "max_trades_per_day", "symbol",
    ):
        assert p[key] == NQ_MAINTENANCE_DEFAULTS[key], f"{key} mismatch"


def test_strategy_symbol_matches_spec_symbol() -> None:
    """Gate is bound to spec.symbol; strategy emits intents with
    strategy_params.symbol. They must agree or the gate rejects them."""
    spec = _nq_spec()
    assert spec.strategy_params["symbol"] == spec.symbol


def test_resolves_through_registry() -> None:
    spec = _nq_spec()
    resolved = BotRegistry().build(spec, broker=SimExecutionClient())
    assert isinstance(resolved.strategy, MeanReversionStrategy)
    assert isinstance(resolved.schedule, AlwaysOn)
    assert isinstance(resolved.risk_gate.policy, EFAStandardEoDDrawdown)
    # Gate is bound to the contract-form symbol (Plan 14 hotfix regression).
    assert resolved.risk_gate.symbol == "MNQH26"


def test_swapping_to_combine_intraday_raises_at_build() -> None:
    """Demonstrates the LiveOnlyGuard's user-facing failure mode."""
    spec = _nq_spec()
    misconfigured = BotSpec(**{**spec.__dict__, "risk_policy": "combine_intraday"})
    with pytest.raises(IncompatibleBotSpecError, match="15:10 CT"):
        BotRegistry().build(misconfigured, broker=SimExecutionClient())


def test_always_schedule_admits_every_hour() -> None:
    """AlwaysOn returns True at midnight, noon, market-close, and off-hours."""
    sched = BotRegistry().build(_nq_spec(), broker=SimExecutionClient()).schedule
    for hour in (0, 6, 12, 15, 18, 23):
        ts = datetime(2026, 5, 22, hour, 30, tzinfo=UTC)
        assert sched.should_trade(ts) is True
