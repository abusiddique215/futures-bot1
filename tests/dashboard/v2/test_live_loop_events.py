"""Tests for LiveTradingLoop's new per-bar telemetry events (Plan 23 T3).

LiveTradingLoop emits, on every bar:
  bar_tick          — OHLCV + bot identity
  account_update    — equity / balance / pnl + derived distance fields + state
  bot_intent        — extract_intent() output

A capturing TelemetryBus sink records every event the loop publishes and
the tests assert on counts + payload shape.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.tracker import AccountStateTracker
from bot.journal.journal import Journal
from bot.observability.bus import TelemetryBus
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.runtime.bar_source import SimBarSource
from bot.runtime.fleet.schedule import AlwaysOn
from bot.runtime.live_loop import LiveTradingLoop
from bot.strategy.orb import OpeningRangeBreakoutStrategy, ORBProfile
from bot.types import AccountState, Bar, Bracket, OrderIntent


class _NoopNews:
    def in_window(self, now: datetime) -> bool:
        _ = now
        return False

    def max_position_during_window(self) -> int:
        return 1


class _CapturingSink:
    """Records every (kind, kw) the bus dispatches."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def receive(self, kind: str, **kw: object) -> None:
        self.events.append((kind, dict(kw)))

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [kw for k, kw in self.events if k == kind]


async def _drain(bus: TelemetryBus) -> None:
    """Wait for every in-flight bus fan-out task to complete.

    TelemetryBus.alert(...) is fire-and-forget when a loop is running — it
    schedules a task and returns. Tests must drain those tasks before
    asserting on captured events.
    """
    import asyncio as _asyncio
    pending = [t for t in bus._inflight if not t.done()]
    if pending:
        await _asyncio.gather(*pending)


class _NoopStrategy:
    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        _ = (bar, state)
        return []


class _BuyOnceStrategy:
    def __init__(self) -> None:
        self._i = 0

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        _ = state
        i = self._i
        self._i += 1
        if i == 0:
            return [OrderIntent(
                symbol="MNQ", side="BUY", quantity=1,
                order_type="MARKET", client_order_id="open-1",
                timestamp=bar.timestamp,
                bracket=Bracket(stop_loss_ticks=40, take_profit_ticks=80),
            )]
        return []


def _bars(n: int) -> list[Bar]:
    start = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    return [
        Bar(
            symbol="MNQ", open=100.0, high=100.5, low=99.5, close=100.0,
            volume=10, timestamp=start + timedelta(minutes=i), interval="1m",
        )
        for i in range(n)
    ]


def _make_gate(sim: SimExecutionClient, bus: TelemetryBus) -> TopstepRiskGate:
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    return TopstepRiskGate(
        policy=policy,
        news_calendar=_NoopNews(),
        execution_client=sim,
        telemetry=bus,
        config=cfg,
        symbol="MNQ",
    )


@pytest.fixture
async def journal(tmp_path: Path) -> Any:
    j = await Journal.connect(str(tmp_path / "j.db"))
    await j.apply_migrations()
    try:
        yield j
    finally:
        await j.close()


async def test_emits_one_bar_tick_per_bar(tmp_path: Path, journal: Journal) -> None:
    sink = _CapturingSink()
    bus = TelemetryBus()
    bus.subscribe(sink)
    sim = SimExecutionClient()
    gate = _make_gate(sim, bus)
    tracker = AccountStateTracker(50_000.0, is_combine=True)
    loop = LiveTradingLoop(
        strategy=_NoopStrategy(), gate=gate, tracker=tracker, broker=sim,
        journal=journal, telemetry=bus,
        heartbeat_path=tmp_path / "hb", symbol="MNQ", schedule=AlwaysOn(),
        bot_name="alpha",
    )
    await loop.run(SimBarSource(_bars(5)), max_bars=5)
    await _drain(bus)
    bars = sink.of_kind("bar_tick")
    assert len(bars) == 5
    first = bars[0]
    assert first["bot"] == "alpha"
    assert first["symbol"] == "MNQ"
    assert "bar" in first
    bar_payload = first["bar"]
    assert bar_payload["o"] == 100.0
    assert bar_payload["c"] == 100.0


async def test_emits_one_account_update_per_bar(
    tmp_path: Path, journal: Journal,
) -> None:
    sink = _CapturingSink()
    bus = TelemetryBus()
    bus.subscribe(sink)
    sim = SimExecutionClient()
    gate = _make_gate(sim, bus)
    tracker = AccountStateTracker(50_000.0, is_combine=True)
    loop = LiveTradingLoop(
        strategy=_NoopStrategy(), gate=gate, tracker=tracker, broker=sim,
        journal=journal, telemetry=bus,
        heartbeat_path=tmp_path / "hb", symbol="MNQ", schedule=AlwaysOn(),
        bot_name="alpha",
    )
    await loop.run(SimBarSource(_bars(3)), max_bars=3)
    await _drain(bus)
    updates = sink.of_kind("account_update")
    assert len(updates) == 3
    u = updates[0]
    # Required risk-header fields.
    for f in (
        "bot", "state", "equity", "balance",
        "realized_pnl_today", "unrealized_pnl",
        "high_water", "distance_to_mll", "distance_to_target",
        "contracts_open", "dll_remaining",
    ):
        assert f in u, f
    assert u["bot"] == "alpha"
    assert u["balance"] == 50_000.0
    assert u["equity"] == pytest.approx(50_000.0)
    assert u["contracts_open"] == 0
    assert u["state"] == "ARMED_WAITING"
    assert u["distance_to_mll"] > 0


