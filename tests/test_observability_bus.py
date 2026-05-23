"""Plan 7 T7: TelemetryBus fan-out + Sink Protocol.

The bus owns subscribers (Sinks). Each Sink implements `async def receive`.
The bus exposes:
  - `alert(kind, **kw)` — sync, satisfies gate.py's _Telemetry Protocol
  - `aalert(kind, **kw)` — async, awaits all sinks; tests use this for determinism

When `alert()` is called inside an async function, it `create_task`s the
fan-out; when called from sync code, it `asyncio.run()`s a fresh loop. Tests
exercise both paths.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from bot.observability.bus import NoopTelemetryBus, Sink, TelemetryBus


@dataclass
class _RecordingSink:
    received: list[tuple[str, dict]] = field(default_factory=list)

    async def receive(self, kind: str, **kw: object) -> None:
        self.received.append((kind, dict(kw)))


async def test_aalert_fans_out_to_all_sinks():
    a, b = _RecordingSink(), _RecordingSink()
    bus = TelemetryBus()
    bus.subscribe(a)
    bus.subscribe(b)

    await bus.aalert("CONSISTENCY_50PCT_EXCEEDED", best_day=100.0, target=200.0)

    assert a.received == [("CONSISTENCY_50PCT_EXCEEDED", {"best_day": 100.0, "target": 200.0})]
    assert b.received == [("CONSISTENCY_50PCT_EXCEEDED", {"best_day": 100.0, "target": 200.0})]


async def test_alert_sync_from_inside_loop_dispatches_via_create_task():
    sink = _RecordingSink()
    bus = TelemetryBus()
    bus.subscribe(sink)

    bus.alert("FORCE_FLATTEN", reason="MLL_EQUITY_TOUCH")
    # Give the scheduled task a tick to run.
    await asyncio.sleep(0)
    # Yield until all pending tasks (the fan-out task) complete.
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)

    assert sink.received == [("FORCE_FLATTEN", {"reason": "MLL_EQUITY_TOUCH"})]


def test_alert_sync_from_no_loop_runs_to_completion():
    sink = _RecordingSink()
    bus = TelemetryBus()
    bus.subscribe(sink)

    # Plain sync call — no running loop. asyncio.run drains a fresh loop.
    bus.alert("SESSION_START", note="dev")

    assert sink.received == [("SESSION_START", {"note": "dev"})]


async def test_unsubscribe_stops_delivery():
    a = _RecordingSink()
    bus = TelemetryBus()
    bus.subscribe(a)
    bus.unsubscribe(a)
    await bus.aalert("X")
    assert a.received == []


async def test_sink_exception_does_not_block_other_sinks():
    @dataclass
    class _Bad:
        async def receive(self, kind: str, **kw: object) -> None:
            raise RuntimeError("boom")

    good = _RecordingSink()
    bad = _Bad()
    bus = TelemetryBus()
    bus.subscribe(bad)
    bus.subscribe(good)

    # Should not raise — bus swallows sink errors (otherwise one bad subscriber
    # would cascade-kill the engine).
    await bus.aalert("PING")

    assert good.received == [("PING", {})]


async def test_noop_telemetry_bus_is_silent():
    # NoopTelemetryBus is the default plugged into TopstepRiskGate in T9 when
    # the driver doesn't pass one. Must satisfy the same surface.
    bus = NoopTelemetryBus()
    bus.alert("X", a=1)
    await bus.aalert("Y", b=2)
    # nothing to assert — just must not raise


async def test_sink_protocol_is_satisfied_by_recording_sink():
    # `Sink` is a Protocol; ensure a plain object with `async def receive` passes.
    sink: Sink = _RecordingSink()
    assert hasattr(sink, "receive")
