# Plan 23 — Trader-Grade Dashboard v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Replace the read-only Jinja2 dashboard with a live, customizable, dark-mode-default trader dashboard. After this plan: a day trader opens `http://localhost:8765`, sees real-time positions / pending orders / account state / what-the-bot-plans-to-do-next, can edit strategy + risk parameters via UI without touching YAML, and per-profile changes don't leak across users.

**Architecture:**

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Browser (React SPA, dark mode default)                                  │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  shadcn/ui components + TradingView Lightweight Charts           │    │
│  │  TanStack Query (REST) + native WebSocket (live events)          │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                              ↑↓                                          │
└──────────────────────────────│┼─────────────────────────────────────────-┘
                              http + ws on :8765
┌──────────────────────────────│┼─────────────────────────────────────────-┐
│  FastAPI dashboard backend  ↓↑                                           │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  REST: GET /api/fleet, /api/bots/{n}, /api/profiles, ...         │    │
│  │  WS:   /ws  ← multiplexed: bar_tick, fill, decision, account     │    │
│  │  Profile API: GET/PUT /api/profiles/{n}/overrides                │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                              ↑                                           │
│  WebSocketBroadcaster (TelemetryBus sink) ──────┐                        │
│                                                 │                        │
│  FleetRuntime ─→ LiveTradingLoop ─→ TelemetryBus.alert(kind, **kw) ──────┘
│      │                                                                   │
│      └─→ BotRegistry.build(spec) ← ProfileOverlay.apply(spec, profile)   │
│                                                                          │
│  Per-profile storage: state/profiles/<name>/{overrides.yaml,prefs.json}  │
└──────────────────────────────────────────────────────────────────────────┘
```

**Tech Stack:**
- **Frontend**: Vite + React 18 + TypeScript + shadcn/ui (Radix primitives + Tailwind) + lucide-react icons
- **Charts**: TradingView Lightweight Charts v5 (free; the chart lib day traders already know)
- **Data layer**: TanStack Query v5 for REST, native `WebSocket` for live channels
- **State**: Zustand for UI-only state (active profile, panel visibility)
- **Backend extensions**: existing FastAPI + `websockets` (already pulled by uvicorn), Pydantic v2 models for profile payloads
- **Build**: `cd dashboard-ui && pnpm build` produces `dashboard-ui/dist/`; FastAPI serves it as static files at `/`
- **No CORS / dev server proxy**: single-port serving — `127.0.0.1:8765` serves both API and UI

**Multi-tenant model (the explicit requirement):**
- Each user has a named **profile** under `state/profiles/<profile_name>/`
- Profile contains: `overrides.yaml` (per-bot strategy_params / risk_params / schedule_params overrides), `prefs.json` (UI prefs), `history.jsonl` (audit log of edits)
- `ProfileOverlay.apply(BotSpec, profile_name)` returns a new BotSpec with merged overrides — frozen-dataclass-safe
- Switching profiles is hot-swap: only affected bots get rebuilt + restarted
- "Default" profile always exists; new profiles forkable from any existing one
- Per-profile changes are file-isolated; no other profile can see or be affected

**Day-trader terminology** (non-negotiable labels used in UI):
- "Contracts" not "quantity" (1 MNQ contract, not 1 unit)
- "R-multiples" for trade outcomes (+1.5R, -1R)
- "Drawdown" / "DD" not "loss from peak"
- "MLL" (Maximum Loss Limit) — Topstep's daily floor
- "Trailing stop" / "trail" for the MLL ratchet
- "MFE" (Max Favorable Excursion) / "MAE" (Max Adverse Excursion)
- "Win rate" / "Profit factor" / "Expectancy" on stats cards
- "Tick" (smallest price increment), "Point" (full point)
- "Long" / "Short" never "buy" / "sell" in position language
- "Daily P&L" / "Realized" / "Unrealized" / "Open P&L"
- "Profit Target" / "Distance to MLL" / "Distance to Target" — Topstep-specific
- "Working orders" not "pending orders"
- "Flat" (no position) — explicit state
- Each bot named by its VSL identity: SurgeBot, PropBot, Gold Bot, ES Scalper, Lux Bot, NQ Maintenance

**Dark-mode-default color system:**
- Background: `#0b0e14` (deep neutral, easy on eyes for long sessions)
- Surface: `#11151c`
- Border: `#1f2733`
- Text primary: `#e6edf3`
- Text secondary: `#7d8590`
- Green (profit / long): `#3fb950` (WCAG AA on dark)
- Red (loss / short): `#f85149`
- Yellow (warning / approaching MLL): `#e3b341`
- Cyan (info / current bar): `#58a6ff`

