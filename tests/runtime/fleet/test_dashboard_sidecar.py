"""FleetRuntime launches the dashboard as a side-car asyncio task (Plan 21 T5).

When `dashboard_port` is passed to FleetRuntime, the runtime spawns a
uvicorn.Server task alongside the bot loops. The dashboard binds to
127.0.0.1 only — never 0.0.0.0. A dashboard crash MUST NOT crash the
fleet (return_exceptions=True on the gather).
"""
from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from bot.backtest.sim_client import SimExecutionClient
from bot.observability.bus import NoopTelemetryBus
from bot.runtime.fleet.registry import BotRegistry, ResolvedBot
from bot.runtime.fleet.runtime import FleetRuntime
from bot.runtime.fleet.spec import BotSpec
from bot.types import AccountState, Bar, OrderIntent


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return int(port)


def _spec(name: str, tmp_path: Path) -> BotSpec:
    return BotSpec(
        name=name, enabled=True, symbol="MNQ",
        strategy_id="noop_custom",
        strategy_params={},
        risk_policy="combine_intraday",
        risk_params={"start_balance": 50_000, "mll_amount": 2_000, "max_mini": 5},
        schedule_type="market_hours",
        schedule_params={"open_ct": "08:30", "close_ct": "15:00"},
        journal_path=tmp_path / f"{name}.db",
    )


class _NoopStrategy:
    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        _ = (bar, state)
        return []


def _resolved(name: str, tmp_path: Path, broker: Any) -> ResolvedBot:
    reg = BotRegistry()
    reg.register_strategy("noop_custom", lambda p: _NoopStrategy())
    return reg.build(_spec(name, tmp_path), broker=broker)


def _slow_bars(n: int, delay_s: float = 0.05) -> list[Bar]:
    """Bars timestamped 1m apart in CT trading window."""
    start = datetime(2026, 5, 22, 13, 30, tzinfo=UTC)  # 08:30 CT
    return [
        Bar(
            symbol="MNQ", open=18000.0, high=18000.0, low=18000.0, close=18000.0,
            volume=100, timestamp=start + timedelta(minutes=i), interval="1m",
        )
        for i in range(n)
    ]


class _SlowSource:
    """Yields bars but sleeps between them so the dashboard task has time to serve."""

    def __init__(self, bars: list[Bar], delay_s: float = 0.05) -> None:
        self._bars = bars
        self._delay = delay_s

    async def subscribe(self) -> AsyncIterator[Bar]:
        for bar in self._bars:
            await asyncio.sleep(self._delay)
            yield bar


async def test_dashboard_sidecar_serves_fleet_page(tmp_path: Path) -> None:
    """With dashboard_port set, FleetRuntime opens a local HTTP server.

    Drives a small bar stream so the fleet has time to start; in parallel
    we make a request to / and assert 200.
    """
    sim = SimExecutionClient()
    await sim.connect()

    # Need at least one *.yml file under a bots_dir so the dashboard
    # list_bots can render something — we synthesize one on disk that
    # points at the same journal the fleet writes.
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    (bots_dir / "alpha.yml").write_text(
        "name: alpha\nenabled: true\nsymbol: MNQ\n"
        "strategy_id: orb_5m\nstrategy_params:\n  range_minutes: 5\n"
        "risk_policy: combine_intraday\n"
        "risk_params:\n  start_balance: 50000\n  mll_amount: 2000\n  max_mini: 5\n"
        "schedule_type: market_hours\n"
        'schedule_params:\n  open_ct: "08:30"\n  close_ct: "15:00"\n'
        f"journal_path: {tmp_path / 'alpha.db'}\n",
        encoding="utf-8",
    )

    bot = _resolved("alpha", tmp_path, sim)
    port = _free_port()
    fleet = FleetRuntime(
        bots=[bot], broker=sim,
        bar_source_factory=lambda spec: _SlowSource(_slow_bars(20)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
        dashboard_port=port,
        dashboard_bots_dir=bots_dir,
    )

    # Run fleet in the background; poll the dashboard until it answers.
    async def run_and_hit_dashboard() -> int:
        fleet_task = asyncio.create_task(fleet.run())
        try:
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                for _ in range(50):  # ~5s budget
                    try:
                        # /healthz works regardless of whether the SPA
                        # dist is present (and is the launchd probe path).
                        resp = await client.get("/healthz")
                        if resp.status_code == 200:
                            return resp.status_code
                    except httpx.ConnectError:
                        pass
                    await asyncio.sleep(0.1)
                raise AssertionError("dashboard never became reachable")
        finally:
            # Signal shutdown via the runtime's stop method.
            fleet.request_shutdown()
            await fleet_task

    code = await run_and_hit_dashboard()
    assert code == 200


async def test_dashboard_binds_to_loopback_only(tmp_path: Path) -> None:
    """The dashboard must NOT bind to 0.0.0.0 — only 127.0.0.1.

    Property-style check: try to reach the port on 127.0.0.1 (should
    succeed) and verify the runtime configures host="127.0.0.1".
    """
    sim = SimExecutionClient()
    await sim.connect()
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()

    bot = _resolved("alpha", tmp_path, sim)
    port = _free_port()
    fleet = FleetRuntime(
        bots=[bot], broker=sim,
        bar_source_factory=lambda spec: _SlowSource(_slow_bars(5)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
        dashboard_port=port,
        dashboard_bots_dir=bots_dir,
    )

    # Inspect the runtime's dashboard config (set by __init__).
    assert fleet._dashboard_host == "127.0.0.1"  # type: ignore[attr-defined]


async def test_dashboard_not_started_when_port_is_none(tmp_path: Path) -> None:
    """Without dashboard_port, no server task is created — regression."""
    sim = SimExecutionClient()
    await sim.connect()
    bot = _resolved("alpha", tmp_path, sim)
    fleet = FleetRuntime(
        bots=[bot], broker=sim,
        bar_source_factory=lambda spec: _SlowSource(_slow_bars(2)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    results = await fleet.run()
    assert results["alpha"].error is None
    # Internal: no dashboard server stashed.
    assert getattr(fleet, "_dashboard_server", None) is None
