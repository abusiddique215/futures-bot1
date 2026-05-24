# Plan 21 — Multi-Bot Dashboard + Cross-Bot Account Allocator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Production UX. Ship a local web dashboard (FastAPI + minimal HTML, no JS framework) that shows per-bot status, current positions, daily P&L, equity curve, and recent journal entries across the entire fleet. Plus a cross-bot account allocator that divides shared Topstep account capacity across active bots without violating combined position limits. After this plan: the operator opens `http://localhost:8765` and sees the whole bot family at a glance, and Plan 12's "one broker per fleet" assumption is safely shareable across N bots.

**Architecture:** Two distinct features that share runtime hooks:

(1) **Dashboard** — a FastAPI app running in a separate asyncio task alongside `FleetRuntime`. Reads per-bot Journal databases + the latest heartbeat. Renders HTML via Jinja2 (already added in Plan 13). Hot-refresh every 5 seconds via simple `<meta http-equiv="refresh" content="5">` (no WebSockets, no SSE — overengineering for a single-user local dashboard).

(2) **Allocator** — new `FleetAllocator` class wraps the shared ExecutionClient. Tracks per-bot position contribution. Before forwarding `place_order` from any bot, checks: would (bot's current position + intent) push the COMBINED account position above the policy max? If yes, deny with reason "FLEET_POSITION_CAP". This prevents two bots both opening +5 minis on the same symbol and breaching Topstep's account-wide cap.

**Tech Stack:** New deps: `fastapi>=0.115`, `uvicorn>=0.30`. Both are widely-used; pin to stable. No frontend framework — server-rendered HTML.

**Scope notes:**
- v1 dashboard is read-only. No buttons to start/stop bots. Buttons are a future plan.
- Dashboard binds to `127.0.0.1` only — never exposed to network.
- Allocator only handles same-symbol position contention. Cross-symbol margin is Topstep's problem (they reject the order at the broker).
- Per-bot risk gates still run FIRST (per-bot rule enforcement is unchanged). The allocator is an additional FLEET-WIDE check after the per-bot gate approves.

**Deliverable:**
- `python -m bot.runtime --bots config/bots/ --dashboard` boots the fleet AND the dashboard.
- `http://localhost:8765/` shows the fleet status page.
- `http://localhost:8765/bots/<name>` shows the per-bot detail page (equity curve + recent trades).
- Allocator caps prevent two bots from breaching combined position limits.
- CI green (~707 + ~30 new tests).
- Tag `plan-21-dashboard-allocator-complete`.

---

## File structure

- Create: `src/bot/dashboard/__init__.py`
- Create: `src/bot/dashboard/app.py` — FastAPI app factory
- Create: `src/bot/dashboard/routes.py` — `/`, `/bots/<name>`, `/healthz`
- Create: `src/bot/dashboard/queries.py` — read-only Journal + heartbeat queries
- Create: `src/bot/dashboard/templates/fleet.html.j2`
- Create: `src/bot/dashboard/templates/bot_detail.html.j2`
- Create: `src/bot/dashboard/templates/base.html.j2`
- Create: `src/bot/dashboard/static/style.css`
- Create: `src/bot/runtime/fleet/allocator.py` — `FleetAllocator`
- Modify: `src/bot/runtime/fleet/runtime.py` — accept optional `dashboard_port` + `allocator`
- Modify: `src/bot/runtime/cli.py` — add `--dashboard` flag
- Modify: `pyproject.toml` — add `fastapi>=0.115`, `uvicorn>=0.30`
- Create: `tests/dashboard/test_queries.py`
- Create: `tests/dashboard/test_routes.py`
- Create: `tests/runtime/fleet/test_allocator.py`
- Create: `tests/integration/test_dashboard_e2e.py`

---

## Tasks

### T1: `FleetAllocator`

`src/bot/runtime/fleet/allocator.py`. Class `FleetAllocator(account_max_mini: int, market_lookup: Callable[[str], MarketSpec])`. Wraps an `ExecutionClient`.

`async approve_intent(bot_name: str, intent: OrderIntent, fleet_positions: dict[str, dict[str, int]]) -> ApprovedOrder | OrderDenied`:
- `current_combined = sum(positions.get(intent.symbol, 0) for positions in fleet_positions.values())`
- `projected = current_combined + intent.qty` (with sign)
- `market = market_lookup(intent.symbol); ratio = market.micro_to_full_ratio if is_micro(intent.symbol) else 1`
- `cap = account_max_mini * ratio`
- If `abs(projected) > cap`: return OrderDenied(reason="FLEET_POSITION_CAP", detail=...)
- Else: return ApprovedOrder(intent)

Threading: positions dict is read under `asyncio.Lock` to prevent races between concurrent bot intents.

Tests:
- 2 bots both submit +3 MNQ; cap is 50 micros; both approved.
- 2 bots both submit +30 MNQ; cap is 50; first approved, second denied.
- Bot A short -10 MNQ, Bot B long +10 MNQ: net = 0, under cap; both approved.
- Lock prevents race: concurrent submits from 3 bots aggregate correctly.

Commit: `feat(fleet): FleetAllocator (cross-bot position cap)`.

### T2: Allocator integration in `FleetRuntime`

Modify `FleetRuntime` to optionally accept a `FleetAllocator`. When set: each bot's `LiveTradingLoop` calls `await allocator.approve_intent(bot_name, intent, fleet_positions)` BEFORE `await broker.place_order(intent)`. The fleet_positions dict is read from the AccountStateTracker of each bot (already a per-bot data structure).

Tests:
- FleetRuntime without allocator (default): existing behavior unchanged (regression).
- FleetRuntime with allocator: cross-bot caps enforced.
- Concurrent bot intents: allocator's lock prevents over-allocation.

Commit: `feat(fleet): FleetRuntime threads FleetAllocator into per-bot loops`.

### T3: Dashboard queries (read-only)

`src/bot/dashboard/queries.py`. Sync functions (the dashboard runs in its own task; queries are SQLite reads).

- `list_bots(bots_dir: Path) -> list[BotStatusRow]` — reads `config/bots/*.yml`, returns rows with name, enabled, last_heartbeat_age_sec, status (running/stopped/error).
- `get_bot_detail(bot_name, journal_path) -> BotDetailView` — opens journal, queries: open positions, today's P&L, last N trades (default 20), equity curve series (list of (timestamp, cumulative_pnl)).
- `get_fleet_heartbeat(heartbeat_path) -> datetime | None` — reads the single fleet heartbeat file.

Tests:
- list_bots against fixture dir → expected rows.
- get_bot_detail against fixture journal → expected fields.
- Missing journal file → returns "no data yet" placeholder, no crash.

Commit: `feat(dashboard): read-only Journal + heartbeat queries`.

### T4: FastAPI app + routes

`src/bot/dashboard/app.py` + `routes.py`. Create_app(state: DashboardState) factory pattern.

Routes:
- `GET /` → fleet.html.j2 with `list_bots(...)` data + auto-refresh meta.
- `GET /bots/<name>` → bot_detail.html.j2 with `get_bot_detail(...)`.
- `GET /healthz` → JSON `{"status":"ok","heartbeat_age":<seconds>}`.

Templates use Jinja2 (already added in Plan 13). Minimal Tailwind-free CSS via static/style.css — table + headers, no images beyond the Plan 13 equity curve PNG embedded in bot_detail.

Tests (via `httpx.AsyncClient` against the app):
- GET / → 200, contains all enabled bot names.
- GET /bots/example → 200, contains last 20 trades.
- GET /bots/nonexistent → 404.
- GET /healthz → 200, status=ok.

Commit: `feat(dashboard): FastAPI app + 3 routes + Jinja2 templates`.

### T5: Dashboard task integrated into `FleetRuntime`

Modify `FleetRuntime.run`:
- If `dashboard_port` set: launch `uvicorn.Server` as an `asyncio.create_task` alongside the bot loops.
- `asyncio.gather` includes the dashboard task with `return_exceptions=True` — dashboard crash does NOT crash the fleet.
- On fleet shutdown: signal uvicorn to stop gracefully.

Tests:
- FleetRuntime with dashboard_port=0 (auto-pick): dashboard reachable; bots also run.
- Dashboard crash mid-run: fleet continues; dashboard restart not attempted in v1.

Commit: `feat(fleet): FleetRuntime launches dashboard as side-car task`.

### T6: CLI `--dashboard` flag

`src/bot/runtime/cli.py`: add `--dashboard` (default off), `--dashboard-port` (default 8765). When `--dashboard`: construct `FleetAllocator` + pass dashboard_port to FleetRuntime.

Tests:
- `python -m bot.runtime --bots config/bots/ --check --dashboard` boots, prints "dashboard at http://127.0.0.1:8765", exits 0 in check mode.
- Without `--dashboard`: dashboard does not start (regression).

Commit: `feat(cli): --dashboard flag wires allocator + side-car HTTP server`.

### T7: End-to-end integration test

`tests/integration/test_dashboard_e2e.py`. Boots FleetRuntime with 2 synthetic bots + dashboard on an ephemeral port. Drives 30 bars of synthetic data through each. Then makes httpx requests to `/`, `/bots/<name>`, `/healthz`. Asserts:
- All routes return 200.
- Fleet page lists both bots with last-heartbeat < 10s.
- Bot detail page shows the expected trade count.
- Healthz responds OK.

Commit: `test(integration): dashboard end-to-end (fleet + 2 bots + HTTP queries)`.

### T8: Docs + tag + push all branches to main

Create `docs/superpowers/specs/2026-05-22-futures-bot/10-dashboard-allocator.md` describing the dashboard + allocator architecture. Update INDEX.

After commit:
```
git tag plan-21-dashboard-allocator-complete
git push origin plan-21-wt --tags  # (or main)
```

Commit: `docs(spec): dashboard + allocator spec 10`.

---

## Verification

```bash
cd ~/futures-bot1
source ~/.venvs/topstep-bot/bin/activate
ruff check . && mypy --strict src/ && pytest -x -q
python -m bot.runtime --bots config/bots/ --dashboard --check
# In another terminal:
open http://localhost:8765
```

Expected:
- CI green: ~707 tests.
- Dashboard shows 6 bots from the lineup (some enabled, some disabled per their YAML).
- Clicking a bot name navigates to detail view with the embedded Plan-13 equity curve.

End state: the VSL-aligned product is complete. SurgeBot + PropBot + Gold Bot + ES Scalper + Lux Bot + NQ Maintenance all deployable through a single CLI invocation, with a fleet dashboard for monitoring and cross-bot account allocation for safety.
