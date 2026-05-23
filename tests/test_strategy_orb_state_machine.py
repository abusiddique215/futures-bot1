"""OpeningRangeBreakoutStrategy state machine.

Tests use a small ``atr_period`` so ATR warms up before the breakout bar.
"""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bot.strategy.orb import OpeningRangeBreakoutStrategy, ORBProfile
from bot.types import AccountState, Bar, OrderIntent

_ET = ZoneInfo("America/New_York")


def _et(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Build a UTC timestamp corresponding to a wall-clock ET moment."""
    return datetime(year, month, day, hour, minute, tzinfo=_ET).astimezone(UTC)


def _bar(o: float, h: float, lo: float, c: float, ts: datetime) -> Bar:
    return Bar(
        symbol="MNQ", open=o, high=h, low=lo, close=c,
        volume=100, timestamp=ts, interval="1m",
    )


def _state(ts: datetime) -> AccountState:
    return AccountState(
        equity=50_000, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True, timestamp=ts,
    )


def _surge_profile() -> ORBProfile:
    return ORBProfile(
        symbol="MNQ", quantity=2, range_minutes=5, atr_period=3,
        atr_mult=1.0, tp_r_multiple=2.0,
        session_start_et=time(9, 30), max_trades_per_day=2,
    )


def _maintenance_profile() -> ORBProfile:
    return ORBProfile(
        symbol="MNQ", quantity=1, range_minutes=5, atr_period=3,
        atr_mult=0.8, tp_r_multiple=1.5,
        session_start_et=time(9, 30), cutoff_time_et=time(11, 30),
        max_trades_per_day=1,
    )


def test_no_signal_during_range_building() -> None:
    """First 5 ET-9:30 bars build the range; no intent emitted."""
    s = OpeningRangeBreakoutStrategy(_surge_profile())
    start = _et(2026, 5, 22, 9, 30)
    intents: list[OrderIntent] = []
    for i in range(5):
        ts = start + timedelta(minutes=i)
        bar = _bar(16500, 16505, 16500, 16502, ts)
        intents.extend(s.on_bar(bar, _state(ts)))
    assert intents == []


def test_breakout_above_range_emits_buy_with_bracket() -> None:
    s = OpeningRangeBreakoutStrategy(_surge_profile())
    start = _et(2026, 5, 22, 9, 30)
    # 5 range bars: high=16510, low=16500
    for i in range(5):
        ts = start + timedelta(minutes=i)
        s.on_bar(_bar(16500, 16510, 16500, 16505, ts), _state(ts))
    # Bar 5 (9:35 ET) closes above 16510 → BUY signal.
    # OHLC chosen so TR continues to be 10 (h-l=10, |h-prev_c|=10, |l-prev_c|=0).
    ts = start + timedelta(minutes=5)
    bar = _bar(16505, 16515, 16505, 16515, ts)
    intents = list(s.on_bar(bar, _state(ts)))
    assert len(intents) == 1
    intent = intents[0]
    assert intent.symbol == "MNQ"
    assert intent.side == "BUY"
    assert intent.quantity == 2
    assert intent.order_type == "BRACKET"
    assert intent.bracket is not None
    # ATR over last 3 TRs = (10 + 10 + 10) / 3 = 10. mult=1.0. ticks = 10 / 0.25 = 40.
    assert intent.bracket.stop_loss_ticks == 40
    # tp_r = 2.0 → 80 ticks
    assert intent.bracket.take_profit_ticks == 80


def test_breakout_below_range_emits_sell_with_bracket() -> None:
    s = OpeningRangeBreakoutStrategy(_surge_profile())
    start = _et(2026, 5, 22, 9, 30)
    for i in range(5):
        ts = start + timedelta(minutes=i)
        s.on_bar(_bar(16500, 16510, 16500, 16505, ts), _state(ts))
    ts = start + timedelta(minutes=5)
    bar = _bar(16500, 16500, 16490, 16495, ts)
    intents = list(s.on_bar(bar, _state(ts)))
    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == "SELL"
    assert intent.quantity == 2
    assert intent.bracket is not None


def test_max_trades_per_day_blocks_further_signals() -> None:
    """surge max_trades=2 → 3rd breakout suppressed same day."""
    s = OpeningRangeBreakoutStrategy(_surge_profile())
    start = _et(2026, 5, 22, 9, 30)
    for i in range(5):
        ts = start + timedelta(minutes=i)
        s.on_bar(_bar(16500, 16510, 16500, 16505, ts), _state(ts))
    # First breakout consumes trade slot 1.
    ts = start + timedelta(minutes=5)
    intents = list(s.on_bar(_bar(16505, 16515, 16505, 16515, ts), _state(ts)))
    assert len(intents) == 1
    # Force the state to "max trades hit + flat" so the next breakout is gated.
    # We bypass the exit-bar contortions because ATR-tracking would inflate
    # subsequent stop sizes; this is a pure state-machine gate test.
    s._position = None
    s._trades_today = 2
    ts = start + timedelta(minutes=6)
    intents = list(s.on_bar(_bar(16505, 16520, 16505, 16515, ts), _state(ts)))
    assert intents == []


def test_new_day_resets_state() -> None:
    """Two trading days; second day rebuilds range independently."""
    s = OpeningRangeBreakoutStrategy(_surge_profile())
    # Day 1
    start1 = _et(2026, 5, 22, 9, 30)
    for i in range(5):
        ts = start1 + timedelta(minutes=i)
        s.on_bar(_bar(16500, 16510, 16500, 16505, ts), _state(ts))
    # Day 1 breakout
    ts = start1 + timedelta(minutes=5)
    s.on_bar(_bar(16510, 16520, 16510, 16515, ts), _state(ts))
    # Day 2 — range rebuilds. First 5 bars on day 2 should emit no intents.
    start2 = _et(2026, 5, 25, 9, 30)
    intents: list[OrderIntent] = []
    for i in range(5):
        ts = start2 + timedelta(minutes=i)
        intents.extend(s.on_bar(
            _bar(17000, 17005, 17000, 17002, ts), _state(ts),
        ))
    assert intents == []


def test_maintenance_cutoff_blocks_late_signals() -> None:
    """Maintenance profile: no signal after 11:30 ET."""
    s = OpeningRangeBreakoutStrategy(_maintenance_profile())
    # Build range starting at 11:25 ET so range completes at 11:30.
    start = _et(2026, 5, 22, 11, 25)
    for i in range(5):
        ts = start + timedelta(minutes=i)
        s.on_bar(_bar(16500, 16510, 16500, 16505, ts), _state(ts))
    # Bar at 11:30 ET — cutoff_time_et is 11:30. Breakout should be suppressed.
    ts = start + timedelta(minutes=5)
    intents = list(s.on_bar(
        _bar(16510, 16520, 16510, 16515, ts), _state(ts),
    ))
    assert intents == []


def test_open_position_exits_at_take_profit() -> None:
    """After entry, a subsequent bar whose high crosses TP emits a closing SELL."""
    s = OpeningRangeBreakoutStrategy(_surge_profile())
    start = _et(2026, 5, 22, 9, 30)
    for i in range(5):
        ts = start + timedelta(minutes=i)
        s.on_bar(_bar(16500, 16510, 16500, 16505, ts), _state(ts))
    # Entry bar — close=16515 above range_high=16510 (clean TR=10 fixture).
    ts = start + timedelta(minutes=5)
    entry = list(s.on_bar(_bar(16505, 16515, 16505, 16515, ts), _state(ts)))
    assert len(entry) == 1
    assert entry[0].side == "BUY"
    # ATR=10, stop=40 ticks, tp=80 ticks → tp_price = 16515 + 80*0.25 = 16535.
    # Next bar's high reaches 16540 → TP crossed.
    ts = start + timedelta(minutes=6)
    exits = list(s.on_bar(_bar(16515, 16540, 16515, 16538, ts), _state(ts)))
    assert len(exits) == 1
    assert exits[0].side == "SELL"
    assert exits[0].quantity == 2
    # Closing order does NOT carry a bracket (it's the exit).
    assert exits[0].bracket is None
