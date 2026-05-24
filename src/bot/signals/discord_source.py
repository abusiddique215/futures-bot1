"""DiscordSignalSource — listens to a Discord channel via discord.py.

Production-side `SignalSource`. The discord.py `Client` is injected via
`client_factory` so tests can swap in a MagicMock and exercise the
on_message → queue → iter_signals path without opening a real socket.

Safety: every event yielded here flows through `SignalStrategy` →
`TopstepRiskGate.approve_or_deny` before any broker call. Even if the
upstream channel posts 1,000 garbled messages, the gate's max_position
cap denies oversize orders (rule 4). No bypass.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any, Final

from bot.signals.parser import parse_signal_message
from bot.signals.source import SignalEvent

log = logging.getLogger(__name__)

_SENTINEL: Final[object] = object()

DiscordClientFactory = Callable[[], Any]


def _default_client_factory() -> Any:
    """Build a real discord.py Client with message-content intent enabled.

    Imported lazily so tests can use this module without `discord` being
    importable in some restricted environments.
    """
    import discord

    intents = discord.Intents.default()
    intents.message_content = True
    return discord.Client(intents=intents)


class DiscordSignalSource:
    """Async iterator of `SignalEvent`s sourced from one or more Discord channels.

    The lifecycle is two halves:
      1. `start_in_background()` connects the discord.py client.
      2. `iter_signals()` yields parsed events as they arrive.

    Call `close()` to shut down the source — iter_signals then exits cleanly.
    """

    def __init__(
        self,
        *,
        token: str,
        channel_ids: list[int],
        default_symbol: str,
        client_factory: DiscordClientFactory = _default_client_factory,
        max_queue_size: int = 1000,
    ) -> None:
        self._token = token
        self._channel_ids = set(channel_ids)
        self._default_symbol = default_symbol
        self._client = client_factory()
        # asyncio.Queue holds parsed SignalEvent | _SENTINEL (signals shutdown).
        self._queue: asyncio.Queue[SignalEvent | object] = asyncio.Queue(
            maxsize=max_queue_size,
        )
        self._closed = False
        # Wire on_message via discord.py's event-handler hook. discord.Client
        # supports `.event` decorator OR direct attribute assignment.
        self._client.event(self._on_message)

    async def _on_message(self, message: Any) -> None:
        """Discord event handler — called by discord.py for every message."""
        await self._handle_message(message)

    async def _handle_message(self, message: Any) -> None:
        """Test-friendly seam: parse + enqueue one message.

        Public test surface — exercised directly by tests via AsyncMock'd
        messages so we don't have to spin up a real client.
        """
        # Skip self / other bots — common Discord gotcha (echo loop).
        try:
            if message.author.bot:
                return
        except AttributeError:
            pass

        try:
            channel_id = int(message.channel.id)
        except AttributeError:
            return
        if channel_id not in self._channel_ids:
            return

        text = str(message.content or "")
        msg_id = str(getattr(message, "id", ""))
        event = parse_signal_message(
            text,
            default_symbol=self._default_symbol,
            received_at=datetime.now(UTC),
            source_id=msg_id,
        )
        if event is None:
            log.info("discord: unparseable message in ch=%d: %r", channel_id, text)
            return

        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("discord: queue full, dropping event %s", event.source_id)

    async def iter_signals(self) -> AsyncIterator[SignalEvent]:
        """Yield events as they arrive. Exits when `close()` is called."""
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                return
            assert isinstance(item, SignalEvent)
            yield item

    def start_in_background(self) -> asyncio.Task[None]:
        """Connect the discord.py client in a background task.

        The caller owns the task — cancel it (or call `close()`) to
        disconnect. Returns the asyncio Task so the caller can await
        cancellation in their teardown path.
        """
        return asyncio.create_task(self._client.start(self._token),
                                   name="discord_signal_source")

    async def close(self) -> None:
        """Disconnect the discord.py client and unblock iter_signals."""
        if self._closed:
            return
        self._closed = True
        try:
            await self._client.close()
        except Exception as e:
            log.warning("discord: client.close raised: %s", e)
        # Wake up any pending iter_signals consumer.
        await self._queue.put(_SENTINEL)
