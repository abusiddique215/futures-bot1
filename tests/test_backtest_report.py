"""TradeReport summary statistics (PnL, drawdown, win rate, profit factor).

TradeReport is tested in isolation by hand-synthesizing TradeLog instances —
no engine, no parquet, no gate. The engine end-to-end test covers integration.

Round-trip definition: a sequence of approved fills on a single symbol that
takes the running position from flat back to flat. The PnL of a round-trip is
the sum of signed_qty * exit_price (counter-signed against entries) priced at
$POINT_VALUE per point — for MNQ, $2/pt; for NQ, $20/pt. Tests use MNQ so
1 pt = $2/contract.
"""
from __future__ import annotations

from datetime import UTC, datetime

from bot.backtest.engine import TradeLog
from bot.types import (
    AccountState,
    OrderEvent,
    OrderIntent,
)


def _state(
    *,
    equity: float = 50_000.0,
    realized: float = 0.0,
    high_water: float = 50_000.0,
) -> AccountState:
    return AccountState(
        equity=equity,
        realized_pnl_today=realized,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=high_water,
        is_combine=True,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _intent(
    side: str, qty: int, coid: str, ts: datetime, symbol: str = "MNQ",
) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=qty,
        order_type="MARKET",
        client_order_id=coid,
        timestamp=ts,
    )


def _event(coid: str, qty: int, price: float, ts: datetime) -> OrderEvent:
    return OrderEvent(
        client_order_id=coid,
        broker_order_id=f"sim-{coid}",
        status="FILLED",
        filled_quantity=qty,
        avg_fill_price=price,
        timestamp=ts,
    )


def _pair(
    side: str, qty: int, coid: str, price: float, t_min: int,
) -> tuple[OrderIntent, OrderEvent]:
    ts = datetime(2026, 1, 1, 14, t_min, tzinfo=UTC)
    return _intent(side, qty, coid, ts), _event(coid, qty, price, ts)


def test_empty_trade_log_metrics_are_zero() -> None:
    from bot.backtest.report import TradeReport
    log = TradeLog(final_state=_state())
    rpt = TradeReport.from_trade_log(log)
    assert rpt.total_trades == 0
    assert rpt.realized_pnl == 0.0
    assert rpt.max_drawdown_dollars == 0.0
    assert rpt.win_rate == 0.0
    assert rpt.profit_factor == 0.0


def test_one_winner_one_loser_metrics() -> None:
    """Two MNQ round-trips:
        RT1 (winner): BUY 1 @16500 → SELL 1 @16550 = +50 pts * $2 = +$100
        RT2 (loser):  SELL 1 @16550 → BUY 1 @16575 = -25 pts * $2 = -$50
    Expect: total_trades=2 (round-trips), realized=$50, win_rate=0.5,
    profit_factor=100/50=2.0, max_dd >= $50 (drawdown from $50,100 high-water).
    """
    from bot.backtest.report import TradeReport
    approved = [
        _pair("BUY", 1, "rt1-open", 16_500.0, 0),
        _pair("SELL", 1, "rt1-close", 16_550.0, 1),
        _pair("SELL", 1, "rt2-open", 16_550.0, 2),
        _pair("BUY", 1, "rt2-close", 16_575.0, 3),
    ]
    # final realized = +$100 - $50 = +$50
    # peak equity hit $50,100 between trades; final $50,050 → drawdown $50
    log = TradeLog(
        final_state=_state(
            equity=50_050.0, realized=50.0, high_water=50_100.0,
        ),
        intents_approved=4,
        approved_orders=approved,
        fills=[ev for _, ev in approved],
    )
    rpt = TradeReport.from_trade_log(log)
    assert rpt.total_trades == 2
    assert rpt.realized_pnl == 50.0
    assert rpt.win_rate == 0.5
    assert rpt.profit_factor == 2.0
    assert rpt.max_drawdown_dollars >= 50.0


def test_all_winners_profit_factor_is_inf() -> None:
    """Two winning round-trips, zero losers → profit_factor=inf, win_rate=1.0."""
    from bot.backtest.report import TradeReport
    approved = [
        _pair("BUY", 1, "rt1-open", 16_500.0, 0),
        _pair("SELL", 1, "rt1-close", 16_510.0, 1),  # +$20
        _pair("BUY", 1, "rt2-open", 16_510.0, 2),
        _pair("SELL", 1, "rt2-close", 16_530.0, 3),  # +$40
    ]
    log = TradeLog(
        final_state=_state(
            equity=50_060.0, realized=60.0, high_water=50_060.0,
        ),
        intents_approved=4,
        approved_orders=approved,
        fills=[ev for _, ev in approved],
    )
    rpt = TradeReport.from_trade_log(log)
    assert rpt.total_trades == 2
    assert rpt.win_rate == 1.0
    assert rpt.profit_factor == float("inf")
    assert rpt.max_drawdown_dollars == 0.0  # equity == high_water


def test_drawdown_from_high_water_minus_equity() -> None:
    """Drawdown = high_water - equity when equity below high_water; clamped at 0."""
    from bot.backtest.report import TradeReport
    # No round-trips — just check the drawdown clamp logic on the state.
    log_below = TradeLog(
        final_state=_state(
            equity=49_500.0, realized=-500.0, high_water=50_200.0,
        ),
    )
    assert TradeReport.from_trade_log(log_below).max_drawdown_dollars == 700.0
    log_at_hw = TradeLog(
        final_state=_state(
            equity=51_000.0, realized=1_000.0, high_water=51_000.0,
        ),
    )
    assert TradeReport.from_trade_log(log_at_hw).max_drawdown_dollars == 0.0


def test_open_position_does_not_count_as_round_trip() -> None:
    """Fills that don't return to flat are ignored for win_rate / profit_factor."""
    from bot.backtest.report import TradeReport
    approved = [
        _pair("BUY", 1, "open-only", 16_500.0, 0),
    ]
    log = TradeLog(
        final_state=_state(
            equity=50_000.0, realized=0.0, high_water=50_000.0,
        ),
        intents_approved=1,
        approved_orders=approved,
        fills=[ev for _, ev in approved],
    )
    rpt = TradeReport.from_trade_log(log)
    assert rpt.total_trades == 0
    assert rpt.win_rate == 0.0
    assert rpt.profit_factor == 0.0
