"""FastAPI WS route for the v2 dashboard.

Single endpoint `/ws`. On connect, the client is registered with the
broadcaster and receives ALL events by default. A client can opt into
filtered delivery by sending:

  {"action": "subscribe", "channels": ["fleet"]}
  {"action": "subscribe", "channels": ["bot:alpha", "bot:beta"]}

Channel semantics live in ws_bridge._channels_for_event.

Handles disconnect cleanly: when the WS receive raises (client gone or
normal close), the broadcaster removes the client + cancels its drain
task; the route returns.
"""
from __future__ import annotations

import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from bot.dashboard.v2.ws_bridge import WebSocketBroadcaster

log = logging.getLogger(__name__)


async def ws_endpoint(websocket: WebSocket) -> None:
    """Accept a WS connection, register with the broadcaster, then pump."""
    state = websocket.app.state.dashboard
    broadcaster: WebSocketBroadcaster | None = state.broadcaster
    if broadcaster is None:
        await websocket.close(code=1011)
        return
    await websocket.accept()
    await broadcaster.register(websocket)
    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                return
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("action") == "subscribe":
                channels = msg.get("channels") or []
                if isinstance(channels, list):
                    broadcaster.subscribe(
                        websocket,
                        [c for c in channels if isinstance(c, str)],
                    )
    finally:
        await broadcaster.unregister(websocket)
