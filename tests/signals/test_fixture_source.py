"""FixtureSignalSource — replays pre-built events for tests. T3."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from bot.signals.fixture_source import FixtureSignalSource
from bot.signals.source import SignalEvent

_TS = datetime(2026, 5, 23, 14, 0, tzinfo=UTC)


def _ev(i: int) -> SignalEvent:
    return SignalEvent(
        received_at=_TS, symbol="MNQH26", side="BUY", qty=1,
        limit_price=20_100.0 + i, stop_loss=None, take_profit=None,
        raw_text=f"e{i}", source_id=f"id-{i}",
    )


async def test_yields_events_in_order():
    events = [_ev(i) for i in range(3)]
    source = FixtureSignalSource(events)
    out = [e async for e in source.iter_signals()]
    assert out == events


async def test_empty_input_completes_cleanly():
    source = FixtureSignalSource([])
    out = [e async for e in source.iter_signals()]
    assert out == []


async def test_emit_rate_respected():
    events = [_ev(i) for i in range(3)]
    source = FixtureSignalSource(events, emit_rate_seconds=0.02)

    async def consume():
        return [e async for e in source.iter_signals()]

    loop = asyncio.get_event_loop()
    start = loop.time()
    out = await consume()
    elapsed = loop.time() - start
    assert out == events
    # 3 events * 0.02s = 0.06s minimum (first emit is also delayed).
    assert elapsed >= 0.05


async def test_emit_rate_zero_is_immediate():
    events = [_ev(i) for i in range(10)]
    source = FixtureSignalSource(events, emit_rate_seconds=0.0)
    loop = asyncio.get_event_loop()
    start = loop.time()
    out = [e async for e in source.iter_signals()]
    assert len(out) == 10
    assert loop.time() - start < 0.05  # essentially instant


async def test_cancellable():
    """Consumer that stops mid-stream should not deadlock the source."""
    events = [_ev(i) for i in range(100)]
    source = FixtureSignalSource(events, emit_rate_seconds=0.0)

    count = 0
    async for _ in source.iter_signals():
        count += 1
        if count >= 3:
            break
    assert count == 3


async def test_emit_rate_negative_rejected():
    with pytest.raises(ValueError, match="emit_rate"):
        FixtureSignalSource([], emit_rate_seconds=-0.1)
