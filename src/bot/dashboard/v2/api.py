"""FastAPI REST routes for the v2 dashboard.

All routes live under `/api/` (mounted by the app factory). JSON only.
Pydantic v2 models drive request validation + response shape so the
frontend gets a typed surface via /api/docs.

Endpoints:

  GET    /api/fleet                                   — fleet summary
  GET    /api/bots/{name}                             — bot detail
  GET    /api/profiles                                — list + active
  POST   /api/profiles                                — create / fork
  DELETE /api/profiles/{name}                         — delete (≠ "default")
  POST   /api/profiles/{name}/activate                — switch active
  GET    /api/profiles/{name}/overrides               — current overrides
  PUT    /api/profiles/{name}/overrides/{bot}/{block} — set one key
  GET    /api/profiles/{name}/history                 — audit trail

Activation does NOT live-restart bots — that's a separate piece of work
the fleet runtime owns. We diff hashes + set the pointer + return the
list of changed bots so the frontend can show "restart required". See
the plan's "RESEARCH-DRIVEN REFINEMENTS" section for the hot-swap caveat.
"""
from __future__ import annotations

import getpass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from bot.dashboard.queries import get_bot_detail, get_fleet_heartbeat, list_bots
from bot.dashboard.v2.profiles import (
    ProfileNotFoundError,
    ProfileOverlay,
    ProfileStore,
    ProfileValidationError,
)
from bot.runtime.fleet.spec import BotSpec, load_bot_specs

# ---------- Pydantic v2 models ----------------------------------------------

class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FleetBotEntry(_Base):
    name: str
    enabled: bool
    symbol: str
    strategy_id: str
    status: str  # "running" | "no_data"


class FleetView(_Base):
    bots: list[FleetBotEntry]
    heartbeat: datetime | None
    heartbeat_age: float | None
    active_profile: str


class AccountSummaryView(_Base):
    """Fleet-wide aggregated account view (sum across all bots)."""
    balance: float
    equity: float
    open_pnl: float
    closed_pnl_today: float
    high_water: float
    contracts_open: int


class FlattenResponse(_Base):
    flattened: list[str]
    failed: list[dict[str, str]]


class PrefsBody(_Base):
    prefs: dict[str, Any]


class PrefsView(_Base):
    prefs: dict[str, Any]


class BotDetailView(_Base):
    name: str
    symbol: str
    enabled: bool
    state: str
    open_positions: dict[str, int]
    realized_pnl_today: float
    equity: float
    high_water_equity: float
    recent_trades: list[dict[str, Any]]
    equity_curve: list[dict[str, Any]]


class ProfileList(_Base):
    profiles: list[str]
    active: str


class CreateProfileBody(_Base):
    name: str
    fork_from: str = "default"


class CreatedProfile(_Base):
    name: str
    forked_from: str


class OverridesView(_Base):
    overrides: dict[str, dict[str, dict[str, Any]]]


class SetOverrideBody(_Base):
    key: str
    value: Any


class EffectiveSpec(_Base):
    name: str
    strategy_params: dict[str, Any]
    risk_params: dict[str, Any]
    schedule_params: dict[str, Any]


class SetOverrideResponse(_Base):
    bot: str
    block: str
    key: str
    value: Any
    spec: EffectiveSpec


class HistoryView(_Base):
    history: list[dict[str, Any]]


class ChangedBot(_Base):
    name: str
    hash_before: str
    hash_after: str
    spec: EffectiveSpec


class ActivateResponse(_Base):
    active: str
    changed_bots: list[ChangedBot]
    unchanged_bots: list[str]
    restart_required: bool


# ---------- helpers ---------------------------------------------------------

def _store(request: Request) -> ProfileStore:
    store: ProfileStore | None = request.app.state.dashboard.profile_store
    if store is None:
        raise HTTPException(
            status_code=503, detail="profile store not wired",
        )
    return store


def _spec_by_name(bots_dir: Any) -> dict[str, BotSpec]:
    return {spec.name: spec for spec in load_bot_specs(bots_dir)}


def _effective_spec(spec: BotSpec, overrides: dict[str, Any]) -> BotSpec:
    """Return the BotSpec after applying this bot's overrides (if any)."""
    bot_overlay = overrides.get(spec.name)
    if not bot_overlay:
        return spec
    return ProfileOverlay.apply(spec, bot_overlay)


def _spec_to_effective_view(spec: BotSpec) -> EffectiveSpec:
    return EffectiveSpec(
        name=spec.name,
        # Coerce datetime.time values to ISO strings so the response is
        # JSON-clean for the frontend.
        strategy_params=_coerce(spec.strategy_params),
        risk_params=_coerce(spec.risk_params),
        schedule_params=_coerce(spec.schedule_params),
    )


