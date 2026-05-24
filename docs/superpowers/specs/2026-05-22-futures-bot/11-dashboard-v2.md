# 11 — Dashboard v2 (Plan 23)

The dashboard ships in two stacked surfaces over a single FastAPI app:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Browser (React SPA, dark-mode default)                                  │
│   shadcn/ui components + TradingView Lightweight Charts v5              │
│   TanStack Query (REST polling) + native WebSocket (live events)        │
│   Zustand store for UI-only state (active profile, ws status)           │
└────────────────────────────────│────────────────────────────────────────┘
                                 │ http + ws on 127.0.0.1:8765
┌────────────────────────────────│────────────────────────────────────────┐
│ FastAPI side-car (`bot.dashboard.app:create_app`)                       │
│                                                                         │
│   /                  ─→ SPA index (dashboard-ui/dist/index.html)        │
│   /bots/<name>       ─→ SPA index (React Router handles client routes)  │
│   /profiles, /settings ─→ SPA index                                     │
│   /assets/*          ─→ SPA static assets                               │
│   /api/*             ─→ Pydantic v2 REST router (see endpoints below)   │
│   /ws                ─→ Multiplexed WebSocket (channel filter)          │
│   /v1/*              ─→ Legacy Jinja fleet/bot HTML (read-only fallback)│
│   /healthz           ─→ JSON { status, heartbeat_age }                  │
│                                                                         │
│   WebSocketBroadcaster ←─ subscribes to TelemetryBus                    │
│       │                                                                 │
│       └─→ per-client asyncio.Queue (max 100; over-full clients dropped) │
│                                                                         │
│   ProfileStore (state/profiles/<name>/)                                 │
│       overrides.yaml | prefs.json | history.jsonl | .lock               │
│   ProfileOverlay.apply(spec, overrides) → new BotSpec                   │
└─────────────────────────────────────────────────────────────────────────┘
```

## REST API (prefix `/api`)

All responses are Pydantic v2 models (`extra="forbid"` for request
bodies, `extra="allow"` for events to keep the relay schema-lenient).

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/fleet` | `{bots:[{name,enabled,symbol,strategy_id,status}], heartbeat, heartbeat_age, active_profile}` |
| GET | `/account_summary` | Fleet-aggregated `{balance, equity, open_pnl, closed_pnl_today, high_water, contracts_open}` |
| GET | `/bots/{name}` | `{name, symbol, enabled, state, open_positions, realized_pnl_today, equity, high_water_equity, recent_trades, equity_curve}` |
| POST | `/bots/flatten_all` | Kill switch — iterates `DashboardState.gates` and calls `force_flatten_now()`. 503 when no gates wired. |
| GET | `/profiles` | `{profiles:[…], active}` |
| POST | `/profiles` | Body `{name, fork_from?}` → 201 `{name, forked_from}` |
| DELETE | `/profiles/{name}` | 204; refuses to delete `"default"` |
| POST | `/profiles/{name}/activate` | `{active, changed_bots, unchanged_bots, restart_required:true}` |
| GET | `/profiles/{name}/overrides` | `{overrides: {bot: {block: {key: value}}}}` |
| PUT | `/profiles/{name}/overrides/{bot}/{block}` | Body `{key, value}` → `{bot, block, key, value, spec}` |
| GET / PUT | `/profiles/{name}/prefs` | UI preferences (theme, refresh, timezone) |
| GET | `/profiles/{name}/history` | Audit trail (one row per `set_override`) |

Activation does NOT live-restart bots — the FleetRuntime owns that
lifecycle. The endpoint returns `restart_required: true` so the
frontend can render a "pending restart" badge.

## WebSocket protocol

Client sends:
```json
{ "action": "subscribe", "channels": ["fleet"] }
{ "action": "subscribe", "channels": ["bot:surgebot_nq"] }
```

Server pushes:
```json
{ "kind": "bar_tick" | "account_update" | "bot_intent"
        | "fill" | "risk_decision" | "bot_state_change",
  "data": <payload matching events.py> }
```

Channel routing:
- `"fleet"` — every event lands here (catch-all).
- `"bot:<name>"` — events whose `data.bot === <name>`.

Per-client `asyncio.Queue(maxsize=100)`. A client that fails to drain is
dropped + closed with code 1013 (try-again-later) on the next push.
This isolates fast clients from slow ones and keeps the broadcaster from
becoming a memory bomb.

## Profile overlay model

Each user has a profile directory under `state/profiles/<name>/`:

```
state/profiles/
├── default/                  # auto-created on first ProfileStore init
│   ├── overrides.yaml        # {} by default
│   ├── prefs.json
│   ├── history.jsonl         # append-only audit
│   └── .lock                 # fcntl flock sentinel
├── <username>/               # auto-created from getpass.getuser()
│   └── …
└── .active                   # pointer to the currently-active profile
```

`ProfileOverlay.apply(spec, overrides)`:
- Pure function. Deep-merges into `strategy_params` /
  `risk_params` / `schedule_params`.
- Returns a NEW `BotSpec` via `dataclasses.replace` (frozen-safe).
- Validates the result by re-running the registry factory — a bad
  overlay value (e.g. ORB `range_minutes: -1`) raises
  `ProfileValidationError` at apply time, not on the next bar.
- `spec_hash(spec)` is a stable SHA-256 over the overrideable fields
  only — `activate` diffs hashes to populate `changed_bots` /
  `unchanged_bots`.

Filesystem isolation: one user's directory never touches another's. A
profile delete removes the directory (including its history); operators
who need long-term audit archive the directory first.

## Frontend (dashboard-ui/)

- **Vite + React 19 + TypeScript + Tailwind 3 + shadcn/ui primitives.**
- **TanStack Query** for REST polling (5s default; 10s for per-bot
  detail; 30s for profile list). WS events invalidate the query cache
  on `account_update` / `fill` / `bot_state_change` rather than
  patching cache entries by hand — keeps the source-of-truth on the
  server.
- **Zustand** for UI-only state: active profile name, last WS event
  timestamp, WS connection status.
- **Lightweight Charts v5** for the equity curve (`chart.addSeries(LineSeries, …)`).
- **No CORS** — the SPA is served from the same origin as the API.
- **Mocked tests:** Vitest + React Testing Library. The BotDetail
  smoke test stubs `lightweight-charts` (jsdom doesn't give it the
  layout it needs) and mocks `fetch` directly rather than pulling MSW.

The SPA build outputs to `src/bot/dashboard/v2/static/dist/`. Both the
dist directory and the React SPA mount are guarded — if the dist isn't
present (fresh clone without `pnpm build`), `/` falls back to the legacy
Jinja fleet page so the no-build dev workflow continues to work.

## Known limitations (deferred)

- **Working orders table** — backend doesn't expose pending orders yet.
  UI renders a placeholder.
- **Per-position stop/target/MFE/MAE** — same; the journal stores fills
  but not order intents in a way the dashboard can query cleanly.
- **Reset-one-override endpoint** — the ParamsEditor surfaces the
  limitation in the UI; resetting today requires editing
  `overrides.yaml` directly.
- **Theme override** — Settings exposes the toggle, but the SPA is
  hard-coded dark for now (the trader-grade default the plan called
  for). The pref persists for the day the theme system lands.
