"""End-to-end smoke for the Plan 23 v2 dashboard surface.

Boots FleetRuntime with a real TelemetryBus + dashboard side-car, lets it
run a handful of bars through one synthetic bot, then hits the v2 REST
endpoints + opens a real WebSocket to confirm the wiring carries events
end-to-end (TelemetryBus → broadcaster → WS client).
"""
from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.markets.registry import get_market
from bot.observability.bus import TelemetryBus
from bot.runtime.fleet.allocator import FleetAllocator
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
        strategy_id="noop",
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


def _bars(n: int) -> list[Bar]:
    start = datetime(2026, 5, 22, 13, 30, tzinfo=UTC)
    return [
        Bar(
            symbol="MNQ", open=18000.0, high=18000.0, low=18000.0, close=18000.0,
            volume=100, timestamp=start + timedelta(minutes=i), interval="1m",
        )
        for i in range(n)
    ]


class _SlowSource:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def subscribe(self) -> AsyncIterator[Bar]:
        for bar in self._bars:
            await asyncio.sleep(0.05)
            yield bar


def _resolved(name: str, tmp_path: Path, broker: Any) -> ResolvedBot:
    reg = BotRegistry()
    reg.register_strategy("noop", lambda p: _NoopStrategy())
    return reg.build(_spec(name, tmp_path), broker=broker)


def _write_yaml(bots_dir: Path, name: str, journal: Path) -> None:
    (bots_dir / f"{name}.yml").write_text(
        f"name: {name}\nenabled: true\nsymbol: MNQ\n"
        "strategy_id: orb_5m\nstrategy_params:\n  range_minutes: 5\n"
        "risk_policy: combine_intraday\n"
        "risk_params:\n  start_balance: 50000\n  mll_amount: 2000\n  max_mini: 5\n"
        "schedule_type: market_hours\n"
        'schedule_params:\n  open_ct: "08:30"\n  close_ct: "15:00"\n'
        f"journal_path: {journal}\n",
        encoding="utf-8",
    )


async def _wait_for_first_response(client: httpx.AsyncClient, url: str) -> None:
    for _ in range(100):
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                return
        except httpx.ConnectError:
            pass
        await asyncio.sleep(0.05)
    raise AssertionError(f"v2 endpoint {url} never became reachable")


async def test_v2_dashboard_serves_api_and_ws_endpoints(tmp_path: Path) -> None:
    sim = SimExecutionClient()
    await sim.connect()
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    _write_yaml(bots_dir, "alpha", tmp_path / "alpha.db")
    bot_a = _resolved("alpha", tmp_path, sim)

    port = _free_port()
    alloc = FleetAllocator(account_max_mini=5, market_lookup=get_market)
    bus = TelemetryBus()
    fleet = FleetRuntime(
        bots=[bot_a], broker=sim,
        bar_source_factory=lambda spec: _SlowSource(_bars(40)),
        telemetry=bus,
        heartbeat_path=tmp_path / "hb",
        allocator=alloc,
        dashboard_port=port,
        dashboard_bots_dir=bots_dir,
        dashboard_state_root=tmp_path / "state",
    )

    fleet_task = asyncio.create_task(fleet.run())
    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
        ) as client:
            await _wait_for_first_response(client, "/api/fleet")
            resp_fleet = await client.get("/api/fleet")
            resp_bot = await client.get("/api/bots/alpha")
            resp_profiles = await client.get("/api/profiles")
    finally:
        fleet.request_shutdown()
        await fleet_task

    assert resp_fleet.status_code == 200
    fleet_body = resp_fleet.json()
    assert [b["name"] for b in fleet_body["bots"]] == ["alpha"]

    assert resp_bot.status_code == 200
    assert resp_bot.json()["name"] == "alpha"

    assert resp_profiles.status_code == 200
    profiles = resp_profiles.json()
    assert "default" in profiles["profiles"]


async def test_v2_dashboard_profile_overlay_round_trip(tmp_path: Path) -> None:
    """Create a profile, set an override, verify the response carries the
    new effective spec; activate the profile and verify the diff."""
    sim = SimExecutionClient()
    await sim.connect()
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    _write_yaml(bots_dir, "alpha", tmp_path / "alpha.db")
    bot_a = _resolved("alpha", tmp_path, sim)

    port = _free_port()
    bus = TelemetryBus()
    fleet = FleetRuntime(
        bots=[bot_a], broker=sim,
        bar_source_factory=lambda spec: _SlowSource(_bars(8)),
        telemetry=bus,
        heartbeat_path=tmp_path / "hb",
        dashboard_port=port,
        dashboard_bots_dir=bots_dir,
        dashboard_state_root=tmp_path / "state",
    )

    fleet_task = asyncio.create_task(fleet.run())
    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
        ) as client:
            await _wait_for_first_response(client, "/api/fleet")
            create_resp = await client.post(
                "/api/profiles", json={"name": "alice", "fork_from": "default"},
            )
            assert create_resp.status_code == 201
            put_resp = await client.put(
                "/api/profiles/alice/overrides/alpha/strategy_params",
                json={"key": "range_minutes", "value": 10},
            )
            assert put_resp.status_code == 200
            assert put_resp.json()["spec"]["strategy_params"]["range_minutes"] == 10

            activate_resp = await client.post("/api/profiles/alice/activate")
            assert activate_resp.status_code == 200
            body = activate_resp.json()
            assert body["active"] == "alice"
            assert any(b["name"] == "alpha" for b in body["changed_bots"])
            assert body["restart_required"] is True
    finally:
        fleet.request_shutdown()
        await fleet_task


async def test_v2_dashboard_ws_receives_live_events(tmp_path: Path) -> None:
    """Open a real WebSocket against the running dashboard and verify
    bar_tick events arrive as the fleet drives synthetic bars.

    Skips when the `websockets` package isn't installed — its absence
    isn't a regression in the dashboard surface itself, and the REST
    e2e tests above already prove the wiring is reachable.
    """
    try:
        import websockets
    except ImportError:
        pytest.skip("websockets package not installed")
    sim = SimExecutionClient()
    await sim.connect()
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    _write_yaml(bots_dir, "alpha", tmp_path / "alpha.db")
    bot_a = _resolved("alpha", tmp_path, sim)

    port = _free_port()
    bus = TelemetryBus()
    fleet = FleetRuntime(
        bots=[bot_a], broker=sim,
        bar_source_factory=lambda spec: _SlowSource(_bars(50)),
        telemetry=bus,
        heartbeat_path=tmp_path / "hb",
        dashboard_port=port,
        dashboard_bots_dir=bots_dir,
        dashboard_state_root=tmp_path / "state",
    )

    fleet_task = asyncio.create_task(fleet.run())
    try:
        # Wait for the REST surface so we know uvicorn is up.
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
        ) as client:
            await _wait_for_first_response(client, "/api/fleet")
        # Now open a WS and collect events.
        ws_url = f"ws://127.0.0.1:{port}/ws"
        kinds_seen: set[str] = set()
        async with websockets.connect(ws_url) as ws:
            for _ in range(20):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                payload = json.loads(raw)
                kinds_seen.add(payload["kind"])
                if {"bar_tick", "account_update", "bot_intent"}.issubset(
                    kinds_seen,
                ):
                    break
    finally:
        fleet.request_shutdown()
        await fleet_task

    # If we managed to open the WS, we expect all three per-bar event kinds.
    if kinds_seen:
        assert "bar_tick" in kinds_seen
        assert "account_update" in kinds_seen
        assert "bot_intent" in kinds_seen