**Deliverable:**
- `dashboard-ui/` Vite + React + shadcn project shipping a built `dashboard-ui/dist/`
- New backend modules: `src/bot/dashboard/v2/` containing WS bridge, profile API, REST extensions
- `state/profiles/default/` ships in repo with empty overrides
- 6 main screens: Overview, Bot Detail (×6 via dynamic route), Profile Manager, Settings, Trade Log, Backtest Viewer
- Live WebSocket events: `bar_tick`, `fill`, `risk_decision`, `account_update`, `bot_intent`
- Strategy + risk parameter editors with input validation + diff-preview before save
- Profile CRUD (create from template, fork, delete, activate)
- All 992 existing tests stay green; +60-80 new tests for the v2 surface
- Tag `plan-23-dashboard-v2-complete`

---

## File structure

### Backend (`src/bot/dashboard/v2/`)
- Create: `src/bot/dashboard/v2/__init__.py`
- Create: `src/bot/dashboard/v2/ws_bridge.py` — `WebSocketBroadcaster` (TelemetryBus sink → all WS clients)
- Create: `src/bot/dashboard/v2/profiles.py` — `ProfileStore`, `ProfileOverlay.apply()`
- Create: `src/bot/dashboard/v2/api.py` — REST routes (fleet, bots, profiles, params)
- Create: `src/bot/dashboard/v2/ws_routes.py` — `/ws` route + connection manager
- Create: `src/bot/dashboard/v2/intent.py` — extracts "what is the bot watching for" from strategy state
- Create: `src/bot/dashboard/v2/static.py` — mounts `dashboard-ui/dist/` for SPA fallback
- Modify: `src/bot/dashboard/app.py` — mount v2 routes alongside legacy v1 (legacy moves to `/v1/`)
- Modify: `src/bot/runtime/fleet/runtime.py` — pass TelemetryBus → WS bridge in dashboard launcher
- Modify: `src/bot/runtime/live_loop.py` — emit `bar_tick` + `account_update` events on every bar
- Modify: `src/bot/runtime/fleet/registry.py` — `build(spec, *, broker, profile=None)` applies overlay

### Frontend (`dashboard-ui/`)
- Create: `dashboard-ui/package.json` (Vite + React + TS + shadcn deps)
- Create: `dashboard-ui/vite.config.ts`
- Create: `dashboard-ui/tsconfig.json`
- Create: `dashboard-ui/tailwind.config.ts`
- Create: `dashboard-ui/index.html`
- Create: `dashboard-ui/src/main.tsx` (TanStack Query + theme provider)
- Create: `dashboard-ui/src/App.tsx` (router)
- Create: `dashboard-ui/src/lib/api.ts` (REST client, type-safe)
- Create: `dashboard-ui/src/lib/ws.ts` (WebSocket client with reconnect)
- Create: `dashboard-ui/src/lib/format.ts` (R-multiples, tick formatting, $ formatting)
- Create: `dashboard-ui/src/components/ui/*` (shadcn copy-paste: button, card, dialog, input, badge, table, tabs, slider)
- Create: `dashboard-ui/src/components/Topbar.tsx` (profile switcher + heartbeat indicator)
- Create: `dashboard-ui/src/components/FleetGrid.tsx` (6 bot status cards)
- Create: `dashboard-ui/src/components/BotCard.tsx` (single bot summary)
- Create: `dashboard-ui/src/components/AccountStatePanel.tsx` (balance, equity, MLL distance, daily P&L)
- Create: `dashboard-ui/src/components/PositionsTable.tsx`
- Create: `dashboard-ui/src/components/WorkingOrdersTable.tsx`
- Create: `dashboard-ui/src/components/BotIntentPanel.tsx` ("watching for breakout above X")
- Create: `dashboard-ui/src/components/EquityCurve.tsx` (TradingView Lightweight Charts)
- Create: `dashboard-ui/src/components/TradeLog.tsx`
- Create: `dashboard-ui/src/components/ParamsEditor.tsx` (strategy + risk params; diff preview)
- Create: `dashboard-ui/src/components/ProfileManager.tsx` (CRUD)
- Create: `dashboard-ui/src/pages/Overview.tsx`
- Create: `dashboard-ui/src/pages/BotDetail.tsx`
- Create: `dashboard-ui/src/pages/Profiles.tsx`
- Create: `dashboard-ui/src/pages/Settings.tsx`
- Create: `dashboard-ui/src/store/ui.ts` (Zustand: active profile, theme override)

