"""AccountStateTracker (backtest-time AccountState builder)."""
from __future__ import annotations

from datetime import UTC, datetime

from bot.types import Bar


def _bar(close: float, ts: datetime | None = None) -> Bar:
    return Bar(
        symbol="MNQ", open=close, high=close, low=close, close=close,
        volume=100,
        timestamp=ts or datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
        interval="1m",
    )


def test_tracker_initial_state_at_start_balance() -> None:
    from bot.backtest.tracker import AccountStateTracker
    t = AccountStateTracker(start_balance=50_000, is_combine=True)
    state = t.snapshot(timestamp=datetime(2026, 1, 1, tzinfo=UTC))
    assert state.equity == 50_000
    assert state.open_positions == {}
    assert state.high_water_equity == 50_000
    assert state.realized_pnl_today == 0.0
    assert state.unrealized_pnl == 0.0


def test_tracker_records_filled_order_opens_position() -> None:
    """A filled BUY 2 MNQ at 16500 opens a long position of 2."""
    from bot.backtest.tracker import AccountStateTracker
    t = AccountStateTracker(start_balance=50_000, is_combine=True)
    t.record_fill(symbol="MNQ", signed_qty=2, fill_price=16_500.0,
                  ts=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    state = t.snapshot(timestamp=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    assert state.open_positions == {"MNQ": 2}


def test_tracker_unrealized_pnl_from_current_bar_close() -> None:
    """Long 2 MNQ at 16500; current close 16510 -> 10 pts * 2 contracts * $2 = $40."""
    from bot.backtest.tracker import AccountStateTracker
    t = AccountStateTracker(start_balance=50_000, is_combine=True)
    t.record_fill(symbol="MNQ", signed_qty=2, fill_price=16_500.0,
                  ts=datetime(2026, 1, 1, tzinfo=UTC))
    t.mark_to_market(bar=_bar(close=16_510.0))
    state = t.snapshot(timestamp=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    assert state.unrealized_pnl == 40.0  # 10 pts * 2 * $2/pt
    assert state.equity == 50_040.0


def test_tracker_closing_position_realizes_pnl() -> None:
    from bot.backtest.tracker import AccountStateTracker
    t = AccountStateTracker(start_balance=50_000, is_combine=True)
    t.record_fill(symbol="MNQ", signed_qty=2, fill_price=16_500.0,
                  ts=datetime(2026, 1, 1, 14, 0, tzinfo=UTC))
    t.record_fill(symbol="MNQ", signed_qty=-2, fill_price=16_520.0,
                  ts=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    state = t.snapshot(timestamp=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    assert state.open_positions == {}
    assert state.realized_pnl_today == 80.0  # 20 pts * 2 * $2/pt
    assert state.unrealized_pnl == 0.0


def test_tracker_flip_realizes_closed_portion_and_opens_new_side() -> None:
    """Long 2 MNQ at 16500, SELL 3 at 16510. Closes 2 long (+$40),
    opens 1 short at 16510."""
    from bot.backtest.tracker import AccountStateTracker
    t = AccountStateTracker(start_balance=50_000, is_combine=True)
    t.record_fill(symbol="MNQ", signed_qty=2, fill_price=16_500.0,
                  ts=datetime(2026, 1, 1, 14, 0, tzinfo=UTC))
    t.record_fill(symbol="MNQ", signed_qty=-3, fill_price=16_510.0,
                  ts=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    state = t.snapshot(timestamp=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    assert state.open_positions == {"MNQ": -1}
    # Realized: 2 long closed at +10 pts * $2/pt * 2 = $40
    assert state.realized_pnl_today == 40.0


def test_tracker_high_water_advances_with_equity_but_not_drawdown() -> None:
    from bot.backtest.tracker import AccountStateTracker
    t = AccountStateTracker(start_balance=50_000, is_combine=True)
    t.record_fill(symbol="MNQ", signed_qty=1, fill_price=16_500.0,
                  ts=datetime(2026, 1, 1, tzinfo=UTC))
    # Move up: equity rises -> high_water advances
    t.mark_to_market(bar=_bar(close=16_550.0))
    s1 = t.snapshot(timestamp=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    assert s1.high_water_equity == 50_100.0  # 50 pts * $2 * 1
    # Move down: equity drops -> high_water stays
    t.mark_to_market(bar=_bar(close=16_510.0))
    s2 = t.snapshot(timestamp=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    assert s2.high_water_equity == 50_100.0
    assert s2.equity == 50_020.0