async def test_emits_one_bot_intent_per_bar(
    tmp_path: Path, journal: Journal,
) -> None:
    sink = _CapturingSink()
    bus = TelemetryBus()
    bus.subscribe(sink)
    sim = SimExecutionClient()
    gate = _make_gate(sim, bus)
    tracker = AccountStateTracker(50_000.0, is_combine=True)
    strat = OpeningRangeBreakoutStrategy(
        ORBProfile(symbol="MNQ", range_minutes=5),
    )
    loop = LiveTradingLoop(
        strategy=strat, gate=gate, tracker=tracker, broker=sim,
        journal=journal, telemetry=bus,
        heartbeat_path=tmp_path / "hb", symbol="MNQ", schedule=AlwaysOn(),
        bot_name="alpha",
    )
    await loop.run(SimBarSource(_bars(4)), max_bars=4)
    await _drain(bus)
    intents = sink.of_kind("bot_intent")
    assert len(intents) == 4
    ev = intents[0]
    assert ev["bot"] == "alpha"
    assert "watching_for" in ev
    assert "schedule_open" in ev
    assert ev["schedule_open"] is True
    assert ev["next_window_opens_in_seconds"] is None  # AlwaysOn


async def test_bot_state_in_trade_after_fill(
    tmp_path: Path, journal: Journal,
) -> None:
    sink = _CapturingSink()
    bus = TelemetryBus()
    bus.subscribe(sink)
    sim = SimExecutionClient()
    gate = _make_gate(sim, bus)
    tracker = AccountStateTracker(50_000.0, is_combine=True)
    loop = LiveTradingLoop(
        strategy=_BuyOnceStrategy(), gate=gate, tracker=tracker, broker=sim,
        journal=journal, telemetry=bus,
        heartbeat_path=tmp_path / "hb", symbol="MNQ", schedule=AlwaysOn(),
        bot_name="alpha",
    )
    await loop.run(SimBarSource(_bars(3)), max_bars=3)
    await _drain(bus)
    updates = sink.of_kind("account_update")
    # Bar 0: BUY executes, fill recorded after; account_update at end of bar 0
    # already sees contracts_open=1 (record_fill before snapshot).
    assert updates[0]["state"] == "IN_TRADE"
    assert updates[0]["contracts_open"] == 1


async def test_emits_fill_event_on_fill(
    tmp_path: Path, journal: Journal,
) -> None:
    sink = _CapturingSink()
    bus = TelemetryBus()
    bus.subscribe(sink)
    sim = SimExecutionClient()
    gate = _make_gate(sim, bus)
    tracker = AccountStateTracker(50_000.0, is_combine=True)
    loop = LiveTradingLoop(
        strategy=_BuyOnceStrategy(), gate=gate, tracker=tracker, broker=sim,
        journal=journal, telemetry=bus,
        heartbeat_path=tmp_path / "hb", symbol="MNQ", schedule=AlwaysOn(),
        bot_name="alpha",
    )
    await loop.run(SimBarSource(_bars(2)), max_bars=2)
    await _drain(bus)
    fills = sink.of_kind("fill")
    assert len(fills) == 1
    f = fills[0]
    assert f["bot"] == "alpha"
    assert f["side"] == "BUY"
    assert f["quantity"] == 1
    assert f["client_order_id"] == "open-1"


async def test_all_event_payloads_json_serializable(
    tmp_path: Path, journal: Journal,
) -> None:
    """Each emitted event must round-trip through json.dumps with default=str."""
    import json
    sink = _CapturingSink()
    bus = TelemetryBus()
    bus.subscribe(sink)
    sim = SimExecutionClient()
    gate = _make_gate(sim, bus)
    tracker = AccountStateTracker(50_000.0, is_combine=True)
    loop = LiveTradingLoop(
        strategy=_BuyOnceStrategy(), gate=gate, tracker=tracker, broker=sim,
        journal=journal, telemetry=bus,
        heartbeat_path=tmp_path / "hb", symbol="MNQ", schedule=AlwaysOn(),
        bot_name="alpha",
    )
    await loop.run(SimBarSource(_bars(2)), max_bars=2)
    await _drain(bus)
    for kind, kw in sink.events:
        s = json.dumps({"kind": kind, "data": kw}, default=str)
        assert isinstance(s, str)
