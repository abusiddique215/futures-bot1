"""WebSocketBroadcaster — TelemetryBus sink fanning out to WS clients.

Per-client async queue + drain task isolates fast clients from slow ones.
A client that fills its queue (default 100 messages) is dropped and closed
on the next push.

The broadcaster's `receive(kind, **kw)` is what `TelemetryBus._fan_out`
calls. It serializes the payload to JSON via Pydantic (when the kind has a
known schema in `events.py`) or falls back to `json.dumps(..., default=str)`
for unknown kinds — keeps the broadcaster a dumb relay rather than a
schema enforcer.

The interface a WS client needs is intentionally minimal — `send_text(str)`
+ `close(code: int)`. Any starlette WebSocket satisfies it; tests inject
lightweight stand-ins.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from bot.dashboard.v2.events import (
    AccountUpdateEvent,
    BarTickEvent,
    BotIntentEvent,
    BotStateChangeEvent,
    FillEvent,
    RiskDecisionEvent,
)

log = logging.getLogger(__name__)

# Canonical kind → model. Unknown kinds bypass validation.
_MODELS: dict[str, type[BaseModel]] = {
    "bar_tick": BarTickEvent,
    "account_update": AccountUpdateEvent,
    "bot_intent": BotIntentEvent,
    "fill": FillEvent,
    "risk_decision": RiskDecisionEvent,
    "bot_state_change": BotStateChangeEvent,
}


@runtime_checkable
class WebSocketLike(Protocol):
    """Minimal interface — starlette WebSocket satisfies it."""

    async def send_text(self, payload: str) -> None: ...
    async def close(self, code: int = ...) -> None: ...


class _ClientState:
    """Per-client queue + drain task. Owned exclusively by the broadcaster."""

    def __init__(self, ws: WebSocketLike, max_queue: int) -> None:
        self.ws = ws
        # asyncio.Queue is bounded; put_nowait raises QueueFull when at
        # max_queue, which is our drop signal.
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_queue)
        self.drain_task: asyncio.Task[None] | None = None
        self.dropped = False


class WebSocketBroadcaster:
    """Receives TelemetryBus events; fans out to all WS clients.

    Parameters
    ----------
    max_queue_per_client
        Per-client outbound queue bound. A client that can't drain fast
        enough is dropped + closed once their queue is full. Default 100
        gives 5+ seconds of slack at a 20 Hz peak bar cadence — more than
        any web client should reasonably need.
    """

    def __init__(self, *, max_queue_per_client: int = 100) -> None:
        self._max_queue = max_queue_per_client
        self._clients: dict[int, _ClientState] = {}
        # Strong refs to drain tasks so they're not GC'd before completing.
        self._drain_tasks: set[asyncio.Task[None]] = set()

    # ---- TelemetryBus sink protocol ----

    async def receive(self, kind: str, **kw: object) -> None:
        """Sink entrypoint — fan out one event to every registered client.

        Serializes once, enqueues per-client. Errors during enqueue (queue
        full / drain task gone) trigger client drop + close.
        """
        if not self._clients:
            return
        payload = _serialize(kind, kw)
        # Snapshot client list so a concurrent unregister can't perturb us.
        for state in list(self._clients.values()):
            if state.dropped:
                continue
            try:
                state.queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop the slow client. Close fires inside _drop so the test
                # observes `closed = True` synchronously after this call.
                await self._drop(state)
        # Yield once so each per-client drain task drains the message it just
        # received before receive() returns. Without this, callers awaiting
        # receive() would observe `ws.sent` empty even though the message is
        # already on the queue. The yield is bounded by the number of fast
        # clients; slow clients block only their own drain task, not ours.
        await asyncio.sleep(0)

    # ---- public API ----

    async def register(self, ws: WebSocketLike) -> None:
        """Add a client + start its drain task."""
        state = _ClientState(ws, self._max_queue)
        self._clients[id(ws)] = state
        state.drain_task = asyncio.create_task(
            self._drain(state), name="ws-drain",
        )
        # Hold a strong ref so the task isn't GC'd before its first await.
        self._drain_tasks.add(state.drain_task)

    async def unregister(self, ws: WebSocketLike) -> None:
        """Remove + cancel a client's drain task. Idempotent."""
        state = self._clients.pop(id(ws), None)
        if state is None:
            return
        await self._cancel_drain(state)

    def clients(self) -> list[WebSocketLike]:
        """List currently-registered, non-dropped clients."""
        return [s.ws for s in self._clients.values() if not s.dropped]

    async def close_all(self) -> None:
        """Drop every client + close their WS. For shutdown."""
        for state in list(self._clients.values()):
            await self._drop(state)
        self._clients.clear()

    # ---- internals ----

    async def _drain(self, state: _ClientState) -> None:
        """Pump messages from the per-client queue to ws.send_text."""
        try:
            while True:
                payload = await state.queue.get()
                try:
                    await state.ws.send_text(payload)
                except Exception as e:
                    log.debug("ws send failed, dropping client: %s", e)
                    state.dropped = True
                    try:
                        await state.ws.close(code=1011)
                    except Exception:
                        pass
                    return
        except asyncio.CancelledError:
            return

    async def _drop(self, state: _ClientState) -> None:
        """Mark a client dropped + cancel its drain task + close ws."""
        if state.dropped:
            return
        state.dropped = True
        # Remove from the live client map so receive() skips it.
        self._clients.pop(id(state.ws), None)
        await self._cancel_drain(state)
        try:
            await state.ws.close(code=1013)  # 1013 = try-again-later
        except Exception as e:
            log.debug("close on dropped client raised: %s", e)

    async def _cancel_drain(self, state: _ClientState) -> None:
        task = state.drain_task
        if task is None or task.done():
            self._drain_tasks.discard(task) if task is not None else None
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        self._drain_tasks.discard(task)


# ---- helpers ---------------------------------------------------------------

def _serialize(kind: str, kw: dict[str, Any]) -> str:
    """Build the JSON envelope `{kind, data}` once, reused per client."""
    model_cls = _MODELS.get(kind)
    if model_cls is not None:
        try:
            data = model_cls.model_validate(kw).model_dump(mode="json")
        except ValidationError as e:
            # Don't drop the message — surface the kw verbatim. The dashboard
            # will see a malformed payload but the operator gets a log line.
            log.warning("payload failed validation for kind=%s: %s", kind, e)
            data = kw
    else:
        data = kw
    return json.dumps({"kind": kind, "data": data}, default=str)