### State + tests
- Create: `state/profiles/default/overrides.yaml` (empty `{}`)
- Create: `state/profiles/default/prefs.json` (defaults)
- Create: `state/profiles/.gitkeep`
- Create: `tests/dashboard/v2/test_profiles.py`
- Create: `tests/dashboard/v2/test_ws_bridge.py`
- Create: `tests/dashboard/v2/test_api.py`
- Create: `tests/dashboard/v2/test_intent.py`
- Create: `tests/integration/test_dashboard_v2_e2e.py`

---

## Tasks

### T1: `ProfileStore` + `ProfileOverlay` — multi-tenancy foundation

`src/bot/dashboard/v2/profiles.py`.

`ProfileStore(root: Path = Path("state/profiles"))`:
- `list_profiles() -> list[str]`
- `create(name: str, *, fork_from: str = "default") -> None`
- `delete(name: str) -> None` (refuses to delete "default")
- `get_overrides(name: str) -> dict[str, dict]` — returns `{bot_name: {param_block: {key: value}}}` from `overrides.yaml`
- `set_override(name: str, bot: str, block: str, key: str, value: Any) -> None` — writes + appends to `history.jsonl`
- `get_prefs(name: str) -> dict` / `set_prefs(name: str, prefs: dict) -> None`

`ProfileOverlay.apply(spec: BotSpec, overrides: dict) -> BotSpec`:
- Deep-merge overrides over spec.strategy_params/risk_params/schedule_params
- Returns NEW frozen BotSpec via `dataclasses.replace`
- Validates result by calling the existing factory functions (raises if invalid)

Tests:
- Create profile, get_overrides returns empty
- Fork from default, edit, verify other profiles unchanged
- Apply override that changes ORB `range_minutes: 5 → 10` → new spec has the override
- Apply override with invalid value (negative tick) → ValidationError
- Delete profile, history.jsonl preserved as audit
- Concurrent writes safe (file locking)

Commit: `feat(dashboard/v2): ProfileStore + ProfileOverlay for per-user customization`.

### T2: `WebSocketBroadcaster` — TelemetryBus → WS clients

`src/bot/dashboard/v2/ws_bridge.py`.

`WebSocketBroadcaster` implements the TelemetryBus sink interface (`async def receive(kind: str, **kw) -> None`). Maintains a set of connected `WebSocket` clients. On `receive()`, fan-out the event to all clients as JSON.

Connection manager methods:
- `async register(ws: WebSocket) -> None`
- `async unregister(ws: WebSocket) -> None`
- `async broadcast(payload: dict) -> None` (handles disconnect cleanup)

Subscribes to the FleetRuntime's TelemetryBus at dashboard launch.

Tests:
- Sink interface satisfied (assignable to `TelemetrySink` Protocol)
- 3 connected clients all receive the same event
- Disconnected client doesn't crash broadcast loop
- Backpressure: client that can't keep up gets dropped after 100-msg queue

Commit: `feat(dashboard/v2): WebSocketBroadcaster — TelemetryBus → connected clients`.

### T3: Per-bar event emission in `LiveTradingLoop`

`src/bot/runtime/live_loop.py`: emit on every bar:
- `bar_tick`: `{bot, symbol, bar: {ts, o, h, l, c, v}}`
- `account_update`: `{bot, equity, balance, realized_pnl, unrealized_pnl, high_water, distance_to_mll, distance_to_target}`
- `bot_intent`: `{bot, watching_for: "ORB breakout > 18045.25 OR < 17988.50", schedule_open: true, max_trades_remaining: 1}`

