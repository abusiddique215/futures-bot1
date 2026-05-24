"""FastAPI app factory for the fleet dashboard (Plan 21 T4 + Plan 23 T5).

`create_app(state)` returns a FastAPI app wired to:

  * legacy v1 routes (read-only fleet/bot HTML pages) from `routes.py`
  * Plan 23 v2 REST API under `/api/` (when ProfileStore is supplied)
  * Plan 23 v2 WS endpoint at `/ws` (when broadcaster is supplied)

The DashboardState ships extra optional fields (bus, profile_store,
broadcaster) so legacy tests that construct minimal state still work —
v2 routes 503 when their dependency is missing.

Templates live next to this module under `templates/`. The Jinja2 env
is built once at app-create time and stashed on `app.state.templates`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from jinja2 import Environment, FileSystemLoader, select_autoescape

from bot.dashboard import routes
from bot.dashboard.v2.profiles import ProfileStore
from bot.dashboard.v2.ws_bridge import WebSocketBroadcaster
from bot.observability.bus import TelemetryBus


@dataclass(frozen=True)
class DashboardState:
    """Per-app configuration passed into create_app.

    bots_dir       — directory of bot YAML files (config/bots/).
    heartbeat_path — single shared FleetRuntime heartbeat file.
    bus            — TelemetryBus the broadcaster subscribes to (optional).
    profile_store  — ProfileStore for /api/profiles/* (optional).
    broadcaster    — WebSocketBroadcaster for /ws (optional).
    """
    bots_dir: Path
    heartbeat_path: Path
    bus: TelemetryBus | None = None
    profile_store: ProfileStore | None = None
    broadcaster: WebSocketBroadcaster | None = None


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
    # Legacy v1 HTML routes (Plan 21).
    app.include_router(routes.build_router())
    # Plan 23 v2 — only mounted when their dependencies are wired so existing
    # tests don't need to change.
    if state.profile_store is not None:
        from bot.dashboard.v2 import api as v2_api
        app.include_router(v2_api.build_router(), prefix="/api")
    if state.broadcaster is not None:
        from bot.dashboard.v2 import ws_routes
        app.add_api_websocket_route("/ws", ws_routes.ws_endpoint)
    return app
