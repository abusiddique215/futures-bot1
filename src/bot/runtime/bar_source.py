"""LiveBarSource Protocol + SimBarSource adapter + DemoBarSource (dashboard).

`LiveTradingLoop` consumes an async Bar stream. Real implementations wrap
`IBLiveBarStream` (Plan 6) or a TopstepX market-data adapter. Tests + sim
runs use `SimBarSource` — a thin wrapper around a sync Iterable that yields
each bar to the async consumer without any I/O.

`DemoBarSource` generates a never-ending synthetic random walk so the
dashboard has something to display when no live broker is wired (Plan 23
follow-up: without it, `python -m bot.runtime --dashboard` exits as soon as
the empty sim source iterates to nothing, taking the dashboard with it).
"""
from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from bot.types import Bar


@runtime_checkable
class LiveBarSource(Protocol):
    """Async Bar stream input to `LiveTradingLoop`.

    `subscribe()` returns an async iterator that yields completed bars in
    chronological order. Implementations must NOT yield duplicate bars on
    reconnect — backfill / de-dup is the source's responsibility, not the
    loop's.
    """
    def subscribe(self) -> AsyncIterator[Bar]: ...


class SimBarSource:
    """Adapter that wraps a sync `Iterable[Bar]` as a `LiveBarSource`.

    Used by:
      - The integration tests in this plan (synthetic bar lists).
      - `env=dev` + `broker=sim` runs from `main.py`, where the default is
        `SimBarSource([])` — the loop iterates zero bars and exits, keeping
        the `--check` smoke test green.
    """

    def __init__(self, bars: Iterable[Bar]) -> None:
        # Materialize so a generator-based input can't be exhausted twice.
        self._bars: list[Bar] = list(bars)

    async def subscribe(self) -> AsyncIterator[Bar]:
        for bar in self._bars:
            yield bar


class DemoBarSource:
    """Never-ending random-walk bar stream for dashboard demo mode.

    When `python -m bot.runtime --dashboard` is invoked without a live broker
    or fixture bars, every bot would otherwise complete instantly with bars=0
    and the process (including the dashboard server) would exit. DemoBarSource
    keeps the loop alive so the user can actually open the dashboard.

    Emits one bar per `interval_seconds` (default 5s), starting from
    `start_price` with a normal-ish random walk. Tight OHLC spread by default
    so accidental ORB triggers stay rare — this is for showing the UI alive,
    not for honest backtesting.
    """

    def __init__(
        self,
        *,
        symbol: str,
        interval_seconds: float = 5.0,
        start_price: float = 18_000.0,
        step_stddev: float = 1.0,
        seed: int | None = None,
    ) -> None:
        self._symbol = symbol
        self._interval = interval_seconds
        self._price = start_price
        self._stddev = step_stddev
        self._rng = random.Random(seed)

    async def subscribe(self) -> AsyncIterator[Bar]:
        while True:
            await asyncio.sleep(self._interval)
            o = self._price
            delta = self._rng.gauss(0.0, self._stddev)
            c = round(o + delta, 2)
            high = max(o, c) + abs(self._rng.gauss(0.0, self._stddev * 0.3))
            low = min(o, c) - abs(self._rng.gauss(0.0, self._stddev * 0.3))
            yield Bar(
                symbol=self._symbol,
                open=o,
                high=round(high, 2),
                low=round(low, 2),
                close=c,
                volume=self._rng.randint(50, 500),
                timestamp=datetime.now(UTC),
                interval="5s",
            )
            self._price = c