Emit on fill + risk decision (already partial; ensure shape consistency).

Tests:
- Synthetic 10-bar run with TelemetryBus stub: receives 10 bar_ticks, 10 account_updates, 10 bot_intents
- Fill triggers `fill` event with correct R-multiple if exit
- All event payloads JSON-serializable

Commit: `feat(runtime): LiveTradingLoop emits bar_tick / account_update / bot_intent events`.

### T4: Bot intent extractor

`src/bot/dashboard/v2/intent.py`. Pure function `extract_intent(strategy, current_bar, account_state) -> dict`:
- For ORB: "Watching for breakout > {high} or < {low} (range: {minutes}m)"
- For TrendFollowing: "Trend = {bullish/bearish/none}; pullback zone {x}-{y}"
- For MeanReversion: "BB upper {x} lower {y}; RSI {r}; entry on {oversold/overbought}"
- For Signal: "Waiting on Discord signal from channels {ids}"

Each strategy type registers an intent extractor; default falls back to "Watching for entry signal".

Tests:
- ORB extractor produces expected string for known state
- Unknown strategy → fallback string
- Pure function (no side effects)

Commit: `feat(dashboard/v2): bot intent extractor — "what is the bot watching for"`.

### T5: REST API + WS routes (FastAPI)

`src/bot/dashboard/v2/api.py` + `ws_routes.py`.

REST (JSON, prefix `/api/`):
- `GET /api/fleet` — all bots + statuses + last heartbeat
- `GET /api/bots/{name}` — full bot view (positions, orders, recent fills, equity series)
- `GET /api/profiles` — list profile names + active
- `POST /api/profiles` — create (body: `{name, fork_from}`)
- `DELETE /api/profiles/{name}` — remove (refuses default)
- `POST /api/profiles/{name}/activate` — switch active profile (hot-swap)
- `GET /api/profiles/{name}/overrides` — current overrides
- `PUT /api/profiles/{name}/overrides/{bot}/{block}` — set one override; returns new computed spec
- `GET /api/profiles/{name}/history` — audit trail

WS:
- `GET /ws` — multiplexed stream. Client sends `{action: "subscribe", channels: ["fleet", "bot:surgebot_nq"]}` to filter

All Pydantic v2 models for request/response. OpenAPI auto-docs at `/api/docs`.

Tests:
- httpx.AsyncClient hits each endpoint, asserts shape
- WebSocket test: connect, subscribe to "fleet", receive 3 broadcast events
- Profile activate hot-swaps bots without restarting the fleet

Commit: `feat(dashboard/v2): REST + WS API surface`.

### T6: Vite + React + shadcn scaffold

Initialize `dashboard-ui/` with:
- `pnpm create vite@latest dashboard-ui --template react-ts`
- Add Tailwind + shadcn/ui init (`pnpm dlx shadcn@latest init`)
- Configure dark mode default in `index.html` (`<html class="dark">`)
- Configure Vite to build to `../src/bot/dashboard/v2/static/dist/` so FastAPI serves the bundle
- Install: tanstack-query, zustand, react-router-dom, lightweight-charts, lucide-react

The static-serve mount in FastAPI: any GET to `/` (not `/api/*` or `/ws`) serves from the built directory; SPA fallback to `index.html` for client-side routes.

Tests:
- `pnpm build` produces dist with non-zero size
- FastAPI mount serves `index.html` at `/`
- `/api/fleet` returns JSON (not the index)

Commit: `feat(dashboard-ui): Vite + React + shadcn/ui scaffold (dark-mode default)`.

### T7: Frontend — Overview + BotCard + AccountStatePanel + Topbar

Render the Overview page: 6 bot cards in a grid, an AccountStatePanel showing fleet-aggregated balance/equity/MLL distance, Topbar with profile switcher + heartbeat indicator.

Hook into `GET /api/fleet` via TanStack Query. Subscribe to `/ws` for `account_update` events and patch the query cache.

Components honor the day-trader terminology + color palette.

Tests (Vitest + React Testing Library):
- Overview renders 6 bot cards
- BotCard shows correct labels ("flat" vs "+1 long", "drawdown $X")
- Topbar switches profile via API call

