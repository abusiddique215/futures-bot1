"""TelemetryBus — fan-out from gate decisions / engine events → sinks.

The bus exposes two dispatch surfaces:
  - `alert(kind, **kw)` — sync; satisfies Plan 3's `_Telemetry` Protocol so
    the gate can call it without juggling event loops inside rule checks.
  - `aalert(kind, **kw)` — async; awaits the full fan-out. T9's
    `force_flatten_now` (async) uses this for determinism.

Sync `alert()` dispatch:
  - Inside a running loop: `create_task` on the fan-out coroutine; the call
    returns immediately, the task fires when the loop next schedules.
  - Outside a loop (sync backtest): `asyncio.run()` drains a fresh loop.

A sink whose `receive` raises is logged and skipped — a bad subscriber must
NOT cascade-kill the engine.
"""
from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

from loguru import logger


@runtime_checkable
class Sink(Protocol):
    """Subscriber Protocol — implement `async def receive(kind, **kw)`."""
    async def receive(self, kind: str, **kw: object) -> None: ...


class TelemetryBus:
    """In-process pub-sub. Subscribers attach via `subscribe(sink)`."""

    def __init__(self) -> None:
        self._sinks: list[Sink] = []
        # Strong refs to in-flight fan-out tasks so they aren't GC'd before
        # they finish (asyncio docs: "Save a reference to the result of this
        # function, to avoid a task disappearing mid-execution.")
        self._inflight: set[asyncio.Task[None]] = set()

    def subscribe(self, sink: Sink) -> None:
        self._sinks.append(sink)

    def unsubscribe(self, sink: Sink) -> None:
        if sink in self._sinks:
            self._sinks.remove(sink)

    async def _fan_out(self, kind: str, kw: dict[str, Any]) -> None:
        """Deliver one alert to every sink. Sink errors are logged and skipped."""
        for sink in list(self._sinks):
            try:
                await sink.receive(kind, **kw)
            except Exception as e:
                # Bus-level catch: see module docstring — a bad sink must NOT
                # cascade-kill the engine.
                logger.bind(sink=type(sink).__name__).error(
                    "telemetry sink raised: {}", e,
                )

    async def aalert(self, kind: str, **kw: object) -> None:
        """Async-native fan-out — await this when you're already async."""
        await self._fan_out(kind, kw)

    def alert(self, kind: str, **kw: object) -> None:
        """Sync entrypoint — satisfies gate.py's `_Telemetry` Protocol.

        If a loop is running, the fan-out is scheduled as a task (fire and
        forget — async sinks complete on the next loop turn). If NO loop is
        running, we drain a fresh loop with explicit close() — asyncio.run()
        and asyncio.Runner both leak the loop's selector self-pipe in Python
        3.13 + pytest-asyncio sessions, tripping PytestUnraisableExceptionWarning.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop — sync caller (e.g. backtest engine). Drain inline.
            new_loop = asyncio.new_event_loop()
            try:
                new_loop.run_until_complete(self._fan_out(kind, kw))
            finally:
                new_loop.close()
            return
        # Hold a reference to the task so it isn't GC'd mid-flight. Sinks
        # complete on the next loop turn; if no one awaits, that's fine —
        # this is the fire-and-forget path (gate.py sync alert calls).
        self._inflight.add(loop.create_task(self._fan_out(kind, kw)))
        self._inflight = {t for t in self._inflight if not t.done()}


class NoopTelemetryBus:
    """Drop-in TelemetryBus that does nothing.

    Plan 9 plugs this in when the gate isn't given a real bus, so existing
    Plan 3 tests keep passing unchanged. Satisfies _Telemetry's `alert` and
    matches TelemetryBus's `aalert` for code that awaits.
    """

    def alert(self, kind: str, **kw: object) -> None:
        _ = (kind, kw)

    async def aalert(self, kind: str, **kw: object) -> None:
        _ = (kind, kw)

    def subscribe(self, sink: Sink) -> None:
        _ = sink

    def unsubscribe(self, sink: Sink) -> None:
        _ = sink
