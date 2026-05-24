"""propbot_nq.yml — Plan 16 BotSpec round-trip + ResolvedBot wiring."""
from __future__ import annotations

from datetime import time
from pathlib import Path

from bot.backtest.sim_client import SimExecutionClient
from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.schedule import MarketHours
from bot.runtime.fleet.spec import load_bot_specs
from bot.strategy.trend_following import TrendFollowingStrategy

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BOTS_DIR = _REPO_ROOT / "config" / "bots"


def test_propbot_yaml_parses() -> None:
    specs = load_bot_specs(_BOTS_DIR)
    propbot = next((s for s in specs if s.name == "propbot_nq"), None)
    assert propbot is not None
    assert propbot.enabled is True
    assert propbot.symbol == "MNQH26"
    assert propbot.strategy_id == "trend_ema_pullback"
    assert propbot.risk_policy == "efa_standard"
    assert propbot.risk_params == {"mll_amount": 2000}
    assert propbot.schedule_type == "market_hours"
    assert propbot.schedule_params == {"open_ct": "09:00", "close_ct": "14:30"}
    assert propbot.journal_path == Path("state/journal_propbot_nq.db")


def test_propbot_strategy_params_include_symbol_match() -> None:
    """Strategy emits intents tagged with this symbol; must match BotSpec.symbol
    so the gate (bound to spec.symbol) accepts them as same-contract."""
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "propbot_nq")
    assert spec.strategy_params["symbol"] == spec.symbol


def test_propbot_resolves_through_registry() -> None:
    spec = next(s for s in load_bot_specs(_BOTS_DIR) if s.name == "propbot_nq")
    reg = BotRegistry()
    resolved = reg.build(spec, broker=SimExecutionClient())
    assert isinstance(resolved.strategy, TrendFollowingStrategy)
    assert isinstance(resolved.schedule, MarketHours)
    assert isinstance(resolved.risk_gate.policy, EFAStandardEoDDrawdown)
    # session_end_ct comes from YAML "14:30" — coerced to datetime.time.
    assert resolved.strategy._session_end_ct == time(14, 30)  # type: ignore[attr-defined]
    # Schedule mirrors the same cutoff.
    assert resolved.schedule.open_ct == time(9, 0)
    assert resolved.schedule.close_ct == time(14, 30)
    # Gate is bound to the contract-form symbol so force_flatten_now hits the
    # right market (Plan 14 gate-symbol hotfix regression check).
    assert resolved.risk_gate.symbol == "MNQH26"
