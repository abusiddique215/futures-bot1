"""LiveBarSource Protocol + SimBarSource adapter.

`LiveTradingLoop` consumes an async Bar stream. Real implementations wrap
`IBLiveBarStream` (Plan 6) or a TopstepX market-data adapter. Tests + sim
runs use `SimBarSource` — a thin wrapper around a sync Iterable that yields
each bar to the async consumer without any I/O.

Keeping the Protocol minimal (one method, one return type) means anything
exposing `subscribe()` → `AsyncIterator[Bar]` can be plugged in.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
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
