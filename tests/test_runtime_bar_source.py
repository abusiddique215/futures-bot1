"""Plan 10 T1: LiveBarSource Protocol + SimBarSource adapter.

LiveBarSource is the Bar-stream input shape for LiveTradingLoop. SimBarSource
adapts a sync Iterable[Bar] so tests + sim runs can drive the loop without
real broker / IB Gateway involvement.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bot.runtime.bar_source import LiveBarSource, SimBarSource
from bot.types import Bar


def _bars(n: int) -> list[Bar]:
    start = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    return [
        Bar(
            symbol="MNQ",
            open=18_000.0 + i,
            high=18_000.5 + i,
            low=17_999.5 + i,
            close=18_000.25 + i,
            volume=100,
            timestamp=start + timedelta(minutes=i),
            interval="1m",
        )
        for i in range(n)
    ]


async def test_sim_bar_source_yields_all_bars_in_order() -> None:
    """SimBarSource.subscribe() yields the underlying bars unchanged."""
    bars = _bars(5)
    source = SimBarSource(bars)
    received: list[Bar] = []
    async for bar in source.subscribe():
        received.append(bar)
    assert received == bars


async def test_sim_bar_source_empty_completes_cleanly() -> None:
    """Empty source completes without yielding anything."""
    source = SimBarSource([])
    received: list[Bar] = []
    async for bar in source.subscribe():
        received.append(bar)
    assert received == []


def test_sim_bar_source_satisfies_protocol() -> None:
    """SimBarSource structurally satisfies LiveBarSource."""
    source = SimBarSource([])
    assert isinstance(source, LiveBarSource)
