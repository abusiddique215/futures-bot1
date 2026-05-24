"""Equity-curve PNG renderer + HTML report renderer."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from bot.proof.metrics import ClosedTrade, compute_report
from bot.proof.render import render_equity_curve, render_html


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


# ---- render_html ------------------------------------------------------------

_HEADLINE_LABELS = (
    "Net Profit", "Max Drawdown", "Total Trades", "% Profitable", "Profit Factor",
)
_SECONDARY_LABELS = (
    "Avg Trade", "Avg Win", "Avg Loss",
    "Avg Holding (min)", "Sharpe (light)",
    "Period Start", "Period End", "Bot",
)


def test_render_html_contains_headline_labels(tmp_path: Path) -> None:
    trades = [
        _trade(100.0, minute=0),
        _trade(-50.0, minute=10),
        _trade(50.0, minute=20),
    ]
    report = compute_report(trades, bot_name="demo_bot")
    out = tmp_path / "report.html"
    result = render_html(report, "equity_curve.png", out)
    assert result == out
    html = out.read_text()
    for label in _HEADLINE_LABELS:
        assert label in html, f"missing headline label: {label}"
    for label in _SECONDARY_LABELS:
        assert label in html, f"missing secondary label: {label}"


def test_render_html_formats_net_profit_with_dollar_and_commas(tmp_path: Path) -> None:
    trades = [_trade(12_345.67, minute=0)]
    report = compute_report(trades, bot_name="demo")
    out = tmp_path / "report.html"
    render_html(report, "equity_curve.png", out)
    html = out.read_text()
    # Expect "$12,345.67" formatting (or "$+12,345.67" / "$-...") visible.
    assert "$12,345.67" in html


def test_render_html_references_equity_png_relative(tmp_path: Path) -> None:
    report = compute_report([_trade(10.0)], bot_name="demo")
    out = tmp_path / "report.html"
    render_html(report, "equity_curve.png", out)
    html = out.read_text()
    assert 'src="equity_curve.png"' in html
    assert "<table" in html
