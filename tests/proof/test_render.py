"""Equity-curve PNG renderer + HTML report renderer."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from bot.proof.metrics import ClosedTrade
from bot.proof.render import render_equity_curve


def _trade(pnl: float, minute: int = 0) -> ClosedTrade:
    entry_ts = datetime(2026, 1, 1, 14, minute, tzinfo=UTC)
    exit_ts = entry_ts + timedelta(minutes=5)
    return ClosedTrade(
        entry_ts=entry_ts, exit_ts=exit_ts, side="BUY",
        entry_price=16_500.0, exit_price=16_510.0, qty=1, pnl=pnl,
    )


# ---- render_equity_curve ----------------------------------------------------

def test_render_equity_curve_writes_nonempty_png(tmp_path: Path) -> None:
    trades = [_trade(10.0 * i, minute=i) for i in range(1, 11)]
    out = tmp_path / "equity.png"
    result = render_equity_curve(trades, "demo", out)
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 5_000  # non-trivial PNG


def test_render_equity_curve_empty_does_not_crash(tmp_path: Path) -> None:
    out = tmp_path / "empty.png"
    result = render_equity_curve([], "demo", out)
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0
