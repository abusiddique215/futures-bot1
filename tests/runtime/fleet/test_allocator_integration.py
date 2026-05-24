"""FleetRuntime + FleetAllocator integration tests (Plan 21 T2).

Wires the allocator into the per-bot LiveTradingLoop so cross-bot caps
are enforced after each bot's own risk gate. Also covers the new
Strategy.setup() lifecycle hook the runtime calls before each bot's
event loop starts (production wiring for SignalStrategy's pump task).
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bot.backtest.sim_client import SimExecutionClient
from bot.journal.journal import Journal
from bot.markets.registry import get_market
from bot.observability.bus import NoopTelemetryBus
from bot.runtime.fleet.allocator import FleetAllocator
from bot.runtime.fleet.registry import BotRegistry, ResolvedBot
from bot.runtime.fleet.runtime import FleetRuntime
from bot.runtime.fleet.spec import BotSpec
from bot.types import AccountState, Bar, Bracket, OrderIntent


def _spec(name: str, tmp_path: Path, *, max_mini: int = 10) -> BotSpec:
    # combine_intraday with a generous max_mini so per-bot MAX_POSITION doesn't
    # fire before the fleet-wide FLEET_POSITION_CAP. The whole point of these
    # tests is to drive the allocator path, not the per-bot gate.
    return BotSpec(
        name=name, enabled=True, symbol="MNQ",
        strategy_id="custom",
        strategy_params={},
        risk_policy="combine_intraday",
        risk_params={
            "start_balance": 50_000,
            "mll_amount": 2_000,
            "max_mini": max_mini,
        },
        schedule_type="market_hours",
        schedule_params={"open_ct": "08:30", "close_ct": "15:00"},
        journal_path=tmp_path / f"{name}.db",
    )


class _EmitBuyOnce:
    """Single-fire strategy: emits exactly one BUY MNQ intent on the first bar."""

    def __init__(self, name: str, qty: int) -> None:
        self._name = name
        self._qty = qty
        self._fired = False

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        _ = state
        if self._fired:
            return []
        self._fired = True
        return [OrderIntent(
            symbol="MNQ", side="BUY", quantity=self._qty,
            order_type="MARKET",
            client_order_id=f"{self._name}-buy-1",
            timestamp=bar.timestamp,
            # Bracket required so the risk gate's STOP_REQUIRED sub-check
            # passes for open-increasing intents.
            bracket=Bracket(stop_loss_ticks=20, take_profit_ticks=20),
        )]


class _StaticSource:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def subscribe(self) -> AsyncIterator[Bar]:
        for bar in self._bars:
            yield bar


def _bars(n: int) -> list[Bar]:
    """In-window MNQ 1-min bars (13:30 UTC = 08:30 CT)."""
    start = datetime(2026, 5, 22, 13, 30, tzinfo=UTC)
    return [
        Bar(
            symbol="MNQ", open=18000.0, high=18000.0, low=18000.0, close=18000.0,
            volume=100, timestamp=start + timedelta(minutes=i), interval="1m",
        )
        for i in range(n)
    ]


def _resolved(
    name: str, tmp_path: Path, broker: Any, strategy: Any,
) -> ResolvedBot:
    reg = BotRegistry()
    reg.register_strategy("custom", lambda p: strategy)
    return reg.build(_spec(name, tmp_path), broker=broker)


async def test_default_no_allocator_unchanged_behavior(tmp_path: Path) -> None:
    """FleetRuntime without an allocator runs exactly like before — regression."""
    sim = SimExecutionClient()
    await sim.connect()
    bot = _resolved("a", tmp_path, sim, _EmitBuyOnce("a", 3))

    fleet = FleetRuntime(
        bots=[bot], broker=sim,
        bar_source_factory=lambda spec: _StaticSource(_bars(3)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    results = await fleet.run()
    assert results["a"].error is None
    assert results["a"].bars_processed == 3

    j = await Journal.connect(str(tmp_path / "a.db"))
    cur = await j._conn.execute("SELECT COUNT(*) FROM fills")  # type: ignore[attr-defined]
    (count,) = await cur.fetchone()  # type: ignore[misc]
    await cur.close()
    await j.close()
    assert count == 1, "single fill expected"


async def test_allocator_caps_second_bot_intent(tmp_path: Path) -> None:
    """Bot A approved for +50 MNQ; Bot B's +1 MNQ is denied by the allocator.

    Per-bot gates each approve the intent (within EFA limits); the
    cross-bot cap is what catches the over-allocation.
    """
    sim = SimExecutionClient()
    await sim.connect()
    bot_a = _resolved("a", tmp_path, sim, _EmitBuyOnce("a", 50))
    bot_b = _resolved("b", tmp_path, sim, _EmitBuyOnce("b", 1))
    alloc = FleetAllocator(account_max_mini=5, market_lookup=get_market)

    fleet = FleetRuntime(
        bots=[bot_a, bot_b], broker=sim,
        bar_source_factory=lambda spec: _StaticSource(_bars(3)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
        allocator=alloc,
    )
    results = await fleet.run()
    assert results["a"].error is None
    assert results["b"].error is None

    # Bot A: 1 risk_decisions approved=1 (per-bot + allocator both approved).
    # Bot B: 1 risk_decisions approved=0, rule=FLEET_POSITION_CAP.
    j_a = await Journal.connect(str(tmp_path / "a.db"))
    j_b = await Journal.connect(str(tmp_path / "b.db"))
    try:
        cur = await j_a._conn.execute(  # type: ignore[attr-defined]
            "SELECT approved, rule FROM risk_decisions WHERE quantity=50",
        )
        rows_a = await cur.fetchall()
        await cur.close()
        cur = await j_b._conn.execute(  # type: ignore[attr-defined]
            "SELECT approved, rule FROM risk_decisions WHERE quantity=1",
        )
        rows_b = await cur.fetchall()
        await cur.close()
    finally:
        await j_a.close()
        await j_b.close()

    assert rows_a == [(1, None)], f"bot a expected single approval, got {rows_a}"
    assert rows_b == [(0, "FLEET_POSITION_CAP")], (
        f"bot b expected FLEET_POSITION_CAP denial, got {rows_b}"
    )


class _SetupSpy:
    """Strategy with a setup() hook the runtime should call before run starts."""

    def __init__(self) -> None:
        self.setup_called = False

    def setup(self) -> None:
        self.setup_called = True

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        _ = (bar, state)
        return []


async def test_fleet_calls_strategy_setup_before_loop_starts(tmp_path: Path) -> None:
    """FleetRuntime invokes strategy.setup() (if present) before LiveTradingLoop.

    Production wiring for SignalStrategy — its setup() calls self.start() to
    spawn the Discord pump task. Without this, flipping lux_bot.yml's
    enabled flag was a silent no-op.
    """
    sim = SimExecutionClient()
    await sim.connect()
    spy = _SetupSpy()
    bot = _resolved("a", tmp_path, sim, spy)

    fleet = FleetRuntime(
        bots=[bot], broker=sim,
        bar_source_factory=lambda spec: _StaticSource(_bars(1)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    await fleet.run()
    assert spy.setup_called, "FleetRuntime must call Strategy.setup() before loop"


class _NoSetupStrategy:
    """Strategy WITHOUT a setup method — must still work (backward compat)."""

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        _ = (bar, state)
        return []


async def test_fleet_tolerates_strategy_without_setup_hook(tmp_path: Path) -> None:
    """Strategies without a setup() method run normally (Protocol fallback)."""
    sim = SimExecutionClient()
    await sim.connect()
    bot = _resolved("a", tmp_path, sim, _NoSetupStrategy())

    fleet = FleetRuntime(
        bots=[bot], broker=sim,
        bar_source_factory=lambda spec: _StaticSource(_bars(1)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    results = await fleet.run()
    assert results["a"].error is None
