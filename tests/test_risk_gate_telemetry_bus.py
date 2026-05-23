"""Plan 7 T9: TopstepRiskGate wired to TelemetryBus.

Gate previously took anything satisfying the inline `_Telemetry` Protocol
(`alert(kind, **kw) -> None`). T9 lets it also accept a `TelemetryBus` so
denials + force-flatten events fan out to subscribers (Journal, JSONLogger,
Telegram). The `_Telemetry` Protocol is preserved — TelemetryBus duck-types
through it.

A `force_flatten_now` triggers a `FORCE_FLATTEN` alert; with a subscribed sink,
that alert must reach the sink. We also exercise the consistency-rule warn
path (the only sync `telemetry.alert` call inside _check_consistency).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from bot.observability.bus import NoopTelemetryBus, TelemetryBus
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.types import AccountState, Bracket, OrderIntent


@dataclass
class _RecordingSink:
    received: list[tuple[str, dict]] = field(default_factory=list)

    async def receive(self, kind: str, **kw: object) -> None:
        self.received.append((kind, dict(kw)))


class _NoopNews:
    def in_window(self, now: datetime) -> bool:
        return False

    def max_position_during_window(self) -> int:
        return 1


class _MockExec:
    def __init__(self) -> None:
        self.cancelled = False
        self.closed = False

    async def cancel_all(self, symbol: str) -> None:
        self.cancelled = True

    async def close_all_positions(self) -> None:
        self.closed = True


def _gate(*, telemetry: object) -> TopstepRiskGate:
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    return TopstepRiskGate(
        policy=policy,
        news_calendar=_NoopNews(),
        execution_client=_MockExec(),
        telemetry=telemetry,  # type: ignore[arg-type]
        config=cfg,
    )


def _now() -> datetime:
    return datetime(2026, 5, 22, 14, 30, tzinfo=UTC)


async def test_gate_accepts_telemetry_bus():
    # Bus is structurally compatible with _Telemetry (has alert(kind, **kw))
    bus = TelemetryBus()
    gate = _gate(telemetry=bus)
    assert gate.telemetry is bus


async def test_gate_accepts_noop_bus():
    bus = NoopTelemetryBus()
    gate = _gate(telemetry=bus)
    assert gate.telemetry is bus


async def test_gate_accepts_legacy_telemetry_protocol():
    # Legacy callers can still pass anything with sync alert(kind, **kw).
    class _Legacy:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def alert(self, kind: str, **kw: object) -> None:
            self.calls.append((kind, dict(kw)))

    legacy = _Legacy()
    gate = _gate(telemetry=legacy)
    assert gate.telemetry is legacy


async def test_force_flatten_alert_fans_out_to_sink():
    bus = TelemetryBus()
    sink = _RecordingSink()
    bus.subscribe(sink)
    gate = _gate(telemetry=bus)

    await gate.force_flatten_now(reason="MLL_EQUITY_TOUCH")

    # Bus's alert -> create_task; await any pending fan-out tasks.
    import asyncio
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)

    kinds = [k for (k, _) in sink.received]
    assert "FORCE_FLATTEN" in kinds


async def test_consistency_warn_routes_through_bus():
    # Set up state so rule 6 trips in soft mode (warn-only).
    bus = TelemetryBus()
    sink = _RecordingSink()
    bus.subscribe(sink)

    cfg = RiskConfig(env="backtest", accounts_managed=1, consistency_mode="soft")
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)

    class _BiasedJournal:
        # 60% of profit target on a single day -> ratio > 50% -> warn.
        def best_day_pnl_so_far(self) -> float:
            return 1_800.0  # > 50% of remaining target

        def net_pnl_so_far(self) -> float:
            return 0.0

    gate = TopstepRiskGate(
        policy=policy,
        news_calendar=_NoopNews(),
        execution_client=_MockExec(),
        telemetry=bus,
        config=cfg,
        journal_provider=_BiasedJournal(),
    )

    state = AccountState(
        equity=50_000.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=50_000.0,
        is_combine=True,
        timestamp=_now(),
    )
    intent = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="MARKET", client_order_id="cn-1",
        timestamp=_now(),
        bracket=Bracket(stop_loss_ticks=20, take_profit_ticks=40),
    )
    gate.approve_or_deny(intent, state)

    # alert() in sync code from inside a running loop schedules a task.
    import asyncio
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)

    kinds = [k for (k, _) in sink.received]
    assert "CONSISTENCY_50PCT_EXCEEDED" in kinds


@pytest.mark.parametrize("telemetry_factory", [TelemetryBus, NoopTelemetryBus])
async def test_gate_constructs_with_any_telemetry(telemetry_factory):
    # Construction with both bus types must succeed and basic deny path still works.
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    gate = TopstepRiskGate(
        policy=policy,
        news_calendar=_NoopNews(),
        execution_client=_MockExec(),
        telemetry=telemetry_factory(),
        config=cfg,
    )
    # Smoke-deny: bracket-less open order
    state = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0, high_water_equity=50_000.0,
        is_combine=True, timestamp=_now(),
    )
    intent = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="MARKET", client_order_id="x",
        timestamp=_now(),
    )
    from bot.types import OrderDenied
    d = gate.approve_or_deny(intent, state)
    assert isinstance(d, OrderDenied)
