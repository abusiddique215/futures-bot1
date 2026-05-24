"""FleetRuntime — concurrent per-bot LiveTradingLoop orchestration."""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bot.backtest.sim_client import SimExecutionClient
from bot.observability.bus import NoopTelemetryBus
from bot.runtime.fleet.registry import BotRegistry, ResolvedBot
from bot.runtime.fleet.runtime import BotResult, FleetRuntime
from bot.runtime.fleet.spec import BotSpec
from bot.types import AccountState, Bar, OrderIntent


def _make_spec(name: str) -> BotSpec:
    return BotSpec(
        name=name, enabled=True, symbol="MNQ",
        strategy_id="orb_5m",
        strategy_params={"range_minutes": 5},
        risk_policy="combine_intraday",
        risk_params={"start_balance": 50_000, "mll_amount": 2_000, "max_mini": 5},
        schedule_type="always", schedule_params={},
        journal_path=Path(f"state/journal_{name}.db"),  # unused; we override
    )


def _bars(n: int, start_offset_minutes: int = 0) -> list[Bar]:
    start = datetime(2026, 5, 22, 19, 0, tzinfo=UTC) + timedelta(minutes=start_offset_minutes)
    return [
        Bar(
            symbol="MNQ", open=18000.0, high=18000.0, low=18000.0, close=18000.0,
            volume=100, timestamp=start + timedelta(minutes=i), interval="1m",
        )
        for i in range(n)
    ]


class _NoopStrategy:
    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        return []


def _resolved(name: str, tmp_path: Path, broker: Any) -> ResolvedBot:
    reg = BotRegistry()
    reg.register_strategy("orb_5m", lambda p: _NoopStrategy())
    spec = _make_spec(name)
    spec_with_path = BotSpec(
        **{**spec.__dict__, "journal_path": tmp_path / f"{name}.db"},
    )
    return reg.build(spec_with_path, broker=broker)


class _StaticSource:
    """Async source yielding a pre-built bar list."""

    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def subscribe(self) -> AsyncIterator[Bar]:
        for bar in self._bars:
            yield bar


class _FailingSource:
    """Yields bars then raises mid-stream."""

    def __init__(self, bars: list[Bar], fail_after: int) -> None:
        self._bars = bars
        self._fail_after = fail_after

    async def subscribe(self) -> AsyncIterator[Bar]:
        for i, bar in enumerate(self._bars):
            if i >= self._fail_after:
                raise RuntimeError("synthetic-source-explosion")
            yield bar


async def test_three_bots_run_to_completion(tmp_path: Path) -> None:
    sim = SimExecutionClient()
    await sim.connect()
    bots = [_resolved(n, tmp_path, sim) for n in ("alpha", "beta", "gamma")]

    def source_for(spec: BotSpec) -> Any:
        _ = spec
        return _StaticSource(_bars(30))

    fleet = FleetRuntime(
        bots=bots,
        broker=sim,
        bar_source_factory=source_for,
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    results = await fleet.run()
    assert set(results.keys()) == {"alpha", "beta", "gamma"}
    for name, r in results.items():
        assert r.error is None, f"{name} had error: {r.error}"
        assert r.bars_processed == 30
        # Per-bot journal file was created
        assert (tmp_path / f"{name}.db").exists()


async def test_one_bot_failure_does_not_crash_others(tmp_path: Path) -> None:
    sim = SimExecutionClient()
    await sim.connect()
    bots = [_resolved(n, tmp_path, sim) for n in ("alpha", "beta", "gamma")]

    def source_for(spec: BotSpec) -> Any:
        if spec.name == "beta":
            return _FailingSource(_bars(30), fail_after=10)
        return _StaticSource(_bars(30))

    fleet = FleetRuntime(
        bots=bots, broker=sim,
        bar_source_factory=source_for,
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    results = await fleet.run()
    assert results["alpha"].error is None
    assert results["alpha"].bars_processed == 30
    assert results["gamma"].error is None
    assert results["gamma"].bars_processed == 30
    assert results["beta"].error is not None
    assert "synthetic-source-explosion" in str(results["beta"].error)


async def test_empty_bot_list_returns_empty_dict(tmp_path: Path) -> None:
    sim = SimExecutionClient()
    await sim.connect()
    fleet = FleetRuntime(
        bots=[], broker=sim,
        bar_source_factory=lambda spec: _StaticSource([]),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    results = await fleet.run()
    assert results == {}


async def test_results_have_bot_result_type(tmp_path: Path) -> None:
    sim = SimExecutionClient()
    await sim.connect()
    bots = [_resolved("alpha", tmp_path, sim)]
    fleet = FleetRuntime(
        bots=bots, broker=sim,
        bar_source_factory=lambda s: _StaticSource(_bars(3)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    results = await fleet.run()
    r = results["alpha"]
    assert isinstance(r, BotResult)
    assert r.bars_processed == 3
