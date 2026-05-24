"""TrendFollowingStrategy — EMA-pullback entry + ATR bracket + EoD flat.

Plan 16. PropBot's signal generator. EMA(20)/EMA(50) trend filter; pullback to
fast EMA within 0.5 ATR triggers entry; stop = fast_ema - 1*ATR; TP =
+reward_ratio * stop distance; one trade per Topstep trading day; flat at
session_end_ct.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from bot.strategy.trend_following import TrendFollowingStrategy
from bot.types import AccountState, Bar, OrderIntent

_UTC = UTC
_CT = ZoneInfo("America/Chicago")


def _state(equity: float = 50_000.0, ts: datetime | None = None) -> AccountState:
    return AccountState(
        equity=equity,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=equity,
        is_combine=False,
        timestamp=ts or datetime(2026, 5, 22, 14, 30, tzinfo=_UTC),
    )


def _bar(
    close: float,
    *,
    ts: datetime,
    symbol: str = "MNQ",
    high: float | None = None,
    low: float | None = None,
    open_: float | None = None,
) -> Bar:
    return Bar(
        symbol=symbol,
        open=open_ if open_ is not None else close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=100,
        timestamp=ts,
        interval="1m",
    )


def _ct_bar(
    close: float,
    *,
    ct_clock: time,
    day: tuple[int, int, int] = (2026, 5, 22),
    **kw: float,
) -> Bar:
    """Bar tagged with a CT wall-clock time on a given calendar date."""
    ct_dt = datetime(day[0], day[1], day[2], ct_clock.hour, ct_clock.minute, tzinfo=_CT)
    return _bar(close, ts=ct_dt.astimezone(_UTC), **cast(dict[str, float], kw))


def _drain(it: Iterable[OrderIntent]) -> list[OrderIntent]:
    return list(it)


# ---------------------------------------------------------------------------
# Warm-up helpers
# ---------------------------------------------------------------------------

def _warmup_uptrend(
    strat: TrendFollowingStrategy,
    state: AccountState,
    *,
    start: datetime,
    closes: list[float],
) -> datetime:
    """Feed `closes` as 1-min bars; return the timestamp of the LAST bar fed."""
    last_ts = start
    for i, c in enumerate(closes):
        last_ts = start + timedelta(minutes=i)
        # Make highs/lows tight to closes so ATR is small and predictable.
        bar = _bar(c, ts=last_ts, high=c + 0.5, low=c - 0.5)
        _drain(strat.on_bar(bar, state))
    return last_ts


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_uptrend_pullback_emits_buy() -> None:
    """fast EMA > slow EMA + price pulls back to within 0.5 ATR of fast EMA → BUY."""
    strat = TrendFollowingStrategy(fast_ema=5, slow_ema=10, symbol="MNQ")
    # Session-open bar (09:00 CT) so we're inside the trading day.
    start_ct = datetime(2026, 5, 22, 9, 0, tzinfo=_CT)
    start_utc = start_ct.astimezone(_UTC)
    # Strong, smooth uptrend long enough to seed both EMAs + ATR.
    closes = [18_000.0 + i * 2.0 for i in range(30)]
    last_ts = _warmup_uptrend(strat, _state(), start=start_utc, closes=closes)

    # Pullback bar: price dips back to roughly the fast EMA value.
    # With closes ending near 18_058, fast EMA(5) ≈ mid-58, slow EMA(10) ≈ low-50s.
    # A close at 18_054 is well within 0.5 ATR (ATR ~1.5) of the fast EMA.
    pullback_ts = last_ts + timedelta(minutes=1)
    pullback = _bar(18_054.0, ts=pullback_ts, high=18_058.0, low=18_053.0)
    intents = _drain(strat.on_bar(pullback, _state(ts=pullback_ts)))
    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == "BUY"
    assert intent.symbol == "MNQ"
    assert intent.order_type == "BRACKET"
    assert intent.bracket is not None
    assert intent.bracket.stop_loss_ticks >= 1
    assert intent.bracket.take_profit_ticks >= intent.bracket.stop_loss_ticks


def test_downtrend_pullback_emits_sell() -> None:
    """fast EMA < slow EMA + price pulls back up to fast EMA → SELL."""
    strat = TrendFollowingStrategy(fast_ema=5, slow_ema=10, symbol="MNQ")
    start_ct = datetime(2026, 5, 22, 9, 0, tzinfo=_CT)
    start_utc = start_ct.astimezone(_UTC)
    closes = [18_000.0 - i * 2.0 for i in range(30)]
    last_ts = _warmup_uptrend(strat, _state(), start=start_utc, closes=closes)

    pullback_ts = last_ts + timedelta(minutes=1)
    # Last close ~17_942; fast EMA(5) ≈ ~17_946; price retraces UP to ~17_946.
    pullback = _bar(17_946.0, ts=pullback_ts, high=17_947.0, low=17_942.0)
    intents = _drain(strat.on_bar(pullback, _state(ts=pullback_ts)))
    assert len(intents) == 1
    assert intents[0].side == "SELL"


def test_flat_emas_no_trade() -> None:
    """When EMAs are within 0.1 * ATR of each other (chop) — no entry."""
    strat = TrendFollowingStrategy(fast_ema=5, slow_ema=10, symbol="MNQ")
    start_ct = datetime(2026, 5, 22, 9, 0, tzinfo=_CT)
    start_utc = start_ct.astimezone(_UTC)
    # Tight chop around 18_000.
    closes = [18_000.0 + (1.0 if i % 2 == 0 else -1.0) for i in range(30)]
    last_ts = _warmup_uptrend(strat, _state(), start=start_utc, closes=closes)

    next_ts = last_ts + timedelta(minutes=1)
    intents = _drain(strat.on_bar(_bar(18_000.0, ts=next_ts), _state(ts=next_ts)))
    assert intents == []


def test_max_trades_per_day_caps_entries() -> None:
    """Second valid signal in same Topstep trading day is ignored."""
    strat = TrendFollowingStrategy(
        fast_ema=5, slow_ema=10, symbol="MNQ", max_trades_per_day=1,
    )
    start_ct = datetime(2026, 5, 22, 9, 0, tzinfo=_CT)
    start_utc = start_ct.astimezone(_UTC)
    closes = [18_000.0 + i * 2.0 for i in range(30)]
    last_ts = _warmup_uptrend(strat, _state(), start=start_utc, closes=closes)

    # First pullback → BUY.
    t1 = last_ts + timedelta(minutes=1)
    first = _drain(
        strat.on_bar(_bar(18_054.0, ts=t1, high=18_058.0, low=18_053.0), _state(ts=t1)),
    )
    assert len(first) == 1
    assert first[0].side == "BUY"

    # Close the position quickly with a TP-hit bar.
    tp = first[0].bracket
    assert tp is not None
    # Force a huge upside bar that ought to trigger TP exit.
    t2 = t1 + timedelta(minutes=1)
    exit_intents = _drain(
        strat.on_bar(
            _bar(20_000.0, ts=t2, high=20_000.0, low=18_054.0),
            _state(ts=t2),
        ),
    )
    assert len(exit_intents) == 1
    assert exit_intents[0].side == "SELL"

    # Now warm up more uptrend to re-arm the pullback condition.
    t3 = t2 + timedelta(minutes=1)
    last2 = _warmup_uptrend(
        strat, _state(), start=t3,
        closes=[20_000.0 + i * 2.0 for i in range(30)],
    )
    t4 = last2 + timedelta(minutes=1)
    second_pullback = _drain(
        strat.on_bar(
            _bar(20_054.0, ts=t4, high=20_058.0, low=20_053.0),
            _state(ts=t4),
        ),
    )
    assert second_pullback == []  # day-cap reached


def test_eod_flat_closes_open_position() -> None:
    """An open position triggers a MARKET close intent at/after session_end_ct."""
    strat = TrendFollowingStrategy(
        fast_ema=5, slow_ema=10, symbol="MNQ", session_end_ct=time(14, 30),
    )
    start_ct = datetime(2026, 5, 22, 9, 0, tzinfo=_CT)
    start_utc = start_ct.astimezone(_UTC)
    closes = [18_000.0 + i * 2.0 for i in range(30)]
    last_ts = _warmup_uptrend(strat, _state(), start=start_utc, closes=closes)

    t1 = last_ts + timedelta(minutes=1)
    opener = _drain(
        strat.on_bar(_bar(18_054.0, ts=t1, high=18_058.0, low=18_053.0), _state(ts=t1)),
    )
    assert len(opener) == 1
    assert opener[0].side == "BUY"

    # Cutoff bar at 14:30 CT.
    cutoff_ct = datetime(2026, 5, 22, 14, 30, tzinfo=_CT)
    cutoff_utc = cutoff_ct.astimezone(_UTC)
    closes_intent = _drain(
        strat.on_bar(_bar(18_060.0, ts=cutoff_utc), _state(ts=cutoff_utc)),
    )
    assert len(closes_intent) == 1
    assert closes_intent[0].side == "SELL"
    assert closes_intent[0].order_type == "MARKET"


def test_atr_computation_matches_orb_method() -> None:
    """ATR(14) = average of last 14 True Ranges. Verified by feeding 15 known bars
    + checking that the strategy's internal ATR matches the reference computation.
    """
    strat = TrendFollowingStrategy(fast_ema=3, slow_ema=5, atr_period=14, symbol="MNQ")
    start_ct = datetime(2026, 5, 22, 9, 0, tzinfo=_CT)
    start_utc = start_ct.astimezone(_UTC)
    closes = [18_000.0 + i * 1.0 for i in range(15)]
    # Build bars with predictable high/low offsets (high=close+1, low=close-1).
    bars: list[Bar] = []
    for i, c in enumerate(closes):
        bars.append(_bar(c, ts=start_utc + timedelta(minutes=i), high=c + 1.0, low=c - 1.0))

    for b in bars:
        _drain(strat.on_bar(b, _state()))

    # Reference ATR: 14 TRs from bars[1..14]. Each TR = max(h-l, |h-prev_close|, |l-prev_close|).
    trs: list[float] = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        h, low = bars[i].high, bars[i].low
        trs.append(max(h - low, abs(h - prev_close), abs(low - prev_close)))
    expected = sum(trs[-14:]) / 14
    # Access internal for verification (parity check, not public API).
    assert strat._atr is not None  # type: ignore[attr-defined]
    assert strat._atr == pytest.approx(expected, abs=1e-9)  # type: ignore[attr-defined]


def test_state_is_unused_strategy_is_state_aware_only_through_bar() -> None:
    """Sanity: passing different AccountState equity values changes nothing
    (strategy doesn't consult equity)."""
    strat = TrendFollowingStrategy(fast_ema=5, slow_ema=10, symbol="MNQ")
    start_ct = datetime(2026, 5, 22, 9, 0, tzinfo=_CT)
    start_utc = start_ct.astimezone(_UTC)
    closes = [18_000.0 + i * 2.0 for i in range(30)]
    last_ts = _warmup_uptrend(strat, _state(), start=start_utc, closes=closes)
    t1 = last_ts + timedelta(minutes=1)
    bar = _bar(18_054.0, ts=t1, high=18_058.0, low=18_053.0)
    s1 = _state(equity=50_000.0, ts=t1)
    intents = _drain(strat.on_bar(bar, replace(s1, equity=99_999.0)))
    assert len(intents) == 1
