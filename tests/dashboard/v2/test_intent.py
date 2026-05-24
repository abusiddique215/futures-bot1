"""Tests for the bot intent extractor (Plan 23 T4).

extract_intent(strategy, current_bar, account_state) -> dict produces a
trader-facing summary of what each strategy type is watching for:

  ORB                 — "Watching for breakout > {high} or < {low} (range: {n}m)"
  TrendFollowing      — "Trend = {bullish|bearish|none}; pullback zone ..."
  MeanReversion       — "BB upper {x} lower {y}; RSI {r}; entry on ..."
  SignalStrategy      — "Waiting on Discord signal from channels {ids}"
  unknown             — fallback "Watching for entry signal"
"""
from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any

from bot.dashboard.v2.intent import extract_intent
from bot.runtime.fleet.schedule import AlwaysOn, CustomWindows, MarketHours
from bot.strategy.mean_reversion import MeanReversionStrategy
from bot.strategy.orb import OpeningRangeBreakoutStrategy, ORBProfile
from bot.strategy.trend_following import TrendFollowingStrategy
from bot.types import Bar


def _bar(close: float = 18_000.0) -> Bar:
    return Bar(
        symbol="MNQH26", open=close, high=close + 1.0, low=close - 1.0,
        close=close, volume=10,
        timestamp=datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
        interval="5m",
    )


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "equity": 50_000.0,
        "open_positions": {},
        "high_water_equity": 50_000.0,
    }
    base.update(overrides)
    return base


# ---------- ORB extractor ---------------------------------------------------

def test_orb_intent_pre_range_complete() -> None:
    """Before the opening range is complete, the bot is gathering the range."""
    strat = OpeningRangeBreakoutStrategy(ORBProfile(symbol="MNQ", range_minutes=5))
    out = extract_intent(strat, _bar(), _state())
    assert isinstance(out, dict)
    assert "watching_for" in out
    assert "range" in out["watching_for"].lower() or "opening" in out["watching_for"].lower()


def test_orb_intent_after_range_complete() -> None:
    """Once the opening range has high+low, the intent reports the breakout levels."""
    strat = OpeningRangeBreakoutStrategy(ORBProfile(symbol="MNQ", range_minutes=5))
    # Force the strategy state machine into "range complete" by setting attrs
    # directly — testing the extractor, not the strategy.
    strat._range_high = 18_045.25
    strat._range_low = 17_988.50
    out = extract_intent(strat, _bar(), _state())
    text = out["watching_for"]
    assert "18045" in text or "18045.25" in text
    assert "17988" in text or "17988.50" in text
    # Day-trader terminology.
    assert "breakout" in text.lower()


def test_orb_intent_returns_trades_remaining() -> None:
    strat = OpeningRangeBreakoutStrategy(
        ORBProfile(symbol="MNQ", range_minutes=5, max_trades_per_day=2),
    )
    out = extract_intent(strat, _bar(), _state())
    assert out["max_trades_remaining"] == 2


# ---------- TrendFollowing extractor ----------------------------------------

def test_trend_following_intent_string() -> None:
    strat = TrendFollowingStrategy(
        fast_ema=20, slow_ema=50, pullback_atr_mult=0.5,
        reward_ratio=2.0, max_trades_per_day=2, symbol="NQH26",
        session_end_ct=time(15, 0),
    )
    out = extract_intent(strat, _bar(), _state())
    text = out["watching_for"]
    assert "trend" in text.lower()


# ---------- MeanReversion extractor -----------------------------------------

def test_mean_reversion_intent_string() -> None:
    strat = MeanReversionStrategy(
        bb_period=20, bb_stddev=2.0, rsi_period=14,
        rsi_oversold=30.0, rsi_overbought=70.0,
        reward_ratio=1.0, max_trades_per_day=3, symbol="MNQH26",
    )
    out = extract_intent(strat, _bar(), _state())
    text = out["watching_for"]
    # MeanReversion summary mentions BB or RSI by name.
    assert "bb" in text.lower() or "rsi" in text.lower()


