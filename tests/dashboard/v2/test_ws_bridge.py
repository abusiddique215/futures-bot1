"""Tests for WebSocketBroadcaster — TelemetryBus sink → WS clients (Plan 23 T2)."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from bot.dashboard.v2.ws_bridge import WebSocketBroadcaster
from bot.observability.bus import Sink, TelemetryBus


class _FakeWS:
    """Minimal stand-in for starlette.websockets.WebSocket.

    Implements the methods WebSocketBroadcaster touches: send_text + close.
    `closed` flips True after the first send_text raises (simulating client
    disconnect).
    """

    def __init__(self, *, fail_on_send: bool = False) -> None:
        self.sent: list[str] = []
        self.fail_on_send = fail_on_send
        self.closed = False

    async def send_text(self, payload: str) -> None:
        if self.fail_on_send:
            raise RuntimeError("client gone")
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        _ = code
        self.closed = True


# ---------- Protocol satisfaction -------------------------------------------

def test_broadcaster_satisfies_sink_protocol() -> None:
    """WebSocketBroadcaster must be assignable to TelemetryBus's Sink."""
    bc = WebSocketBroadcaster()
    assert isinstance(bc, Sink)


# ---------- Fan-out ---------------------------------------------------------

async def test_register_and_broadcast_to_one_client() -> None:
    bc = WebSocketBroadcaster()
    ws = _FakeWS()
    await bc.register(ws)
    await bc.receive("bar_tick", bot="alpha", symbol="MNQH26", bar={
        "ts": datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
        "o": 1.0, "h": 1.0, "low": 1.0, "c": 1.0, "v": 1,
    })
    assert len(ws.sent) == 1
    payload = json.loads(ws.sent[0])
    assert payload["kind"] == "bar_tick"
    assert payload["data"]["bot"] == "alpha"


async def test_broadcast_to_three_clients_each_receives() -> None:
    bc = WebSocketBroadcaster()
    clients = [_FakeWS() for _ in range(3)]
    for c in clients:
        await bc.register(c)
    await bc.receive(
        "account_update",
        bot="alpha", state="ARMED_WAITING",
        equity=50_000.0, balance=50_000.0,
        realized_pnl_today=0.0, unrealized_pnl=0.0,
        high_water=50_000.0,
        distance_to_mll=2_000.0, distance_to_target=3_000.0,
        contracts_open=0, dll_remaining=1_000.0,
    )
    for c in clients:
        assert len(c.sent) == 1
        payload = json.loads(c.sent[0])
        assert payload["kind"] == "account_update"


async def test_unregister_stops_receiving() -> None:
    bc = WebSocketBroadcaster()
    ws = _FakeWS()
    await bc.register(ws)
    await bc.unregister(ws)
    await bc.receive("bot_intent", bot="alpha", watching_for="x",
                      schedule_open=True,
                      next_window_opens_in_seconds=None,
                      max_trades_remaining=1)
    assert ws.sent == []


# ---------- Failure handling ------------------------------------------------

async def test_failing_client_does_not_crash_broadcast() -> None:
    bc = WebSocketBroadcaster()
    good = _FakeWS()
    bad = _FakeWS(fail_on_send=True)
    await bc.register(good)
    await bc.register(bad)
    await bc.receive("bot_intent", bot="alpha", watching_for="x",
                      schedule_open=True,
                      next_window_opens_in_seconds=None,
                      max_trades_remaining=1)
    # The good client still got the message; the bad client was dropped.
    assert len(good.sent) == 1
    assert bad not in bc.clients()
    # The bad client was closed by the broadcaster's cleanup path.
    assert bad.closed is True


async def test_unknown_kind_passes_through_with_raw_payload() -> None:
    """An event kind not in our enum still ships as JSON — broadcaster
    is a dumb relay, not a schema enforcer."""
    bc = WebSocketBroadcaster()
    ws = _FakeWS()
    await bc.register(ws)
    await bc.receive("custom_thing", foo="bar")
    assert len(ws.sent) == 1
    payload = json.loads(ws.sent[0])
    assert payload["kind"] == "custom_thing"
    assert payload["data"] == {"foo": "bar"}


# ---------- Backpressure ----------------------------------------------------

