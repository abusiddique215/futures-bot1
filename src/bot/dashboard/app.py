"""FastAPI app factory for the fleet dashboard (Plan 21 T4 + Plan 23 T5).

`create_app(state)` returns a FastAPI app wired to:

  * Plan 23 v2 REST API under `/api/` (when ProfileStore is supplied)
  * Plan 23 v2 WS endpoint at `/ws` (when broadcaster is supplied)
  * Plan 23 SPA at `/` (when `spa_dist_dir` exists)
  * Legacy v1 read-only HTML pages under `/v1/` (always mounted as a
    fallback for the operator who prefers the old refresh-every-5s UI)

The DashboardState ships extra optional fields (bus, profile_store,
broadcaster, gates) so legacy tests that construct minimal state still
work — v2 routes 503 when their dependency is missing. When no SPA dist
is present, `/` still hits the legacy fleet HTML so the local dev
workflow stays one URL.

Templates live next to this module under `templates/`. The Jinja2 env
is built once at app-create time and stashed on `app.state.templates`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from bot.dashboard import routes
from bot.dashboard.v2.profiles import ProfileStore
from bot.dashboard.v2.ws_bridge import WebSocketBroadcaster
from bot.observability.bus import TelemetryBus
from bot.risk.gate import TopstepRiskGate

_DEFAULT_SPA_DIST = Path(__file__).parent / "v2" / "static" / "dist"


@dataclass(frozen=True)
class DashboardState:
    """Per-app configuration passed into create_app.

    bots_dir       — directory of bot YAML files (config/bots/).
    heartbeat_path — single shared FleetRuntime heartbeat file.
    bus            — TelemetryBus the broadcaster subscribes to (optional).
    profile_store  — ProfileStore for /api/profiles/* (optional).
    broadcaster    — WebSocketBroadcaster for /ws (optional).
    gates          — per-bot RiskGates so the kill switch endpoint can call
                     `force_flatten_now()`. Empty dict ⇒ kill switch returns
                     a 503 "no gates wired" error.
    """
    bots_dir: Path
    heartbeat_path: Path
    bus: TelemetryBus | None = None
    profile_store: ProfileStore | None = None
    broadcaster: WebSocketBroadcaster | None = None
    gates: dict[str, TopstepRiskGate] = field(default_factory=dict)
    # SPA mount: when set + exists, serves the React bundle at `/` and
    # falls back to `index.html` for client-side routes (so reloading
    # /bots/<name> hits React Router, not a 404).
    spa_dist_dir: Path | None = None


_TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(state: DashboardState) -> FastAPI:
    """Build a FastAPI app for the given DashboardState."""
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "html.j2"]),
    )
    app = FastAPI(
        title="Topstep Fleet Dashboard",
        # Disable the legacy doc UIs — v2 API exposes its own /api/docs path
        # (wired by the v2 router) so JSON consumers get OpenAPI without
        # polluting the legacy HTML namespace.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.dashboard = state
    app.state.templates = env
    # Plan 23 v2 — only mounted when their dependencies are wired so existing
    # tests don't need to change.
    if state.profile_store is not None:
        from bot.dashboard.v2 import api as v2_api
        app.include_router(v2_api.build_router(), prefix="/api")
    if state.broadcaster is not None:
        from bot.dashboard.v2 import ws_routes
        app.add_api_websocket_route("/ws", ws_routes.ws_endpoint)

    # Legacy v1 HTML routes (Plan 21). Always under /v1/ so v2 SPA owns `/`.
    # Also mounted at `/` as a fallback when no SPA dist is configured —
    # keeps the no-SPA dev workflow on a single URL.
    legacy_router = routes.build_router()
    app.include_router(legacy_router, prefix="/v1")

    # SPA: if a dist dir exists, serve it at `/` with index fallback.
    spa_dir = state.spa_dist_dir or _DEFAULT_SPA_DIST
    if spa_dir.is_dir() and (spa_dir / "index.html").is_file():
        # Static assets first (CSS / JS / icons under /assets/*).
        assets_dir = spa_dir / "assets"
        if assets_dir.is_dir():
            app.mount(
                "/assets", StaticFiles(directory=assets_dir), name="spa-assets",
            )
        index_path = spa_dir / "index.html"

        async def _spa_index() -> FileResponse:
            return FileResponse(index_path, media_type="text/html")

        # SPA root + client-side routes. /api/* and /ws/* already routed
        # above; FastAPI matches more-specific routes first.
        app.add_api_route("/", _spa_index, methods=["GET"])
        app.add_api_route("/bots/{name}", _spa_index, methods=["GET"])
        app.add_api_route("/profiles", _spa_index, methods=["GET"])
        app.add_api_route("/settings", _spa_index, methods=["GET"])

        # Mirror /healthz at root so launchd / curl health checks still hit
        # a known path even when the SPA is up.
        @app.get("/healthz")
        async def _healthz() -> JSONResponse:
            from datetime import UTC, datetime

            from bot.dashboard.queries import get_fleet_heartbeat

            heartbeat = get_fleet_heartbeat(state.heartbeat_path)
            age: float | None = None
            if heartbeat is not None and heartbeat.tzinfo is not None:
                age = (datetime.now(UTC) - heartbeat).total_seconds()
            return JSONResponse(
                {"status": "ok", "heartbeat_age": age},
            )
    else:
        # No SPA dist — keep `/`, `/bots/{name}`, `/healthz` on the legacy
        # router for back-compat with the Plan 21 dev workflow.
        app.include_router(legacy_router)

    return app
