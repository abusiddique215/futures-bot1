"""Bot intent extractor — "what is the bot watching for right now".

Pure function `extract_intent(strategy, current_bar, account_state)` returns
a dict that the dashboard renders verbatim:

  {
    "watching_for": str,                   # human-readable; trader vocab
    "schedule_open": bool,                 # is the bot's window open now?
    "next_window_opens_in_seconds": int | None,  # None ⇒ open / always-on
    "max_trades_remaining": int | None,    # None when strategy has no cap
  }

Each strategy class registers an extractor; unknown strategies fall back
to a generic "Watching for entry signal". The function reads strategy
state but NEVER mutates — repeat calls return the same value for the
same input.

The schedule helper computes `next_window_opens_in_seconds` for the three
built-in Schedule impls (AlwaysOn, MarketHours, CustomWindows). Walking
forward up to 8 days covers DST transitions and weekend gaps for the
sessions we ship.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bot.runtime.fleet.schedule import AlwaysOn, CustomWindows, MarketHours, Schedule
from bot.strategy.mean_reversion import MeanReversionStrategy
from bot.strategy.orb import OpeningRangeBreakoutStrategy
from bot.strategy.signal_strategy import SignalStrategy
from bot.strategy.tiered_sizing import TieredSizingDecorator
from bot.strategy.trend_following import TrendFollowingStrategy
from bot.types import Bar

_CT = ZoneInfo("America/Chicago")
_FALLBACK = "Watching for entry signal"


# ---- per-strategy extractors -----------------------------------------------

def _orb_extractor(strategy: Any, bar: Bar, state: dict[str, Any]) -> dict[str, Any]:
    _ = (bar, state)
    profile = strategy._profile
    range_high = strategy._range_high
    range_low = strategy._range_low
    trades_remaining = max(
        0, profile.max_trades_per_day - strategy._trades_today,
    )
    if range_high is None or range_low is None:
        msg = (
            f"Building opening range "
            f"(first {profile.range_minutes}m of session)"
        )
    else:
        msg = (
            f"Watching for breakout > {range_high:.2f} "
            f"or < {range_low:.2f} (range: {profile.range_minutes}m)"
        )
    return {
        "watching_for": msg,
        "max_trades_remaining": trades_remaining,
    }


def _trend_following_extractor(
    strategy: Any, bar: Bar, state: dict[str, Any],
) -> dict[str, Any]:
    _ = (bar, state)
    fast = strategy._fast_ema
    slow = strategy._slow_ema
    atr = strategy._atr
    if fast is None or slow is None:
        trend = "warming up"
    elif fast > slow:
        trend = "bullish"
    elif fast < slow:
        trend = "bearish"
    else:
        trend = "none"
    if fast is not None and atr is not None:
        zone_low = fast - strategy._pullback_atr_mult * atr
        zone_high = fast + strategy._pullback_atr_mult * atr
        msg = (
            f"Trend = {trend}; pullback zone "
            f"{zone_low:.2f}-{zone_high:.2f}"
        )
    else:
        msg = f"Trend = {trend}; warming indicators"
    trades_remaining = max(
        0, strategy._max_trades_per_day - strategy._trades_today,
    )
    return {
        "watching_for": msg,
        "max_trades_remaining": trades_remaining,
    }


def _mean_reversion_extractor(
    strategy: Any, bar: Bar, state: dict[str, Any],
) -> dict[str, Any]:
    _ = (bar, state)
    bands = strategy._bollinger()
    if bands is None:
        msg = (
            f"Warming up BB({strategy._bb_period}, {strategy._bb_stddev})"
        )
    else:
        lower, _mid, upper, _sigma = bands
        msg = (
            f"BB upper {upper:.2f} lower {lower:.2f}; "
            f"RSI({strategy._rsi_period}) entry on "
            f"oversold<={strategy._rsi_oversold} / "
            f"overbought>={strategy._rsi_overbought}"
        )
    trades_remaining = max(
        0, strategy._max_trades_per_day - strategy._trades_today,
    )
    return {
        "watching_for": msg,
        "max_trades_remaining": trades_remaining,
    }


def _signal_extractor(
    strategy: Any, bar: Bar, state: dict[str, Any],
) -> dict[str, Any]:
    _ = (bar, state)
    qsize = strategy.queue_size() if hasattr(strategy, "queue_size") else 0
    msg = (
        f"Waiting on external signal (queue: {qsize})"
    )
    return {
        "watching_for": msg,
        "max_trades_remaining": None,
    }


def _tiered_extractor(
    strategy: Any, bar: Bar, state: dict[str, Any],
) -> dict[str, Any]:
    """TieredSizingDecorator wraps an inner strategy; recurse into it."""
    inner = strategy._inner
    return _dispatch(inner, bar, state)


_REGISTRY: dict[type, Callable[[Any, Bar, dict[str, Any]], dict[str, Any]]] = {
    OpeningRangeBreakoutStrategy: _orb_extractor,
    TrendFollowingStrategy: _trend_following_extractor,
    MeanReversionStrategy: _mean_reversion_extractor,
    SignalStrategy: _signal_extractor,
    TieredSizingDecorator: _tiered_extractor,
}


def _dispatch(
    strategy: Any, bar: Bar, state: dict[str, Any],
) -> dict[str, Any]:
    extractor = _REGISTRY.get(type(strategy))
    if extractor is None:
        return {
            "watching_for": _FALLBACK,
            "max_trades_remaining": None,
        }
    return extractor(strategy, bar, state)


# ---- schedule next-window helper -------------------------------------------

def _seconds_to_next_window(schedule: Schedule, now: datetime) -> int | None:
    """How many seconds until `schedule.should_trade(now+dt)` becomes True.

    Returns None for AlwaysOn (always-on, no "next" window) or when the
    schedule is open right now. Walks forward in 1-minute increments up to
    8 days — long enough to span a weekend and a DST jump in the schedules
    we ship.
    """
    if isinstance(schedule, AlwaysOn):
        return None
    if schedule.should_trade(now):
        return None
    if isinstance(schedule, MarketHours):
        return _market_hours_next_open(schedule, now)
    if isinstance(schedule, CustomWindows):
        return _custom_windows_next_open(schedule, now)
    # Unknown schedule — fall back to coarse 1-minute walk.
    return _walk_forward(schedule, now)


def _market_hours_next_open(sched: MarketHours, now: datetime) -> int:
    """Return seconds until the next `open_ct` time, in CT terms."""
    ct_now = now.astimezone(_CT)
    today_open = ct_now.replace(
        hour=sched.open_ct.hour, minute=sched.open_ct.minute,
        second=0, microsecond=0,
    )
    if ct_now.time() < sched.open_ct:
        target_ct = today_open
    else:
        target_ct = today_open + timedelta(days=1)
    target_utc = target_ct.astimezone(UTC)
    return max(0, int((target_utc - now).total_seconds()))


def _custom_windows_next_open(sched: CustomWindows, now: datetime) -> int | None:
    """Walk through the next 8 days of (date * windows) and pick the earliest
    start that is strictly after now."""
    if not sched.windows:
        return None
    local_now = now.astimezone(sched.tz)
    best: datetime | None = None
    for day_offset in range(0, 9):
        day = (local_now + timedelta(days=day_offset)).date()
        for start, _end in sched.windows:
            candidate = datetime.combine(
                day, _strip_microseconds(start), tzinfo=sched.tz,
            )
            if candidate > local_now and (best is None or candidate < best):
                best = candidate
    if best is None:
        return None
    return max(0, int((best.astimezone(UTC) - now).total_seconds()))


def _strip_microseconds(t: time) -> time:
    return t.replace(microsecond=0)


def _walk_forward(schedule: Schedule, now: datetime) -> int | None:
    """Last-resort: minute-stepping search up to 8 days."""
    step = timedelta(minutes=1)
    limit = timedelta(days=8)
    cursor = now + step
    while cursor - now < limit:
        if schedule.should_trade(cursor):
            return int((cursor - now).total_seconds())
        cursor += step
    return None


# ---- public API ------------------------------------------------------------

def extract_intent(
    strategy: Any,
    current_bar: Bar,
    account_state: dict[str, Any],
    *,
    schedule: Schedule | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pure function: build a trader-facing intent dict.

    Parameters
    ----------
    strategy
        The bot's Strategy instance. Looked up in _REGISTRY by exact type.
    current_bar
        Most recent closed bar. Used by extractors that condition on price.
    account_state
        Snapshot of relevant state (open_positions, equity, …). Optional
        for most extractors today; passed through for forward compatibility.
    schedule
        The bot's Schedule. When supplied, the result includes
        schedule_open + next_window_opens_in_seconds.
    now
        Reference time for schedule queries. Defaults to current_bar.timestamp.
    """
    out = _dispatch(strategy, current_bar, account_state)
    if schedule is not None:
        ref = now if now is not None else current_bar.timestamp
        out["schedule_open"] = schedule.should_trade(ref)
        out["next_window_opens_in_seconds"] = _seconds_to_next_window(
            schedule, ref,
        )
    return out
