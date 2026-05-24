"""DiscordSignalSource — discord.py-backed signal source. T4.

Tests use AsyncMock for the discord client: no real network connection
is established in CI. We exercise the on_message handler directly to
confirm: (a) messages in watched channels reach the iter_signals queue;
(b) messages in unwatched channels are dropped; (c) malformed messages
are dropped without crashing.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from bot.signals.discord_source import DiscordSignalSource


def _msg(*, content: str, channel_id: int, message_id: int = 1, bot: bool = False):
    """Build a discord.py-shaped message mock."""
    m = MagicMock()
    m.content = content
    m.id = message_id
    m.channel = MagicMock()
    m.channel.id = channel_id
    m.author = MagicMock()
    m.author.bot = bot
    return m


async def test_message_in_watched_channel_yields_signal():
    client = MagicMock()
    client.start = AsyncMock()
    client.close = AsyncMock()
    source = DiscordSignalSource(
        token="fake",
        channel_ids=[1001],
        default_symbol="NQ",
        client_factory=lambda: client,
    )

    msg = _msg(content="BUY NQ @20100 SL=20070 TP=20160", channel_id=1001)
    await source._handle_message(msg)

    # iter_signals reads from the internal queue.
    async def first():
        async for ev in source.iter_signals():
            return ev
        return None

    ev = await asyncio.wait_for(first(), timeout=0.5)
    assert ev is not None
    assert ev.side == "BUY"
    assert ev.symbol == "NQ"
    assert ev.source_id == "1"


async def test_message_in_unwatched_channel_ignored():
    client = MagicMock()
    source = DiscordSignalSource(
        token="fake", channel_ids=[1001], default_symbol="NQ",
        client_factory=lambda: client,
    )
    msg = _msg(content="BUY NQ @20100 SL=20070 TP=20160", channel_id=9999)
    await source._handle_message(msg)
    assert source._queue.qsize() == 0


async def test_malformed_message_logged_not_crashed(caplog):
    client = MagicMock()
    source = DiscordSignalSource(
        token="fake", channel_ids=[1001], default_symbol="NQ",
        client_factory=lambda: client,
    )
    msg = _msg(content="hello world this is not a signal", channel_id=1001)
    await source._handle_message(msg)
    assert source._queue.qsize() == 0


async def test_bot_messages_ignored():
    """Don't echo our own bot's messages — common Discord gotcha."""
    client = MagicMock()
    source = DiscordSignalSource(
        token="fake", channel_ids=[1001], default_symbol="NQ",
        client_factory=lambda: client,
    )
    msg = _msg(
        content="BUY NQ @20100 SL=20070 TP=20160",
        channel_id=1001, bot=True,
    )
    await source._handle_message(msg)
    assert source._queue.qsize() == 0


async def test_multiple_messages_preserve_order():
    client = MagicMock()
    source = DiscordSignalSource(
        token="fake", channel_ids=[1001], default_symbol="NQ",
        client_factory=lambda: client,
    )
    for i in range(3):
        msg = _msg(
            content=f"BUY NQ @{20100 + i} SL=20070 TP=20160",
            channel_id=1001, message_id=i,
        )
        await source._handle_message(msg)

    out = []
    async def consume():
        async for ev in source.iter_signals():
            out.append(ev)
            if len(out) == 3:
                return

    await asyncio.wait_for(consume(), timeout=0.5)
    assert [int(e.limit_price or 0) for e in out] == [20_100, 20_101, 20_102]


async def test_close_stops_iteration():
    """After close(), iter_signals should exit (not hang forever)."""
    client = MagicMock()
    client.close = AsyncMock()
    source = DiscordSignalSource(
        token="fake", channel_ids=[1001], default_symbol="NQ",
        client_factory=lambda: client,
    )

    async def consume_with_timeout():
        out = []
        async for ev in source.iter_signals():
            out.append(ev)
        return out

    task = asyncio.create_task(consume_with_timeout())
    await asyncio.sleep(0.02)
    await source.close()
    result = await asyncio.wait_for(task, timeout=0.5)
    assert result == []


async def test_start_invokes_client_start():
    client = MagicMock()
    client.start = AsyncMock()
    source = DiscordSignalSource(
        token="abc", channel_ids=[1001], default_symbol="NQ",
        client_factory=lambda: client,
    )
    # start_in_background creates a task that awaits client.start(token).
    task = source.start_in_background()
    # Let the task scheduler run the coroutine at least once.
    await asyncio.sleep(0.01)
    client.start.assert_called_once_with("abc")
    # AsyncMock returns immediately, so the task completes successfully —
    # cleanup is best-effort.
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