class _SlowWS:
    """Client whose send_text awaits an event the test never sets — simulates
    a stuck client. Used to verify the broadcaster's queue-based isolation."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.sent_count = 0
        self.closed = False

    async def send_text(self, payload: str) -> None:
        _ = payload
        await self.gate.wait()
        self.sent_count += 1

    async def close(self, code: int = 1000) -> None:
        _ = code
        self.closed = True


async def test_slow_client_dropped_after_queue_full() -> None:
    """A client that can't keep up gets dropped + closed.

    Send 200 events into a broadcaster that holds a max-100 queue. The slow
    client never drains. It MUST be dropped before all 200 are queued, AND
    fast clients must still get every event.
    """
    bc = WebSocketBroadcaster(max_queue_per_client=10)
    slow = _SlowWS()
    fast = _FakeWS()
    await bc.register(slow)
    await bc.register(fast)
    for i in range(50):
        await bc.receive("bar_tick", bot="alpha", symbol="MNQH26", bar={
            "ts": datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
            "o": float(i), "h": float(i), "low": float(i), "c": float(i),
            "v": i,
        })
    # Fast client got every message.
    assert len(fast.sent) == 50
    # Slow client dropped and closed.
    assert slow not in bc.clients()
    assert slow.closed is True


# ---------- Bus integration -------------------------------------------------

async def test_subscribed_to_bus_relays_alerts() -> None:
    bus = TelemetryBus()
    bc = WebSocketBroadcaster()
    bus.subscribe(bc)
    ws = _FakeWS()
    await bc.register(ws)
    await bus.aalert("fill", bot="alpha", symbol="MNQH26", side="BUY",
                      quantity=1, fill_price=18_000.0,
                      timestamp=datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
                      client_order_id="x-1")
    assert len(ws.sent) == 1
    payload = json.loads(ws.sent[0])
    assert payload["kind"] == "fill"


async def test_close_all_unregisters_every_client() -> None:
    bc = WebSocketBroadcaster()
    clients = [_FakeWS() for _ in range(3)]
    for c in clients:
        await bc.register(c)
    await bc.close_all()
    assert bc.clients() == []
    for c in clients:
        assert c.closed is True


# ---------- JSON serialization ---------------------------------------------

async def test_datetime_serializes_to_iso() -> None:
    bc = WebSocketBroadcaster()
    ws = _FakeWS()
    await bc.register(ws)
    ts = datetime(2026, 5, 24, 14, 0, tzinfo=UTC)
    await bc.receive("fill", bot="alpha", symbol="MNQH26", side="BUY",
                      quantity=1, fill_price=18_000.0,
                      timestamp=ts, client_order_id="x-1")
    payload = json.loads(ws.sent[0])
    # ISO formatted datetime.
    assert "2026-05-24" in payload["data"]["timestamp"]


@pytest.mark.parametrize("kind", [
    "bar_tick", "account_update", "bot_intent",
    "fill", "risk_decision", "bot_state_change",
])
async def test_all_canonical_kinds_serialize(kind: str) -> None:
    bc = WebSocketBroadcaster()
    ws = _FakeWS()
    await bc.register(ws)
    kw: dict[str, Any] = {"bot": "alpha"}
    if kind == "bar_tick":
        kw["symbol"] = "MNQH26"
        kw["bar"] = {
            "ts": datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
            "o": 1.0, "h": 1.0, "low": 1.0, "c": 1.0, "v": 1,
        }
    elif kind == "account_update":
        kw.update(
            state="ARMED_WAITING", equity=50_000.0, balance=50_000.0,
            realized_pnl_today=0.0, unrealized_pnl=0.0, high_water=50_000.0,
            distance_to_mll=2_000.0, distance_to_target=3_000.0,
            contracts_open=0, dll_remaining=1_000.0,
        )
    elif kind == "bot_intent":
        kw.update(watching_for="x", schedule_open=True,
                  next_window_opens_in_seconds=None,
                  max_trades_remaining=1)
    elif kind == "fill":
        kw.update(symbol="MNQH26", side="BUY", quantity=1,
                  fill_price=18_000.0,
                  timestamp=datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
                  client_order_id="x-1")
    elif kind == "risk_decision":
        kw.update(approved=True, rule=None, reason=None,
                  timestamp=datetime(2026, 5, 24, 14, 0, tzinfo=UTC))
    elif kind == "bot_state_change":
        kw.update(from_state="ARMED_WAITING", to_state="IN_TRADE",
                  reason="fill", timestamp=datetime(2026, 5, 24, 14, 0, tzinfo=UTC))
    await bc.receive(kind, **kw)
    payload = json.loads(ws.sent[0])
    assert payload["kind"] == kind
