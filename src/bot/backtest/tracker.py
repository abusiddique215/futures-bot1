"""AccountStateTracker — running AccountState for backtest.

Maintains realized + unrealized P&L across the backtest Bar loop, tracks
high-water equity, and emits an AccountState snapshot for the RiskGate on
every bar.

Point value formula: TICK_VALUES[sym] / MIN_TICK[sym]
  MNQ = $0.50 / 0.25 = $2/pt
  NQ  = $5.00 / 0.25 = $20/pt
"""
from __future__ import annotations

from datetime import datetime
from typing import Final

from bot.constants import MIN_TICK, TICK_VALUES
from bot.types import AccountState, Bar

# Point value: $/tick * ticks/pt.
_POINT_VALUE: Final[dict[str, float]] = {
    sym: TICK_VALUES[sym] / MIN_TICK[sym] for sym in TICK_VALUES
}


class AccountStateTracker:
    """Backtest-time AccountState source. Sync, in-memory, deterministic."""

    def __init__(self, start_balance: float, is_combine: bool) -> None:
        self._start_balance = start_balance
        self._is_combine = is_combine
        self._realized: float = 0.0
        self._unrealized: float = 0.0
        self._positions: dict[str, int] = {}      # symbol -> signed qty
        self._avg_entry: dict[str, float] = {}    # symbol -> avg entry
        self._high_water: float = start_balance
        self._last_bar_close: dict[str, float] = {}

    def record_fill(
        self,
        symbol: str,
        signed_qty: int,
        fill_price: float,
        ts: datetime,
    ) -> None:
        """Apply a completed fill to position state, realizing PnL when closing
        or flipping."""
        current = self._positions.get(symbol, 0)
        if current == 0:
            self._positions[symbol] = signed_qty
            self._avg_entry[symbol] = fill_price
            return
        new_qty = current + signed_qty
        if new_qty == 0 or (current * new_qty < 0):
            # Closing or flipping. Realize on the closed portion.
            closed_signed_qty = (
                min(abs(current), abs(signed_qty)) * (1 if current > 0 else -1)
            )
            self._realize_pnl(symbol, closed_signed_qty, fill_price)
            if new_qty == 0:
                del self._positions[symbol]
                del self._avg_entry[symbol]
            else:  # flip
                self._positions[symbol] = new_qty
                self._avg_entry[symbol] = fill_price
        else:
            # Adding to existing same-side position — weighted avg entry.
            old_avg = self._avg_entry[symbol]
            self._avg_entry[symbol] = (
                (old_avg * abs(current) + fill_price * abs(signed_qty))
                / abs(new_qty)
            )
            self._positions[symbol] = new_qty
        self._recompute_unrealized()

    def _realize_pnl(
        self, symbol: str, closed_signed_qty: int, exit_price: float,
    ) -> None:
        entry = self._avg_entry[symbol]
        pnl = (exit_price - entry) * closed_signed_qty * _POINT_VALUE[symbol]
        self._realized += pnl

    def mark_to_market(self, bar: Bar) -> None:
        """Update unrealized P&L from the latest bar close for any open position
        in this symbol."""
        self._last_bar_close[bar.symbol] = bar.close
        self._recompute_unrealized()

    def _recompute_unrealized(self) -> None:
        total = 0.0
        for sym, qty in self._positions.items():
            if sym not in self._last_bar_close:
                continue
            mark = self._last_bar_close[sym]
            entry = self._avg_entry[sym]
            total += (mark - entry) * qty * _POINT_VALUE[sym]
        self._unrealized = total
        equity = self._start_balance + self._realized + self._unrealized
        if equity > self._high_water:
            self._high_water = equity

    @property
    def high_water_equity(self) -> float:
        """Exposed so the engine can keep tracker as the source of truth for
        high-water across bars."""
        return self._high_water

    def snapshot(self, timestamp: datetime) -> AccountState:
        equity = self._start_balance + self._realized + self._unrealized
        return AccountState(
            equity=equity,
            realized_pnl_today=self._realized,
            unrealized_pnl=self._unrealized,
            open_positions=dict(self._positions),
            pending_intent_count=0,
            high_water_equity=self._high_water,
            is_combine=self._is_combine,
            timestamp=timestamp,
            start_balance=self._start_balance,
        )