def _coerce(obj: Any) -> Any:
    """Recursively replace datetime.time with ISO string for JSON output."""
    import datetime as _dt
    if isinstance(obj, dict):
        return {k: _coerce(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce(v) for v in obj]
    if isinstance(obj, _dt.time):
        return obj.isoformat()
    return obj


def _bot_state(open_positions: dict[str, int], enabled: bool) -> str:
    if not enabled:
        return "DISABLED"
    for qty in open_positions.values():
        if qty != 0:
            return "IN_TRADE"
    return "ARMED_WAITING"


# ---------- router ----------------------------------------------------------

def build_router() -> APIRouter:
    router = APIRouter()

    # ---- fleet ----

    @router.get("/fleet", response_model=FleetView)
    async def get_fleet(request: Request) -> FleetView:
        ds = request.app.state.dashboard
        rows = list_bots(ds.bots_dir)
        specs_by_name = {s.name: s for s in load_bot_specs(ds.bots_dir)}
        hb = get_fleet_heartbeat(ds.heartbeat_path)
        age = None
        if hb is not None and hb.tzinfo is not None:
            age = (datetime.now(UTC) - hb).total_seconds()
        store = ds.profile_store
        active = store.get_active() if store is not None else "default"
        return FleetView(
            bots=[
                FleetBotEntry(
                    name=r.name, enabled=r.enabled, symbol=r.symbol,
                    strategy_id=(
                        specs_by_name[r.name].strategy_id
                        if r.name in specs_by_name else "unknown"
                    ),
                    status=r.status,
                ) for r in rows
            ],
            heartbeat=hb,
            heartbeat_age=age,
            active_profile=active,
        )

    # ---- aggregated account ----

    @router.get("/account_summary", response_model=AccountSummaryView)
    async def get_account_summary(request: Request) -> AccountSummaryView:
        """Sum per-bot journal snapshots into a single fleet view.

        Each bot has its own journal + tracker so the "fleet account" is a
        derived rollup. Bots with empty journals contribute zero. This is
        the read the Overview header consumes; per-bot detail still hits
        `/api/bots/{name}` for the unaggregated numbers.
        """
        ds = request.app.state.dashboard
        rows = list_bots(ds.bots_dir)
        balance = equity = high_water = closed_pnl = 0.0
        open_pnl = 0.0  # unrealized — sourced from open positions
        contracts_open = 0
        for r in rows:
            detail = get_bot_detail(r.name, r.journal_path)
            balance += detail.equity - detail.realized_pnl_today
            equity += detail.equity
            high_water += detail.high_water_equity
            closed_pnl += detail.realized_pnl_today
            contracts_open += sum(
                abs(q) for q in detail.open_positions.values()
            )
        return AccountSummaryView(
            balance=balance,
            equity=equity,
            open_pnl=open_pnl,
            closed_pnl_today=closed_pnl,
            high_water=high_water,
            contracts_open=contracts_open,
        )

    # ---- kill switch ----

    @router.post("/bots/flatten_all", response_model=FlattenResponse)
    async def flatten_all(request: Request) -> FlattenResponse:
        """Force-flatten every bot in the fleet. Cancel-then-close per gate.

        Disabled (returns 503) when no `gates` dict is wired into
        DashboardState — happens in tests that don't construct a real
        FleetRuntime + ResolvedBots.
        """
        ds = request.app.state.dashboard
        gates = ds.gates or {}
        if not gates:
            raise HTTPException(
                status_code=503,
                detail="kill switch unavailable: no gates wired",
            )
        flattened: list[str] = []
        failed: list[dict[str, str]] = []
        for name, gate in gates.items():
            try:
                await gate.force_flatten_now(
                    reason=f"dashboard kill switch by {getpass.getuser()}",
                )
                flattened.append(name)
            except Exception as e:
                failed.append({"bot": name, "error": str(e)})
        return FlattenResponse(flattened=flattened, failed=failed)

    @router.get("/bots/{name}", response_model=BotDetailView)
    async def get_bot(name: str, request: Request) -> BotDetailView:
        ds = request.app.state.dashboard
        rows = list_bots(ds.bots_dir)
        match = next((r for r in rows if r.name == name), None)
        if match is None:
            raise HTTPException(
                status_code=404, detail=f"unknown bot: {name}",
            )
        detail = get_bot_detail(name, match.journal_path)
        return BotDetailView(
            name=match.name,
            symbol=match.symbol,
            enabled=match.enabled,
            state=_bot_state(detail.open_positions, match.enabled),
            open_positions=detail.open_positions,
            realized_pnl_today=detail.realized_pnl_today,
            equity=detail.equity,
            high_water_equity=detail.high_water_equity,
            recent_trades=[
                {
                    "client_order_id": t.client_order_id,
                    "symbol": t.symbol, "side": t.side,
                    "quantity": t.quantity, "fill_price": t.fill_price,
                    "timestamp": t.timestamp.isoformat(),
                } for t in detail.recent_trades
            ],
            equity_curve=[
                {
                    "timestamp": p.timestamp.isoformat(),
                    "equity": p.equity, "realized_pnl": p.realized_pnl,
                } for p in detail.equity_curve
            ],
        )

    # ---- profiles ----

    @router.get("/profiles", response_model=ProfileList)
    async def get_profiles(request: Request) -> ProfileList:
        store = _store(request)
        return ProfileList(
            profiles=store.list_profiles(),
            active=store.get_active(),
        )

    @router.post(
        "/profiles", status_code=status.HTTP_201_CREATED,
        response_model=CreatedProfile,
    )
    async def create_profile(
        body: CreateProfileBody, request: Request,
    ) -> CreatedProfile:
        store = _store(request)
        try:
            store.create(body.name, fork_from=body.fork_from)
        except FileExistsError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ProfileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return CreatedProfile(name=body.name, forked_from=body.fork_from)

    @router.delete(
        "/profiles/{name}", status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_profile(name: str, request: Request) -> Response:
        store = _store(request)
        try:
            store.delete(name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except ProfileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/profiles/{name}/overrides", response_model=OverridesView,
    )
    async def get_overrides(name: str, request: Request) -> OverridesView:
        store = _store(request)
        try:
            return OverridesView(overrides=store.get_overrides(name))
        except ProfileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @router.put(
        "/profiles/{name}/overrides/{bot}/{block}",
        response_model=SetOverrideResponse,
    )
    async def put_override(
        name: str, bot: str, block: str,
        body: SetOverrideBody, request: Request,
    ) -> SetOverrideResponse:
        ds = request.app.state.dashboard
        store = _store(request)
        try:
            store.set_override(
                name, bot=bot, block=block, key=body.key, value=body.value,
                user=getpass.getuser(),
            )
        except ProfileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ProfileValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        # Build the effective spec for the bot so the frontend can refresh.
        specs = _spec_by_name(ds.bots_dir)
        if bot not in specs:
            raise HTTPException(status_code=404, detail=f"unknown bot: {bot}")
        overrides = store.get_overrides(name)
        try:
            new_spec = _effective_spec(specs[bot], overrides)
        except ProfileValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return SetOverrideResponse(
            bot=bot, block=block, key=body.key, value=body.value,
            spec=_spec_to_effective_view(new_spec),
        )

    @router.get("/profiles/{name}/prefs", response_model=PrefsView)
    async def get_prefs(name: str, request: Request) -> PrefsView:
        store = _store(request)
        try:
            return PrefsView(prefs=store.get_prefs(name))
        except ProfileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @router.put("/profiles/{name}/prefs", response_model=PrefsView)
    async def put_prefs(
        name: str, body: PrefsBody, request: Request,
    ) -> PrefsView:
        store = _store(request)
        try:
            store.set_prefs(name, body.prefs)
        except ProfileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return PrefsView(prefs=store.get_prefs(name))

    @router.get("/profiles/{name}/history", response_model=HistoryView)
    async def get_history(name: str, request: Request) -> HistoryView:
        store = _store(request)
        try:
            return HistoryView(history=store.get_history(name))
        except ProfileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @router.post(
        "/profiles/{name}/activate", response_model=ActivateResponse,
    )
    async def activate_profile(
        name: str, request: Request,
    ) -> ActivateResponse:
        ds = request.app.state.dashboard
        store = _store(request)
        if name not in store.list_profiles():
            raise HTTPException(
                status_code=404, detail=f"profile not found: {name!r}",
            )
        active = store.get_active()
        old_overrides = store.get_overrides(active)
        new_overrides = store.get_overrides(name)
        specs = list(load_bot_specs(ds.bots_dir))
        changed: list[ChangedBot] = []
        unchanged: list[str] = []
        for spec in specs:
            try:
                before = _effective_spec(spec, old_overrides)
                after = _effective_spec(spec, new_overrides)
            except ProfileValidationError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            h_before = ProfileOverlay.spec_hash(before)
            h_after = ProfileOverlay.spec_hash(after)
            if h_before != h_after:
                changed.append(ChangedBot(
                    name=spec.name,
                    hash_before=h_before, hash_after=h_after,
                    spec=_spec_to_effective_view(after),
                ))
            else:
                unchanged.append(spec.name)
        store.set_active(name)
        return ActivateResponse(
            active=name,
            changed_bots=changed,
            unchanged_bots=unchanged,
            # We don't live-restart the fleet from here — the runtime owns
            # that lifecycle. Always report restart_required=True so the
            # frontend renders a clear "pending restart" badge.
            restart_required=True,
        )

    return router
