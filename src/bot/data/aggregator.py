"""BarAggregator — build 1m/5m bars from sub-interval ticks/sub-bars.

Spec: 01-data-pipeline.md §3.4. Closed-bar semantics: a bar closes when a tick
arrives crossing its [start, start+interval) boundary. The crossing tick
belongs to the NEXT bar.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from bot.types import Bar, Tick

_INTERVAL_TO_DELTA: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
}


def _floor_to_interval(t: datetime, interval: timedelta) -> datetime:
    """Round t down to the nearest interval boundary."""
    epoch = datetime(1970, 1, 1, tzinfo=t.tzinfo)
    delta_seconds = (t - epoch).total_seconds()
    interval_seconds = interval.total_seconds()
    floored_seconds = (int(delta_seconds) // int(interval_seconds)) * int(interval_seconds)
    return epoch + timedelta(seconds=floored_seconds)


class BarAggregator:
    """Stateful aggregator. One instance per (symbol, interval)."""

    def __init__(self, interval: str, symbol: str) -> None:
        if interval not in _INTERVAL_TO_DELTA:
            raise ValueError(f"Unsupported interval: {interval!r}")
        self._interval_str = interval
        self._interval = _INTERVAL_TO_DELTA[interval]
        self._symbol = symbol
        self._current: Bar | None = None
        self._last_tick_ts: datetime | None = None

    def feed(self, t: Tick) -> Bar | None:
        """Process a tick; return the just-closed bar, or None."""
        if self._last_tick_ts is not None and t.timestamp <= self._last_tick_ts:
            raise ValueError(
                f"Tick out of order: {t.timestamp} <= last {self._last_tick_ts}"
            )
        self._last_tick_ts = t.timestamp

        bar_start = _floor_to_interval(t.timestamp, self._interval)

        if self._current is None:
            self._current = Bar(
                symbol=self._symbol,
                open=t.price, high=t.price, low=t.price, close=t.price,
                volume=t.size,
                timestamp=bar_start, interval=self._interval_str,
            )
            return None

        if bar_start > self._current.timestamp:
            # Bar closes; the crossing tick opens the next bar.
            closed = self._current
            self._current = Bar(
                symbol=self._symbol,
                open=t.price, high=t.price, low=t.price, close=t.price,
                volume=t.size,
                timestamp=bar_start, interval=self._interval_str,
            )
            return closed

        # Tick is within the current bar — update OHLC + volume
        cur = self._current
        self._current = Bar(
            symbol=cur.symbol,
            open=cur.open,
            high=max(cur.high, t.price),
            low=min(cur.low, t.price),
            close=t.price,
            volume=cur.volume + t.size,
            timestamp=cur.timestamp,
            interval=cur.interval,
        )
        return None

    def flush(self) -> Bar | None:
        """Drain the in-progress bar (end-of-data only)."""
        out = self._current
        self._current = None
        return out
