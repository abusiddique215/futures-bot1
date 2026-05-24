"""Plan 23 Wave 2 — end-to-end smoke for the live dashboard surface.

Boots a 2-bot fleet against a sim broker with synthetic bars, brings up
the dashboard, then exercises:

  1. REST: GET /api/fleet — both bots present, strategy_id + active_profile shown.
  2. REST: GET /api/account_summary — returns the aggregated shape.
  3. REST: SPA root `GET /` returns HTML containing `<div id="root"`.
  4. WS:  open + subscribe "fleet" + receive ≥1 bar_tick event.
  5. Profile API: create + override + activate round-trip; verify the
     active-profile flip flows back through `GET /api/fleet`.

Skips the WS portion gracefully when the `websockets` package isn't
installed — keeps CI green on minimal environments.
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
from bot.observability.bus import TelemetryBus
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


async def _wait_for(client: httpx.AsyncClient, url: str) -> None:
    for _ in range(100):
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                return
        except httpx.ConnectError:
            pass
        await asyncio.sleep(0.05)
    raise AssertionError(f"endpoint {url} never became reachable")


async def test_dashboard_v2_full_e2e(tmp_path: Path) -> None:
    """One run that exercises REST + WS + SPA root + profile overlay."""
    sim = SimExecutionClient()
    await sim.connect()
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    _write_yaml(bots_dir, "alpha", tmp_path / "alpha.db")
    _write_yaml(bots_dir, "beta", tmp_path / "beta.db")
    bot_a = _resolved("alpha", tmp_path, sim)
    bot_b = _resolved("beta", tmp_path, sim)

    port = _free_port()
    bus = TelemetryBus()
    fleet = FleetRuntime(
        bots=[bot_a, bot_b], broker=sim,
        bar_source_factory=lambda spec: _SlowSource(_bars(40)),
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
            await _wait_for(client, "/api/fleet")

            # 1. Fleet REST — both bots present with strategy_id.
            fleet_resp = await client.get("/api/fleet")
            assert fleet_resp.status_code == 200
            fleet_body = fleet_resp.json()
            names = sorted(b["name"] for b in fleet_body["bots"])
            assert names == ["alpha", "beta"]
            for entry in fleet_body["bots"]:
                assert entry["strategy_id"] == "orb_5m"
            assert "active_profile" in fleet_body

            # 2. Account summary REST shape check.
            acct_resp = await client.get("/api/account_summary")
            assert acct_resp.status_code == 200
            acct = acct_resp.json()
            for key in (
                "balance", "equity", "open_pnl", "closed_pnl_today",
                "high_water", "contracts_open",
            ):
                assert key in acct

            # 3. SPA root.
            spa_resp = await client.get("/")
            assert spa_resp.status_code == 200
            assert '<div id="root"' in spa_resp.text

            # 4. Profile overlay round-trip: create alice, set override,
            #    activate, verify active flag flows through fleet view.
            create = await client.post(
                "/api/profiles", json={"name": "alice", "fork_from": "default"},
            )
            assert create.status_code == 201
            put = await client.put(
                "/api/profiles/alice/overrides/alpha/strategy_params",
                json={"key": "range_minutes", "value": 10},
            )
            assert put.status_code == 200
            assert put.json()["spec"]["strategy_params"]["range_minutes"] == 10

            activate = await client.post("/api/profiles/alice/activate")
            assert activate.status_code == 200
            assert activate.json()["active"] == "alice"

            fleet_after = await client.get("/api/fleet")
            assert fleet_after.json()["active_profile"] == "alice"

            # 5. WS — open + subscribe + receive at least one bar_tick.
            #    Skipped gracefully on minimal envs (test-only import).
            try:
                import websockets
            except ImportError:
                pytest.skip("websockets package not installed")
            ws_url = f"ws://127.0.0.1:{port}/ws"
            kinds: set[str] = set()
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({
                    "action": "subscribe", "channels": ["fleet"],
                }))
                for _ in range(40):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    except TimeoutError:
                        break
                    payload = json.loads(raw)
                    kinds.add(payload["kind"])
                    if "bar_tick" in kinds:
                        break
            assert "bar_tick" in kinds
    finally:
        fleet.request_shutdown()
        await fleet_task
