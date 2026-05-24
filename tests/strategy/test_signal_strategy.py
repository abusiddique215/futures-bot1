"""SignalStrategy — consumes a SignalSource → emits OrderIntents. T5.

The strategy holds an internal deque populated by a background pump task
that reads `SignalSource.iter_signals()`. The synchronous `on_bar` drains
up to `max_signals_per_bar` matching events per bar and converts each
into an OrderIntent. Tests use the sync `inject()` seam so we don't need
to wire up the pump task — the contract under test is the bar-time drain
+ symbol-match + intent-shape logic, not the asyncio plumbing (which the
FixtureSignalSource integration test covers end-to-end).
"""
from __future__ import annotations

from datetime import UTC, datetime

from bot.signals.source import SignalEvent
from bot.strategy.signal_strategy import SignalStrategy
from bot.types import AccountState, Bar


def _bar(ts: datetime | None = None) -> Bar:
    return Bar(
        symbol="MNQ", open=20_100.0, high=20_100.0,
        low=20_100.0, close=20_100.0, volume=100,
        timestamp=ts or datetime(2026, 5, 24, 14, 30, tzinfo=UTC),
        interval="10m",
    )


def _state(ts: datetime | None = None) -> AccountState:
    return AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=False,
        timestamp=ts or datetime(2026, 5, 24, 14, 30, tzinfo=UTC),
    )


def _event(
    *, symbol: str = "MNQ", side: str = "BUY", qty: int = 1,
    limit_price: float | None = 20_100.0,
    stop_loss: float | None = 20_070.0,
    take_profit: float | None = 20_160.0,
    source_id: str = "msg-1",
) -> SignalEvent:
    return SignalEvent(
        received_at=datetime(2026, 5, 24, 14, 29, tzinfo=UTC),
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        qty=qty,
        limit_price=limit_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        raw_text=f"{side} {symbol} @{limit_price} SL={stop_loss} TP={take_profit}",
        source_id=source_id,
    )


def test_no_signals_no_intents():
    strat = SignalStrategy(symbol="MNQ")
    intents = list(strat.on_bar(_bar(), _state()))
    assert intents == []


def test_one_signal_yields_one_intent():
    strat = SignalStrategy(symbol="MNQ")
    strat.inject(_event())
    intents = list(strat.on_bar(_bar(), _state()))
    assert len(intents) == 1
    ix = intents[0]
    assert ix.symbol == "MNQ"
    assert ix.side == "BUY"
    assert ix.quantity == 1
    assert ix.order_type == "LIMIT"
    assert ix.limit_price == 20_100.0
    assert ix.bracket is not None
    # stop distance = 20100 - 20070 = 30 points / 0.25 tick = 120 ticks
    assert ix.bracket.stop_loss_ticks == 120
    # tp distance = 20160 - 20100 = 60 points / 0.25 = 240 ticks
    assert ix.bracket.take_profit_ticks == 240


def test_signal_without_limit_price_emits_market():
    strat = SignalStrategy(symbol="MNQ")
    strat.inject(_event(limit_price=None, stop_loss=None, take_profit=None))
    intents = list(strat.on_bar(_bar(), _state()))
    assert len(intents) == 1
    assert intents[0].order_type == "MARKET"
    assert intents[0].limit_price is None
    assert intents[0].bracket is None


def test_signal_with_only_stop_no_tp_uses_one_to_one():
    """If TP missing, still emit a bracket — TP defaults to same distance as SL."""
    strat = SignalStrategy(symbol="MNQ")
    strat.inject(_event(take_profit=None))
    intents = list(strat.on_bar(_bar(), _state()))
    assert len(intents) == 1
    assert intents[0].bracket is not None
    # Default tp = sl distance: 120 ticks both ways
    assert intents[0].bracket.stop_loss_ticks == 120
    assert intents[0].bracket.take_profit_ticks == 120


def test_five_signals_one_per_bar_default():
    """Default cap = 1 per bar. 4 retained for subsequent bars."""
    strat = SignalStrategy(symbol="MNQ", max_signals_per_bar=1)
    for i in range(5):
        strat.inject(_event(source_id=f"msg-{i}"))

    out1 = list(strat.on_bar(_bar(), _state()))
    assert len(out1) == 1
    assert strat.pending_count() == 4

    out2 = list(strat.on_bar(_bar(), _state()))
    assert len(out2) == 1
    assert strat.pending_count() == 3


def test_max_signals_per_bar_cap_respected():
    strat = SignalStrategy(symbol="MNQ", max_signals_per_bar=3)
    for i in range(5):
        strat.inject(_event(source_id=f"msg-{i}"))
    out = list(strat.on_bar(_bar(), _state()))
    assert len(out) == 3
    assert strat.pending_count() == 2


def test_wrong_symbol_skipped():
    """Signal for ES while bot watches MNQ → drop event, don't emit."""
    strat = SignalStrategy(symbol="MNQ")
    strat.inject(_event(symbol="ES"))
    out = list(strat.on_bar(_bar(), _state()))
    assert out == []
    assert strat.pending_count() == 0  # dropped, not retained


def test_root_symbol_matches_contract_month():
    """Signal symbol 'NQ' matches bot symbol 'MNQH26' via root prefix."""
    strat = SignalStrategy(symbol="MNQH26")
    strat.inject(_event(symbol="MNQ"))
    out = list(strat.on_bar(_bar(), _state()))
    assert len(out) == 1
    assert out[0].symbol == "MNQH26"


def test_qty_passed_through_verbatim():
    """Strategy does NOT cap qty — risk gate is the single chokepoint.

    Signal claims qty=100 → strategy emits qty=100 → gate denies MAX_POSITION
    downstream. Verified in tests/integration/test_lux_bot_e2e.py.
    """
    strat = SignalStrategy(symbol="MNQ")
    strat.inject(_event(qty=100))
    out = list(strat.on_bar(_bar(), _state()))
    assert len(out) == 1
    assert out[0].quantity == 100


def test_sell_signal_emits_sell_intent():
    strat = SignalStrategy(symbol="MNQ")
    strat.inject(_event(side="SELL", limit_price=20_100.0,
                        stop_loss=20_130.0, take_profit=20_040.0))
    out = list(strat.on_bar(_bar(), _state()))
    assert len(out) == 1
    assert out[0].side == "SELL"
    # SELL: SL is above entry, TP below — stop_distance still = |20130-20100| = 30pt
    assert out[0].bracket is not None
    assert out[0].bracket.stop_loss_ticks == 120
    assert out[0].bracket.take_profit_ticks == 240


def test_client_order_id_traces_signal_source_id():
    """Provenance: the broker order's client_order_id includes the
    signal source_id so the dashboard can trace order → Discord message.
    """
    strat = SignalStrategy(symbol="MNQ")
    strat.inject(_event(source_id="discord-msg-99"))
    out = list(strat.on_bar(_bar(), _state()))
    assert "discord-msg-99" in out[0].client_order_id
