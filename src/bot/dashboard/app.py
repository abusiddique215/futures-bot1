"""FastAPI app factory for the fleet dashboard (Plan 21 T4).

`create_app(state)` returns a FastAPI app wired to the three read-only
routes defined in `routes.py`. The DashboardState carries the bots dir
and heartbeat path — no module-level globals, so tests construct fresh
state pointing at tmp_path and run the full app surface in-process via
httpx.AsyncClient.

Templates live next to this module under `templates/`. The Jinja2 env
is built once at app-create time and stashed on `app.state.templates`
so route handlers can render with `app.state.templates.get_template(...)`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from jinja2 import Environment, FileSystemLoader, select_autoescape

from bot.dashboard import routes


@dataclass(frozen=True)
class DashboardState:
    """Per-app configuration passed into create_app.

    bots_dir       — directory of bot YAML files (config/bots/).
    heartbeat_path — single shared FleetRuntime heartbeat file.
    """
    bots_dir: Path
    heartbeat_path: Path


_TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(state: DashboardState) -> FastAPI:
    """Build a FastAPI app for the given DashboardState."""
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "html.j2"]),
    )
    app = FastAPI(
        title="Topstep Fleet Dashboard",
        # Disable the docs UIs — this is an internal monitoring page, not
        # a public API surface.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.dashboard = state
    app.state.templates = env
    app.include_router(routes.build_router())
    return app