# ---------- Fallback --------------------------------------------------------

class _UnknownStrategy:
    def on_bar(self, bar: Bar, state: Any) -> list[Any]:
        _ = (bar, state)
        return []


def test_unknown_strategy_fallback() -> None:
    out = extract_intent(_UnknownStrategy(), _bar(), _state())
    assert out["watching_for"] == "Watching for entry signal"


# ---------- Schedule next-window helper -------------------------------------

def test_intent_with_always_on_schedule_no_next_window() -> None:
    strat = OpeningRangeBreakoutStrategy(ORBProfile(symbol="MNQ", range_minutes=5))
    out = extract_intent(
        strat, _bar(), _state(),
        schedule=AlwaysOn(),
        now=datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
    )
    assert out["schedule_open"] is True
    assert out["next_window_opens_in_seconds"] is None


def test_intent_market_hours_inside_window() -> None:
    """14:00 UTC = 09:00 CT — well inside 08:30..15:10 window."""
    strat = OpeningRangeBreakoutStrategy(ORBProfile(symbol="MNQ", range_minutes=5))
    out = extract_intent(
        strat, _bar(), _state(),
        schedule=MarketHours(open_ct=time(8, 30), close_ct=time(15, 10)),
        now=datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
    )
    assert out["schedule_open"] is True
    assert out["next_window_opens_in_seconds"] is None


def test_intent_market_hours_outside_window_returns_seconds_to_open() -> None:
    """03:00 UTC = 22:00 CT prior day. Next open is 08:30 CT today."""
    strat = OpeningRangeBreakoutStrategy(ORBProfile(symbol="MNQ", range_minutes=5))
    # 03:00 UTC on 2026-05-24 = 22:00 CT on 2026-05-23. Next 08:30 CT is
    # 2026-05-24 08:30 CT = 13:30 UTC. Delta = 10.5 hours = 37800 s.
    now = datetime(2026, 5, 24, 3, 0, tzinfo=UTC)
    out = extract_intent(
        strat, _bar(), _state(),
        schedule=MarketHours(open_ct=time(8, 30), close_ct=time(15, 10)),
        now=now,
    )
    assert out["schedule_open"] is False
    secs = out["next_window_opens_in_seconds"]
    assert secs is not None
    # Allow a 1-minute tolerance for DST/wall-clock arithmetic.
    assert 37_000 < secs < 38_500


def test_intent_custom_windows_outside_window_returns_seconds_to_open() -> None:
    """CustomWindows: 10:00..11:00 CT only. 12:00 CT after the window."""
    strat = OpeningRangeBreakoutStrategy(ORBProfile(symbol="MNQ", range_minutes=5))
    sched = CustomWindows(windows=[(time(10, 0), time(11, 0))])
    # 12:00 CT = 17:00 UTC. Next open is tomorrow 10:00 CT = 15:00 UTC.
    # 17:00 UTC -> 15:00 UTC next day = 22 hours.
    now = datetime(2026, 5, 24, 17, 0, tzinfo=UTC)
    out = extract_intent(
        strat, _bar(), _state(), schedule=sched, now=now,
    )
    assert out["schedule_open"] is False
    secs = out["next_window_opens_in_seconds"]
    assert secs is not None
    assert 78_000 < secs < 80_000  # ~22 hours, allow some tolerance


# ---------- Purity ----------------------------------------------------------

def test_extract_intent_does_not_mutate_strategy() -> None:
    strat = OpeningRangeBreakoutStrategy(ORBProfile(symbol="MNQ", range_minutes=5))
    before = strat._range_high, strat._range_low, strat._trades_today
    _ = extract_intent(strat, _bar(), _state())
    after = strat._range_high, strat._range_low, strat._trades_today
    assert before == after
