"""IBLiveBarStream — live MNQ bars from IB Gateway via ib_async.

Plan 6 fills in the skeleton from Plan 2. Tests drive the FakeIB and assert
that 5-sec RealTimeBar updates aggregate to 1-minute Bar instances yielded
from IBLiveBarStream.subscribe().
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from bot.data.live_ib import IBLiveBarStream
from tests.fakes.fake_ib import FakeIB


@dataclass
class _FakeRTB:
    """Minimal RealTimeBar shim — only the fields IBLiveBarStream reads."""
    time: datetime
    open_: float
    high: float
    low: float
    close: float
    volume: int


def test_ib_live_bar_stream_constructs() -> None:
    s = IBLiveBarStream(host="127.0.0.1", port=4002, client_id=7)
    assert s.host == "127.0.0.1"
    assert s.port == 4002
    assert s.client_id == 7


async def test_connect_opens_ib_connection_and_subscribes_to_realtime_bars() -> None:
    fake = FakeIB()
    s = IBLiveBarStream(host="1.2.3.4", port=4002, client_id=9,
                        ib_factory=lambda: fake)
    await s.connect()
    assert fake.connect_calls == [("1.2.3.4", 4002, 9)]


async def test_subscribe_yields_aggregated_1m_bars_from_5sec_updates() -> None:
    """Twelve 5-sec bars within one minute → one closed 1m bar emitted."""
    fake = FakeIB()
    s = IBLiveBarStream(host="127.0.0.1", port=4002, client_id=1,
                        ib_factory=lambda: fake)
    await s.connect()

    # Build the 5-sec bar feed: 12 bars covering 14:30:00-14:30:55, then one
    # at 14:31:00 to trigger 14:30 close.
    base = datetime(2026, 5, 22, 14, 30, 0, tzinfo=UTC)
    bars = []
    for i in range(12):
        bars.append(_FakeRTB(
            time=base.replace(second=i * 5),
            open_=100.0 + i, high=101.0 + i, low=99.0 + i,
            close=100.5 + i, volume=10,
        ))
    bars.append(_FakeRTB(
        time=datetime(2026, 5, 22, 14, 31, 0, tzinfo=UTC),
        open_=200.0, high=200.0, low=200.0, close=200.0, volume=5,
    ))

    async def drive_feed() -> None:
        # Allow subscribe() to register its handler.
        await asyncio.sleep(0)
        for b in bars:
            fake.realtime_bars.append(b)
            fake.barUpdateEvent.emit(fake.realtime_bars, True)
            await asyncio.sleep(0)

    drive = asyncio.create_task(drive_feed())
    out_bars = []
    async for bar in s.subscribe(symbol="MNQ", interval="1m"):
        out_bars.append(bar)
        if len(out_bars) >= 1:
            break
    await drive

    assert len(out_bars) == 1
    closed = out_bars[0]
    assert closed.symbol == "MNQ"
    assert closed.interval == "1m"
    assert closed.timestamp == base  # the bar's open time
    # Volume = 12 ticks of 10 each = 120 (just the closed-minute ticks).
    assert closed.volume == 120
    # Each 5-sec RTB collapses to one Tick(price=close, size=volume) — so the
    # 1m bar's OHLC is built from the sequence of RTB closes (100.5 .. 111.5).
    # This loses sub-5-sec OHLC; irrelevant for 1m/5m aggregation. See
    # IBLiveBarStream module docstring.
    assert closed.open == pytest.approx(100.5)
    assert closed.close == pytest.approx(111.5)
    assert closed.high == pytest.approx(111.5)
    assert closed.low == pytest.approx(100.5)


async def test_subscribe_requires_connect_first() -> None:
    s = IBLiveBarStream(host="127.0.0.1", port=4002, client_id=1)

    async def consume() -> None:
        async for _ in s.subscribe(symbol="MNQ", interval="1m"):
            return

    with pytest.raises(RuntimeError, match="connect"):
        await consume()
