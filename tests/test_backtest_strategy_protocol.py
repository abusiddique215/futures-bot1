"""Strategy Protocol contract."""
from __future__ import annotations

from datetime import UTC, datetime

from bot.types import AccountState, Bar


def test_strategy_protocol_importable() -> None:
    from bot.backtest.strategy import Strategy
    assert Strategy is not None


def test_placeholder_strategy_emits_no_intents_by_default() -> None:
    from bot.backtest.strategy import PlaceholderStrategy
    s = PlaceholderStrategy()
    bar = Bar(symbol="MNQ", open=100.0, high=101.0, low=99.5, close=100.5,
              volume=10, timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
              interval="1m")
    state = AccountState(
        equity=50_000, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=bar.timestamp,
    )
    intents = list(s.on_bar(bar, state))
    assert intents == []


def test_placeholder_strategy_satisfies_protocol() -> None:
    """Structural conformance check via mypy + isinstance."""
    from bot.backtest.strategy import PlaceholderStrategy, Strategy
    s: Strategy = PlaceholderStrategy()
    assert isinstance(s, Strategy)
