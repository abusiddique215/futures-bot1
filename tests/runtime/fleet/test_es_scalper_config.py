"""config/bots/es_scalper.yml — Plan 18 BotSpec round-trip + ResolvedBot wiring."""
from __future__ import annotations

from datetime import time
from pathlib import Path

from bot.backtest.sim_client import SimExecutionClient
from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.schedule import MarketHours
from bot.runtime.fleet.spec import load_bot_specs
from bot.strategy.mean_reversion import MeanReversionStrategy

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BOTS_DIR = _REPO_ROOT / "config" / "bots"


def test_es_scalper_yaml_parses() -> None:
    specs = load_bot_specs(_BOTS_DIR)
    es = next((s for s in specs if s.name == "es_scalper"), None)
    assert es is not None
    assert es.enabled is True
    assert es.symbol == "MESH26"
    assert es.strategy_id == "mean_reversion_bb"
    assert es.risk_policy == "efa_standard"
    assert es.risk_params == {"mll_amount": 2000}
    assert es.schedule_type == "market_hours"
    assert es.schedule_params == {"open_ct": "08:30", "close_ct": "14:45"}
    assert es.journal_path == Path("state/journal_es_scalper.db")


def test_es_scalper_strategy_params_symbol_matches_botspec() -> None:
    """Strategy emits intents tagged with this symbol; must match BotSpec.symbol
    so the gate (bound to spec.symbol) accepts them as same-contract."""
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "es_scalper")
    assert spec.strategy_params["symbol"] == spec.symbol


def test_es_scalper_strategy_params_match_profile() -> None:
    """YAML strategy_params mirror ES_SCALPER_DEFAULTS (minus the symbol/quantity
    overrides — symbol is per-contract in YAML)."""
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "es_scalper")
    assert spec.strategy_params["bb_period"] == 10
    assert spec.strategy_params["bb_stddev"] == 1.5
    assert spec.strategy_params["rsi_period"] == 9
    assert spec.strategy_params["rsi_oversold"] == 35.0
    assert spec.strategy_params["rsi_overbought"] == 65.0
    assert spec.strategy_params["reward_ratio"] == 0.75
    assert spec.strategy_params["max_trades_per_day"] == 10


def test_es_scalper_resolves_through_registry() -> None:
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "es_scalper")
    reg = BotRegistry()
    resolved = reg.build(spec, broker=SimExecutionClient())
    assert isinstance(resolved.strategy, MeanReversionStrategy)
    assert isinstance(resolved.schedule, MarketHours)
    assert isinstance(resolved.risk_gate.policy, EFAStandardEoDDrawdown)
    # MarketHours honors the 08:30 - 14:45 CT window.
    assert resolved.schedule.open_ct == time(8, 30)
    assert resolved.schedule.close_ct == time(14, 45)
    # Gate is bound to the contract-form symbol so force_flatten_now hits the
    # right market (Plan 14 gate-symbol hotfix regression check).
    assert resolved.risk_gate.symbol == "MESH26"
