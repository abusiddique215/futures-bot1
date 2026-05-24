"""Tests for the dashboard v2 REST + WS API surface (Plan 23 T5).

REST endpoints (prefix /api):
  GET  /api/fleet
  GET  /api/bots/{name}
  GET  /api/profiles
  POST /api/profiles                       — create
  DELETE /api/profiles/{name}
  POST /api/profiles/{name}/activate       — hot-swap (computes hash diff)
  GET  /api/profiles/{name}/overrides
  PUT  /api/profiles/{name}/overrides/{bot}/{block}
  GET  /api/profiles/{name}/history

WebSocket:
  GET  /ws — multiplexed live stream with optional subscribe filter
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from bot.dashboard.app import DashboardState, create_app
from bot.dashboard.v2.profiles import ProfileStore
from bot.dashboard.v2.ws_bridge import WebSocketBroadcaster
from bot.observability.bus import TelemetryBus


def _spec_yaml(name: str, journal: str) -> str:
    return (
        f"name: {name}\n"
        f"enabled: true\n"
        "symbol: MNQH26\n"
        "strategy_id: orb_5m\n"
        "strategy_params:\n  range_minutes: 5\n  symbol: MNQ\n"
        "risk_policy: efa_standard\n"
        "risk_params:\n  mll_amount: 2000\n"
        "schedule_type: market_hours\n"
        'schedule_params:\n  open_ct: "08:30"\n  close_ct: "15:00"\n'
        f"journal_path: {journal}\n"
    )


@pytest.fixture
def state(tmp_path: Path) -> DashboardState:
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    (bots_dir / "alpha.yml").write_text(_spec_yaml("alpha", str(tmp_path / "alpha.db")))
    (bots_dir / "beta.yml").write_text(_spec_yaml("beta", str(tmp_path / "beta.db")))
    heartbeat = tmp_path / "hb"
    heartbeat.write_text(datetime(2026, 5, 24, 10, 0, tzinfo=UTC).isoformat())
    bus = TelemetryBus()
    broadcaster = WebSocketBroadcaster()
    bus.subscribe(broadcaster)
    profile_store = ProfileStore(tmp_path / "profiles", current_user="test_user")
    return DashboardState(
        bots_dir=bots_dir, heartbeat_path=heartbeat,
        bus=bus, profile_store=profile_store, broadcaster=broadcaster,
    )


# ---------- REST: fleet -----------------------------------------------------

async def test_get_fleet_returns_bot_list(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/api/fleet")
    assert resp.status_code == 200
    body = resp.json()
    assert "bots" in body
    names = [b["name"] for b in body["bots"]]
    assert sorted(names) == ["alpha", "beta"]
    assert "heartbeat_age" in body


async def test_get_bot_detail_returns_expected_shape(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/api/bots/alpha")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "alpha"
    # Bot state is one of the canonical enum values.
    assert body["state"] in ("DISABLED", "ARMED_WAITING", "IN_TRADE", "LOCKED")
    assert "open_positions" in body
    assert "recent_trades" in body
    assert "equity_curve" in body


async def test_get_bot_detail_404_unknown(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/api/bots/nonexistent")
    assert resp.status_code == 404


# ---------- REST: profiles --------------------------------------------------

async def test_get_profiles_includes_default_and_active(
    state: DashboardState,
) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/api/profiles")
    assert resp.status_code == 200
    body = resp.json()
    assert "default" in body["profiles"]
    assert body["active"] in body["profiles"]


async def test_create_profile(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/profiles", json={"name": "alice", "fork_from": "default"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "alice"


async def test_create_duplicate_profile_returns_409(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        await client.post("/api/profiles", json={"name": "alice"})
        resp = await client.post("/api/profiles", json={"name": "alice"})
    assert resp.status_code == 409


async def test_delete_profile(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        await client.post("/api/profiles", json={"name": "alice"})
        resp = await client.delete("/api/profiles/alice")
    assert resp.status_code == 204


async def test_delete_default_refused(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.delete("/api/profiles/default")
    assert resp.status_code == 400


async def test_get_overrides_empty(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/api/profiles/default/overrides")
    assert resp.status_code == 200
    assert resp.json() == {"overrides": {}}


async def test_put_override_sets_value(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.put(
            "/api/profiles/default/overrides/alpha/strategy_params",
            json={"key": "range_minutes", "value": 10},
        )
    assert resp.status_code == 200
    body = resp.json()
    # Response includes the new effective spec for `alpha`.
    assert body["spec"]["strategy_params"]["range_minutes"] == 10


async def test_put_override_rejects_invalid_value(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.put(
            "/api/profiles/default/overrides/alpha/strategy_params",
            json={"key": "range_minutes", "value": -1},
        )
    assert resp.status_code == 400


async def test_put_override_unknown_block_400(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.put(
            "/api/profiles/default/overrides/alpha/foo",
            json={"key": "x", "value": 1},
        )
    assert resp.status_code == 400


async def test_history_endpoint_returns_audit_rows(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        await client.put(
            "/api/profiles/default/overrides/alpha/strategy_params",
            json={"key": "range_minutes", "value": 10},
        )
        resp = await client.get("/api/profiles/default/history")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["history"]) == 1
    row = body["history"][0]
    assert row["bot"] == "alpha"
    assert row["after"] == 10


async def test_activate_profile_returns_diff(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        await client.post("/api/profiles", json={"name": "alice"})
        await client.put(
            "/api/profiles/alice/overrides/alpha/strategy_params",
            json={"key": "range_minutes", "value": 10},
        )
        resp = await client.post("/api/profiles/alice/activate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] == "alice"
    assert body["restart_required"] is True
    names = [b["name"] for b in body["changed_bots"]]
    assert "alpha" in names
    assert "beta" in body["unchanged_bots"]


# ---------- WebSocket -------------------------------------------------------

def test_websocket_connect_and_receive_event(state: DashboardState) -> None:
    """Sync test using TestClient.websocket_connect.

    The endpoint accepts the connection and pushes any subsequent
    TelemetryBus event the broadcaster receives.
    """
    app = create_app(state)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        # Push an event via the bus the broadcaster is subscribed to.
        state.bus.alert("bar_tick", bot="alpha", symbol="MNQH26", bar={
            "ts": datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
            "o": 1.0, "h": 1.0, "low": 1.0, "c": 1.0, "v": 1,
        })
        raw = ws.receive_text()
        payload = json.loads(raw)
        assert payload["kind"] == "bar_tick"
        assert payload["data"]["bot"] == "alpha"


def test_websocket_subscribe_filter_drops_other_channels(
    state: DashboardState,
) -> None:
    app = create_app(state)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "action": "subscribe", "channels": ["bot:alpha"],
        }))
        # Push a beta event — must not arrive.
        state.bus.alert("bar_tick", bot="beta", symbol="MNQH26", bar={
            "ts": datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
            "o": 1.0, "h": 1.0, "low": 1.0, "c": 1.0, "v": 1,
        })
        # Push an alpha event — must arrive.
        state.bus.alert("bar_tick", bot="alpha", symbol="MNQH26", bar={
            "ts": datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
            "o": 1.0, "h": 1.0, "low": 1.0, "c": 1.0, "v": 1,
        })
        payload = json.loads(ws.receive_text())
        assert payload["data"]["bot"] == "alpha"


def test_websocket_fleet_channel_receives_every_event(
    state: DashboardState,
) -> None:
    app = create_app(state)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"action": "subscribe", "channels": ["fleet"]}))
        state.bus.alert("bar_tick", bot="beta", symbol="MNQH26", bar={
            "ts": datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
            "o": 1.0, "h": 1.0, "low": 1.0, "c": 1.0, "v": 1,
        })
        payload = json.loads(ws.receive_text())
        assert payload["data"]["bot"] == "beta"


# ---------- Static-spec endpoint for active profile -------------------------

async def test_get_active_profile_includes_username_default(
    state: DashboardState,
) -> None:
    """The active profile defaults to the per-user profile we created."""
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/api/profiles")
    body = resp.json()
    assert body["active"] == "test_user"


# ---------- T7 backend extensions: account_summary, flatten_all, prefs ------

async def test_get_account_summary_aggregates_per_bot_journals(
    state: DashboardState,
) -> None:
    """account_summary sums across per-bot journals — zero when none exist."""
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/api/account_summary")
    assert resp.status_code == 200
    body = resp.json()
    # Both bots have empty journals → all rollups are zero.
    for key in (
        "balance", "equity", "open_pnl", "closed_pnl_today",
        "high_water", "contracts_open",
    ):
        assert key in body
    assert body["contracts_open"] == 0


async def test_fleet_view_includes_strategy_id_and_active_profile(
    state: DashboardState,
) -> None:
    """The fleet view exposes strategy_id per bot + the active profile."""
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/api/fleet")
    body = resp.json()
    assert body["active_profile"] in ("test_user", "default")
    for entry in body["bots"]:
        assert entry["strategy_id"] == "orb_5m"


async def test_flatten_all_503_when_no_gates_wired(
    state: DashboardState,
) -> None:
    """Without gates the kill switch is unavailable — returns 503."""
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.post("/api/bots/flatten_all")
    assert resp.status_code == 503


async def test_flatten_all_calls_force_flatten_on_each_gate(
    state: DashboardState,
) -> None:
    """With gates wired, POST /api/bots/flatten_all hits force_flatten_now."""
    called: list[str] = []

    class _FakeGate:
        def __init__(self, name: str) -> None:
            self.name = name

        async def force_flatten_now(self, reason: str | None = None) -> None:
            _ = reason
            called.append(self.name)

    # Replace gates on the state. Use object cast since DashboardState is
    # frozen — build a new one for the test.
    from dataclasses import replace
    test_state = replace(
        state,
        gates={
            "alpha": _FakeGate("alpha"),  # type: ignore[dict-item]
            "beta": _FakeGate("beta"),    # type: ignore[dict-item]
        },
    )
    app = create_app(test_state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.post("/api/bots/flatten_all")
    assert resp.status_code == 200
    assert sorted(resp.json()["flattened"]) == ["alpha", "beta"]
    assert sorted(called) == ["alpha", "beta"]


async def test_prefs_round_trip(state: DashboardState) -> None:
    """Read prefs (empty), write some, read them back."""
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        get_resp = await client.get("/api/profiles/test_user/prefs")
        assert get_resp.status_code == 200
        assert get_resp.json()["prefs"] == {}

        put_resp = await client.put(
            "/api/profiles/test_user/prefs",
            json={"prefs": {"theme": "dark", "refresh_rate_ms": 1000}},
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["prefs"]["theme"] == "dark"

        get2 = await client.get("/api/profiles/test_user/prefs")
        assert get2.json()["prefs"]["refresh_rate_ms"] == 1000


async def test_prefs_404_for_unknown_profile(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/api/profiles/nope/prefs")
    assert resp.status_code == 404


# ---------- SPA mount ------------------------------------------------------

async def test_spa_root_serves_index_html(state: DashboardState) -> None:
    """When the SPA dist exists, `/` returns the index containing #root."""
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert 'id="root"' in resp.text


async def test_spa_handles_client_side_routes(state: DashboardState) -> None:
    """SPA client-side routes /bots/<name>, /profiles, /settings all return
    the index so React Router can render them after hydration."""
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        for path in ("/bots/alpha", "/profiles", "/settings"):
            resp = await client.get(path)
            assert resp.status_code == 200, path
            assert 'id="root"' in resp.text, path
