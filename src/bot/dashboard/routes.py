"""Dashboard HTTP routes — fleet page, bot detail, healthz (Plan 21 T4).

Three GETs:
  /            — fleet.html.j2 with one row per bot in `config/bots/`.
  /bots/<name> — bot_detail.html.j2 with open positions, P&L, recent
                 trades, equity series. 404 if `<name>` isn't in the
                 bots directory.
  /healthz     — JSON `{"status":"ok","heartbeat_age":<seconds|null>}`.

Fleet + detail pages embed `<meta http-equiv="refresh" content="5">` so
the operator's browser polls every 5 seconds — keeps the dashboard
stateless. No WebSockets, no SSE, no JS framework (single-user local
monitoring; refresh is plenty).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from bot.dashboard.queries import (
    get_bot_detail,
    get_fleet_heartbeat,
    list_bots,
)


def build_router() -> APIRouter:
    """Return a new APIRouter wired with all three dashboard routes."""
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    async def fleet_page(request: Request) -> HTMLResponse:
        state = request.app.state.dashboard
        rows = list_bots(state.bots_dir)
        heartbeat = get_fleet_heartbeat(state.heartbeat_path)
        age_seconds = _age_seconds(heartbeat)
        template = request.app.state.templates.get_template("fleet.html.j2")
        body = template.render(
            bots=rows,
            heartbeat=heartbeat,
            heartbeat_age=age_seconds,
            refresh_seconds=5,
        )
        return HTMLResponse(body)

    @router.get("/bots/{name}", response_class=HTMLResponse)
    async def bot_detail_page(request: Request, name: str) -> HTMLResponse:
        state = request.app.state.dashboard
        rows = list_bots(state.bots_dir)
        match = next((r for r in rows if r.name == name), None)
        if match is None:
            raise HTTPException(status_code=404, detail=f"unknown bot: {name}")
        detail = get_bot_detail(name, match.journal_path)
        template = request.app.state.templates.get_template("bot_detail.html.j2")
        body = template.render(
            bot=match,
            detail=detail,
            refresh_seconds=5,
        )
        return HTMLResponse(body)

    @router.get("/healthz")
    async def healthz(request: Request) -> JSONResponse:
        state = request.app.state.dashboard
        heartbeat = get_fleet_heartbeat(state.heartbeat_path)
        age = _age_seconds(heartbeat)
        payload: dict[str, Any] = {
            "status": "ok",
            "heartbeat_age": age,
        }
        return JSONResponse(payload)

    return router


def _age_seconds(heartbeat: datetime | None) -> float | None:
    """Convert a heartbeat timestamp into seconds-since-now (UTC).

    Returns None when no heartbeat was found so the dashboard can render
    a "no heartbeat yet" state rather than a misleading negative number.
    """
    if heartbeat is None:
        return None
    now = datetime.now(UTC)
    # Naive timestamps would raise; the heartbeat writer always uses
    # tz-aware ISO so this path is only hit if a future writer regresses.
    if heartbeat.tzinfo is None:
        return None
    return (now - heartbeat).total_seconds()
