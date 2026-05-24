"""Dashboard FastAPI routes (Plan 21 T4).

Tests via httpx.AsyncClient + the create_app factory. The DashboardState
carries the bots_dir + heartbeat_path so the test fixture can wire them
to tmp_path without touching globals.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from bot.dashboard.app import DashboardState, create_app
from bot.journal.journal import Journal
from bot.types import OrderEvent, OrderIntent


def _spec_yaml(name: str, enabled: bool, journal: str) -> str:
    return (
        f"name: {name}\n"
        f"enabled: {str(enabled).lower()}\n"
        "symbol: MNQH26\n"
        "strategy_id: orb_5m\n"
        "strategy_params:\n  range_minutes: 5\n"
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
    (bots_dir / "alpha.yml").write_text(
        _spec_yaml("alpha", True, str(tmp_path / "alpha.db")),
    )
    (bots_dir / "beta.yml").write_text(
        _spec_yaml("beta", False, str(tmp_path / "beta.db")),
    )
    heartbeat = tmp_path / "hb"
    heartbeat.write_text(datetime(2026, 5, 24, 10, 0, tzinfo=UTC).isoformat())
    return DashboardState(bots_dir=bots_dir, heartbeat_path=heartbeat)


async def test_root_returns_200_with_bot_names(state: DashboardState) -> None:
    """Legacy v1 fleet page now lives under /v1/ — the SPA owns `/`."""
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/v1/")
    assert resp.status_code == 200
    assert "alpha" in resp.text
    assert "beta" in resp.text


async def test_root_includes_auto_refresh_meta(state: DashboardState) -> None:
    """Fleet page auto-refreshes every 5s via <meta http-equiv=refresh>."""
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/v1/")
    assert "http-equiv" in resp.text.lower()
    assert "refresh" in resp.text.lower()


async def test_bot_detail_returns_200_for_existing_bot(
    state: DashboardState, tmp_path: Path,
) -> None:
    """A bot detail page returns 200 even if the journal has no data yet."""
    # alpha.db doesn't exist — should still return 200 with empty view.
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/v1/bots/alpha")
    assert resp.status_code == 200
    assert "alpha" in resp.text


async def test_bot_detail_404_for_unknown_bot(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/v1/bots/nonexistent")
    assert resp.status_code == 404


async def test_bot_detail_shows_recent_trades(
    state: DashboardState, tmp_path: Path,
) -> None:
    """Populate alpha's journal with one fill; detail page contains its data."""
    j = await Journal.connect(str(tmp_path / "alpha.db"))
    await j.apply_migrations()
    ts = datetime(2026, 5, 24, 13, 30, tzinfo=UTC)
    intent = OrderIntent(
        symbol="MNQH26", side="BUY", quantity=2, order_type="MARKET",
        client_order_id="cid-1", timestamp=ts,
    )
    await j.record_risk_decision(
        intent=intent, approved=True, rule=None, reason=None, timestamp=ts,
    )
    await j.record_fill(OrderEvent(
        client_order_id="cid-1", broker_order_id="bid-1",
        status="FILLED", filled_quantity=2, avg_fill_price=18_055.5,
        timestamp=ts,
    ))
    await j.close()

    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/v1/bots/alpha")
    assert resp.status_code == 200
    # The fill price should appear somewhere in the rendered HTML.
    assert "18055" in resp.text.replace(",", "") or "18055.5" in resp.text


async def test_healthz_returns_ok_with_heartbeat_age(state: DashboardState) -> None:
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "heartbeat_age" in body


async def test_healthz_handles_missing_heartbeat(tmp_path: Path) -> None:
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    state = DashboardState(
        bots_dir=bots_dir, heartbeat_path=tmp_path / "never_written",
    )
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    # heartbeat_age may be None when no heartbeat — status still "ok".
    assert body["status"] == "ok"
    assert body["heartbeat_age"] is None
