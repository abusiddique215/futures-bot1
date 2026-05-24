"""StrategyReport dataclass + compute_report over closed trades.

The 5 headline metric labels mirror TradingView's Strategy Report shape from
the VSL ("Net Profit", "Max Drawdown", "Total Trades", "% Profitable",
"Profit Factor"). Secondary metrics (avg trade, avg win, avg loss, avg
holding minutes, sharpe-light) round out the surface.

ClosedTrade is the universal intermediate format both source adapters
(JournalSource, BacktestLogSource) produce — `pnl` is pre-computed in
dollars by the adapter so this module stays free of point-value math.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from bot.types import Side

_EPOCH: Final[datetime] = datetime.fromtimestamp(0, tz=UTC)


@dataclass(frozen=True)
class ClosedTrade:
    """One round-trip (flat → flat) with realized P&L in dollars."""
    entry_ts: datetime
    exit_ts: datetime
    side: Side                # direction of the opening leg
    entry_price: float
    exit_price: float
    qty: int                  # absolute contract count
    pnl: float                # dollars, signed


@dataclass(frozen=True)
class StrategyReport:
    """Per-bot proof-surface summary. The 5 headline metrics match the VSL."""
    bot_name: str
    period_start: datetime
    period_end: datetime
    # Headline (TradingView labels, verbatim)
    net_profit: float
    max_drawdown: float
    total_trades: int
    pct_profitable: float     # 0.0 - 1.0
    profit_factor: float      # sum(wins) / sum(abs(losses))
    # Secondary
    avg_trade_pnl: float
    avg_win: float
    avg_loss: float           # magnitude (positive)
    avg_holding_minutes: float
    sharpe_light: float       # mean/stdev of per-trade P&L; 0 if <2 trades


def compute_report(trades: list[ClosedTrade], bot_name: str) -> StrategyReport:
    """Reduce a list of closed trades into a StrategyReport."""
    if not trades:
        return StrategyReport(
            bot_name=bot_name,
            period_start=_EPOCH,
            period_end=_EPOCH,
            net_profit=0.0,
            max_drawdown=0.0,
            total_trades=0,
            pct_profitable=0.0,
            profit_factor=0.0,
            avg_trade_pnl=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            avg_holding_minutes=0.0,
            sharpe_light=0.0,
        )

    pnls = [t.pnl for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    total = len(trades)

    net_profit = sum(pnls)
    pct_profitable = len(winners) / total

    if winners and losers:
        profit_factor = sum(winners) / abs(sum(losers))
    else:
        profit_factor = 0.0  # all-winners or all-losers → 0 (no div-by-zero)

    avg_trade_pnl = net_profit / total
    avg_win = (sum(winners) / len(winners)) if winners else 0.0
    avg_loss = (abs(sum(losers)) / len(losers)) if losers else 0.0
    avg_holding_minutes = sum(
        (t.exit_ts - t.entry_ts).total_seconds() / 60.0 for t in trades
    ) / total

    sharpe_light = 0.0
    if len(pnls) >= 2:
        stdev = statistics.pstdev(pnls)
        if stdev > 0.0:
            sharpe_light = statistics.mean(pnls) / stdev

    return StrategyReport(
        bot_name=bot_name,
        period_start=trades[0].entry_ts,
        period_end=trades[-1].exit_ts,
        net_profit=net_profit,
        max_drawdown=_max_drawdown(pnls),
        total_trades=total,
        pct_profitable=pct_profitable,
        profit_factor=profit_factor,
        avg_trade_pnl=avg_trade_pnl,
        avg_win=avg_win,
        avg_loss=avg_loss,
        avg_holding_minutes=avg_holding_minutes,
        sharpe_light=sharpe_light,
    )


def _max_drawdown(pnls: list[float]) -> float:
    """Peak-to-trough on the cumulative-PnL curve. Returns a non-negative dollar
    amount."""
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return max_dd
