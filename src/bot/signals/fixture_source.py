"""FixtureSignalSource — replays a pre-built list of events.

Used by tests + the runtime `--check` smoke path when no real Discord
secrets are configured. `emit_rate_seconds=0.0` (the default) yields
every event back-to-back without awaiting; a positive value sleeps
between yields so integration tests can exercise the strategy's
"one signal per bar" cap with deterministic timing.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from bot.signals.source import SignalEvent


class FixtureSignalSource:
    """Test-friendly `SignalSource` that yields a fixed list of events."""

    def __init__(
        self,
        events: list[SignalEvent],
        *,
        emit_rate_seconds: float = 0.0,
    ) -> None:
        if emit_rate_seconds < 0.0:
            raise ValueError("emit_rate_seconds must be >= 0.0")
        self._events = list(events)
        self._emit_rate = emit_rate_seconds

    async def iter_signals(self) -> AsyncIterator[SignalEvent]:
        for event in self._events:
            if self._emit_rate > 0.0:
                await asyncio.sleep(self._emit_rate)
            yield event
