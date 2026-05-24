"""Plan 22 T3 — Strategy.teardown() lifecycle hook on FleetRuntime.

Verifies:
  - FleetRuntime calls teardown() on a strategy that has the method.
  - A strategy without teardown() is skipped without error (Plan 11 baseline).
  - Teardown raising does NOT crash the fleet (logged + swallowed).
  - SignalStrategy.teardown() calls stop() (pump task is cancelled).
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.observability.bus import NoopTelemetryBus
from bot.runtime.fleet.registry import BotRegistry, ResolvedBot
from bot.runtime.fleet.runtime import FleetRuntime
from bot.runtime.fleet.spec import BotSpec
from bot.signals.fixture_source import FixtureSignalSource
from bot.signals.source import SignalEvent
from bot.strategy.signal_strategy import SignalStrategy
from bot.types import AccountState, Bar, OrderIntent


def _bars(symbol: str, n: int) -> list[Bar]:
    start = datetime(2026, 5, 24, 14, 0, tzinfo=UTC)
    return [
        Bar(
            symbol=symbol, open=20_100.0, high=20_100.0, low=20_100.0,
            close=20_100.0, volume=100,
            timestamp=start + timedelta(minutes=i), interval="1m",
        )
        for i in range(n)
    ]


class _StaticBarSource:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def subscribe(self) -> AsyncIterator[Bar]:
        for b in self._bars:
            yield b


class _StrategyWithTeardown:
    """Records whether teardown() ran. Used to assert FleetRuntime calls it."""

    def __init__(self) -> None:
        self.teardown_called = False

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        _ = (bar, state)
        return []

    def teardown(self) -> None:
        self.teardown_called = True


class _StrategyAsyncTeardown:
    """Async teardown — runtime awaits coroutines."""

    def __init__(self) -> None:
        self.teardown_called = False

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        _ = (bar, state)
        return []

    async def teardown(self) -> None:
        self.teardown_called = True


class _StrategyFailingTeardown:
    """Teardown raises — fleet must swallow + continue."""

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        _ = (bar, state)
        return []

    def teardown(self) -> None:
        raise RuntimeError("teardown explosion")


class _StrategyNoTeardown:
    """No teardown method — hasattr returns False, runtime skips."""

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        _ = (bar, state)
        return []


def _resolve_with(strategy: Any, tmp_path: Path, broker: Any) -> ResolvedBot:
    """Build a ResolvedBot whose strategy is the supplied instance."""
    # `efa_standard` + `always` is the only combination this test can use:
    # combine_intraday + always is forbidden by live_only_guard, and
    # market_hours adds CT-clock complexity we don't need for a teardown test.
    spec = BotSpec(
        name="teardown_test",
        enabled=True,
        symbol="MNQ",
        strategy_id="custom",
        strategy_params={},
        risk_policy="efa_standard",
        risk_params={"mll_amount": 2_000},
        schedule_type="always",
        schedule_params={},
        journal_path=tmp_path / "teardown.db",
    )
    reg = BotRegistry()

    def _factory(params: dict[str, Any]) -> Any:
        _ = params
        return strategy

    reg.register_strategy("custom", _factory)
    return reg.build(spec, broker=broker)


@pytest.mark.asyncio
async def test_fleet_calls_teardown_on_strategy_that_has_it(
    tmp_path: Path,
) -> None:
    sim = SimExecutionClient()
    await sim.connect()
    strategy = _StrategyWithTeardown()
    resolved = _resolve_with(strategy, tmp_path, sim)

    fleet = FleetRuntime(
        bots=[resolved], broker=sim,
        bar_source_factory=lambda spec: _StaticBarSource(_bars("MNQ", 3)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    await fleet.run()

    assert strategy.teardown_called is True


@pytest.mark.asyncio
async def test_fleet_awaits_async_teardown(tmp_path: Path) -> None:
    sim = SimExecutionClient()
    await sim.connect()
    strategy = _StrategyAsyncTeardown()
    resolved = _resolve_with(strategy, tmp_path, sim)

    fleet = FleetRuntime(
        bots=[resolved], broker=sim,
        bar_source_factory=lambda spec: _StaticBarSource(_bars("MNQ", 3)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    await fleet.run()

    assert strategy.teardown_called is True


@pytest.mark.asyncio
async def test_fleet_skips_teardown_when_strategy_has_none(
    tmp_path: Path,
) -> None:
    sim = SimExecutionClient()
    await sim.connect()
    strategy = _StrategyNoTeardown()
    resolved = _resolve_with(strategy, tmp_path, sim)

    fleet = FleetRuntime(
        bots=[resolved], broker=sim,
        bar_source_factory=lambda spec: _StaticBarSource(_bars("MNQ", 3)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    results = await fleet.run()
    # No exception, bot completed cleanly.
    assert results["teardown_test"].error is None


@pytest.mark.asyncio
async def test_failing_teardown_does_not_crash_fleet(tmp_path: Path) -> None:
    """A bot's teardown explosion must NOT propagate as a fleet failure."""
    sim = SimExecutionClient()
    await sim.connect()
    strategy = _StrategyFailingTeardown()
    resolved = _resolve_with(strategy, tmp_path, sim)

    fleet = FleetRuntime(
        bots=[resolved], broker=sim,
        bar_source_factory=lambda spec: _StaticBarSource(_bars("MNQ", 3)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    results = await fleet.run()
    # The loop itself completed fine; teardown raised but was swallowed.
    assert results["teardown_test"].error is None
    assert results["teardown_test"].bars_processed == 3


@pytest.mark.asyncio
async def test_signal_strategy_teardown_cancels_pump(tmp_path: Path) -> None:
    """SignalStrategy.teardown() must call stop() — pump task is cancelled."""
    _ = tmp_path
    source = FixtureSignalSource([
        SignalEvent(
            received_at=datetime(2026, 5, 24, 13, 59, tzinfo=UTC),
            symbol="MNQ", side="BUY", qty=1,
            limit_price=20_100.0, stop_loss=None, take_profit=None,
            raw_text="BUY MNQ", source_id="sig-1",
        ),
    ])
    strat = SignalStrategy(symbol="MNQ", source=source)
    strat.setup()
    assert strat._pump_task is not None
    pump = strat._pump_task

    await strat.teardown()

    assert strat._pump_task is None
    assert pump.done()