Commit: `feat(dashboard-ui): Overview page + BotCard + Topbar with profile switcher`.

### T8: Frontend — BotDetail (positions, orders, intent, equity curve, trade log)

`pages/BotDetail.tsx` route: `/bots/:name`.

Layout (3-column grid):
- Left: BotIntentPanel ("Watching for breakout > 18045.25"), AccountStatePanel for this bot
- Center: EquityCurve (TradingView Lightweight Charts) + recent fills overlaid
- Right: PositionsTable (current), WorkingOrdersTable (pending), TradeLog (last 50)

Live updates via `/ws` subscription to `bot:<name>` channel.

Tests:
- BotDetail page mounts + shows live data after WS connect
- EquityCurve renders without errors
- TradeLog formats R-multiples correctly

Commit: `feat(dashboard-ui): BotDetail page — intent + positions + orders + equity curve + trade log`.

### T9: Frontend — ParamsEditor (strategy + risk param editor)

`components/ParamsEditor.tsx`: form bound to a bot's overrideable params from the active profile.

For each editable field (read from a schema endpoint or hardcoded per strategy type):
- Slider for numeric ranges (BB period 5-50)
- Number input for free numerics (atr_mult 0.5-3.0)
- Time pickers for session windows
- Toggle for booleans
- Diff preview: shows base value vs override value, before save
- "Save to {profile}" button writes via `PUT /api/profiles/{name}/overrides/{bot}/{block}`
- "Reset to base" button removes the override

After save: bot hot-restarts; new params take effect on next bar.

Tests:
- Render editor for ORB params; sliders match schema
- Save triggers correct PUT
- Reset removes override

Commit: `feat(dashboard-ui): ParamsEditor — strategy + risk params with diff preview`.

### T10: Frontend — ProfileManager + Settings

`pages/Profiles.tsx`: list profiles, create / fork / delete / activate. Confirmation modal on destructive actions.

`pages/Settings.tsx`: theme override (dark/light/system; default dark), refresh rate, timezone preference.

Tests:
- Create profile, list updates
- Activate profile, Topbar reflects new active
- Settings persist to `prefs.json` via API

Commit: `feat(dashboard-ui): ProfileManager + Settings pages`.

### T11: End-to-end smoke test

`tests/integration/test_dashboard_v2_e2e.py`:
- Boot fleet (2 bots, sim broker, fixture bars)
- Start dashboard with v2 routes mounted
- httpx hits `/api/fleet`, asserts both bots present
- Open WebSocket, subscribe to `fleet`, receive >0 bar_tick events as bars stream
- Create profile, set override for one bot, verify the bot's spec reflects the override after activation
- `GET /` returns HTML containing `<div id="root"` (the SPA host)

Commit: `test(integration): dashboard v2 e2e — REST + WS + profile activation`.

### T12: Docs + tag

- Update `ONBOARDING.md` with dashboard v2 usage
- Update `README.md` with the dashboard v2 features
- Update `docs/superpowers/specs/2026-05-22-futures-bot/10-dashboard-allocator.md` with the v2 architecture
- Add a new spec `11-dashboard-v2.md` covering profile overlay design + WS protocol

Then `git tag plan-23-dashboard-v2-complete && git push origin main --tags`.

Commit: `docs(spec): dashboard v2 + profile overlay design`.

---

## Verification

```bash
cd ~/futures-bot1
source ~/.venvs/topstep-bot/bin/activate
ruff check . && mypy --strict src/ && pytest -q
cd dashboard-ui && pnpm install && pnpm test && pnpm build && cd ..
python -m bot.runtime --bots config/bots/ --dashboard --check
# Then in another terminal:
open http://localhost:8765/
```

Expected:
- CI green: ~1060 tests (992 + ~70 new).
- Dashboard loads in dark mode, shows 6 bot cards.
- Profile switcher in topbar; creating "alice" and activating it isolates Alice's overrides from "default".
- BotDetail page shows live bot intent ("Watching for ORB breakout > $X").
- Tag `plan-23-dashboard-v2-complete` pushed.

End state: the trader opens the dashboard, knows exactly what the bot is doing + planning, and can tune it without YAML.
