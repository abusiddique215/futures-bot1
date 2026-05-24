"""StrategyReport metrics — compute_report over a list[ClosedTrade]."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bot.proof.metrics import ClosedTrade, StrategyReport, compute_report


def _trade(
    pnl: float,
    *,
    minute: int = 0,
    hold_min: int = 5,
    side: str = "BUY",
    qty: int = 1,
    entry_price: float = 16_500.0,
    exit_price: float | None = None,
) -> ClosedTrade:
    entry_ts = datetime(2026, 1, 1, 14, minute, tzinfo=UTC)
    exit_ts = entry_ts + timedelta(minutes=hold_min)
    return ClosedTrade(
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        side=side,  # type: ignore[arg-type]
        entry_price=entry_price,
        exit_price=exit_price if exit_price is not None else entry_price,
        qty=qty,
        pnl=pnl,
    )


def test_empty_trades_yields_zeroed_report() -> None:
    rpt = compute_report([], bot_name="demo")
    assert isinstance(rpt, StrategyReport)
    assert rpt.bot_name == "demo"
    assert rpt.net_profit == 0.0
    assert rpt.max_drawdown == 0.0
    assert rpt.total_trades == 0
    assert rpt.pct_profitable == 0.0
    assert rpt.profit_factor == 0.0
    assert rpt.avg_trade_pnl == 0.0
    assert rpt.avg_win == 0.0
    assert rpt.avg_loss == 0.0
    assert rpt.avg_holding_minutes == 0.0
    assert rpt.sharpe_light == 0.0


def test_single_winning_trade() -> None:
    rpt = compute_report([_trade(100.0, minute=0, hold_min=10)], bot_name="demo")
    assert rpt.total_trades == 1
    assert rpt.net_profit == 100.0
    assert rpt.pct_profitable == 1.0
    assert rpt.profit_factor == 0.0  # no losers → 0 (no div-by-zero)
    assert rpt.avg_trade_pnl == 100.0
    assert rpt.avg_win == 100.0
    assert rpt.avg_loss == 0.0
    assert rpt.avg_holding_minutes == 10.0
    assert rpt.max_drawdown == 0.0
    assert rpt.period_start == datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
    assert rpt.period_end == datetime(2026, 1, 1, 14, 10, tzinfo=UTC)


def test_mixed_wins_losses_metrics() -> None:
    trades = [
        _trade(100.0, minute=0, hold_min=5),
        _trade(-50.0, minute=10, hold_min=3),
        _trade(50.0, minute=20, hold_min=7),
        _trade(-25.0, minute=30, hold_min=5),
    ]
    rpt = compute_report(trades, bot_name="demo")
    assert rpt.total_trades == 4
    assert rpt.net_profit == 75.0
    assert rpt.pct_profitable == 0.5  # 2 / 4
    # sum(wins) = 150, sum(losses) = 75 → PF = 2.0
    assert rpt.profit_factor == 2.0
    assert rpt.avg_trade_pnl == 75.0 / 4
    assert rpt.avg_win == 75.0  # (100 + 50) / 2
    assert rpt.avg_loss == 37.5  # (50 + 25) / 2 — magnitudes
    assert rpt.avg_holding_minutes == 5.0  # (5+3+7+5)/4


def test_max_drawdown_peak_to_trough_on_equity_curve() -> None:
    """Equity walks 100 → 110 → 105 → 95 → 100; max DD = 110-95 = 15.

    Starting from 100 cumulative PnL means: trades = +10, -5, -10, +5.
    """
    trades = [
        _trade(100.0, minute=0, hold_min=1),  # equity 100
        _trade(10.0, minute=5, hold_min=1),   # equity 110 (peak)
        _trade(-5.0, minute=10, hold_min=1),  # equity 105
        _trade(-10.0, minute=15, hold_min=1), # equity 95 (trough)
        _trade(5.0, minute=20, hold_min=1),   # equity 100
    ]
    rpt = compute_report(trades, bot_name="demo")
    assert rpt.max_drawdown == 15.0


def test_all_losing_trades_profit_factor_zero() -> None:
    trades = [_trade(-10.0, minute=0), _trade(-20.0, minute=5)]
    rpt = compute_report(trades, bot_name="demo")
    assert rpt.total_trades == 2
    assert rpt.net_profit == -30.0
    assert rpt.pct_profitable == 0.0
    assert rpt.profit_factor == 0.0  # no winners → no div-by-zero
    assert rpt.avg_win == 0.0
    assert rpt.avg_loss == 15.0
