"""TradeReport — summary statistics over a TradeLog.

Metrics:
  total_trades         : count of closed round-trips (per-symbol flat→flat).
  realized_pnl         : final_state.realized_pnl_today (authoritative).
  max_drawdown_dollars : max(0, high_water_equity - equity) on final state.
                         v1 uses the final-state snapshot only; an intra-run
                         peak-to-trough curve is deferred to Plan 5.
  win_rate             : winning_rt / total_rt, 0.0 if no round-trips.
  profit_factor        : sum_winners / abs(sum_losers); inf if no losers and
                         at least one winner; 0.0 if no winners.

Round-trip reconstruction needs the OrderIntent.side (OrderEvent alone lacks it),
so TradeReport reads `log.approved_orders`, not `log.fills`.
"""
from __future__ import annotations

from dataclasses import dataclass

from bot.backtest.engine import TradeLog
from bot.constants import MIN_TICK, TICK_VALUES
from bot.types import OrderEvent, OrderIntent

_POINT_VALUE: dict[str, float] = {
    sym: TICK_VALUES[sym] / MIN_TICK[sym] for sym in TICK_VALUES
}


@dataclass(frozen=True)
class TradeReport:
    """Summary stats over a backtest run."""
    total_trades: int
    realized_pnl: float
    max_drawdown_dollars: float
    win_rate: float
    profit_factor: float

    @classmethod
    def from_trade_log(cls, log: TradeLog) -> TradeReport:
        round_trip_pnls = _round_trip_pnls(log.approved_orders)
        winners = [p for p in round_trip_pnls if p > 0]
        losers = [p for p in round_trip_pnls if p < 0]
        total = len(round_trip_pnls)

        win_rate = (len(winners) / total) if total > 0 else 0.0

        if not winners:
            profit_factor = 0.0
        elif not losers:
            profit_factor = float("inf")
        else:
            profit_factor = sum(winners) / abs(sum(losers))

        state = log.final_state
        drawdown = max(0.0, state.high_water_equity - state.equity)

        return cls(
            total_trades=total,
            realized_pnl=state.realized_pnl_today,
            max_drawdown_dollars=drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
        )


def _round_trip_pnls(
    approved_orders: list[tuple[OrderIntent, OrderEvent]],
) -> list[float]:
    """Walk fills per-symbol; each return-to-flat is one round-trip.

    For each round-trip we accumulate cash flow = sum over fills of
    (-signed_qty * fill_price) in price-points (a sell credits cash, a buy
    debits it). Multiply by the symbol's POINT_VALUE to convert price points
    into dollars. A round-trip's dollar P&L is that cash flow once the running
    position returns to 0.
    """
    pnls: list[float] = []
    # symbol -> (running signed qty, accumulated cash flow in price units)
    running: dict[str, tuple[int, float]] = {}
    for intent, event in approved_orders:
        fill_price = event.avg_fill_price
        if fill_price is None:
            continue  # non-fill event; shouldn't happen in approved_orders
        signed = intent.signed_qty()
        qty, cash = running.get(intent.symbol, (0, 0.0))
        new_qty = qty + signed
        new_cash = cash + (-signed * fill_price)
        if new_qty == 0 and qty != 0:
            pnls.append(new_cash * _POINT_VALUE[intent.symbol])
            running.pop(intent.symbol, None)
        else:
            running[intent.symbol] = (new_qty, new_cash)
    return pnls
