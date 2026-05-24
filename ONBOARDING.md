# Onboarding — Topstep Futures Bot Fleet

You just cloned the repo. This document gets you from zero to a running backtest in 5 minutes, and to "I understand how this whole system works" in 30 minutes.

## TL;DR (5 minutes)

```bash
# 1. Clone (you've done this).
cd <repo>

# 2. Python 3.13 + venv.
python3.13 -m venv ~/.venvs/topstep-bot
source ~/.venvs/topstep-bot/bin/activate
pip install -e ".[dev]"

# 3. Smoke-test the runtime (no broker, no data, no risk).
python -m bot.runtime --bots config/bots/ --check

# 4. Run the test suite — should be ~990 passing.
pytest -q

# 5. Run the full-fleet smoke test — boots all 6 bots concurrently
#    + dashboard + ~30s of synthetic bars, end-to-end.
pytest tests/integration/test_full_fleet_smoke.py -v
```

If steps 3 + 4 are green you have a working dev environment.

To run an actual backtest you need a 1-minute OHLCV CSV (timestamp, open, high, low, close, volume — UTC, one bar per row). See `tests/test_backtest_cli_bot_flag.py::_write_fixture_csv` for the exact format; then:

```bash
python -m bot.backtest --bot surgebot_nq \
  --start 2024-01-01 --end 2024-01-31 \
  --data-fixture path/to/bars.csv \
  --proof-output state/proof/my_first_run/
ls state/proof/my_first_run/  # report.html + report.json + equity_curve.png + trade_log.json
```

Continuous-contract historical loading from FirstRateData is in flight; the `--data-fixture` path is the production-ready route as of 2026-05-24.

## What this is

A Python-based automated futures trading bot fleet for Topstep, the prop-trading firm. The product is six independent bots running concurrently against a single Topstep account:

| Bot | Market | Strategy | Risk Policy | Schedule |
| --- | --- | --- | --- | --- |
| `surgebot_nq` | MNQ | ORB 5-minute + tiered sizing | Combine | 08:30 - 15:00 CT |
| `propbot_nq` | MNQH26 | Trend (EMA pullback) | EFA Standard | 09:00 - 14:30 CT |
| `lux_bot` | MNQH26 | External Discord signals | EFA Standard | Always |
| `nq_maintenance` | MNQH26 | Mean reversion (BB + RSI) | EFA Standard | Always (24/7) |
| `gold_bot` | MGCH26 | Mean reversion | EFA Standard | 7 ET windows |
| `es_scalper` | MESH26 | Mean reversion (scalper tuning) | EFA Standard | 08:30 - 14:45 CT |

The whole fleet is driven by a single shared broker connection. A cross-bot `FleetAllocator` caps total account exposure so two bots can't independently open positions that combine to breach Topstep's account-level limit.

A four-rail test ladder is the contract for promoting a strategy from idea to real money:

1. **Backtest** — historical bars + `SimExecutionClient`. No live deps. Cost: $0.
2. **IB Paper** — live bars from Interactive Brokers paper + paper fills.
3. **TopstepX Sim** — real Topstep account in their simulated mode. End-to-end with TopstepX's auth + reconciliation.
4. **TopstepX Live** — real money. Operator authorizes per-bot.

Bots ship `enabled: false` and the operator promotes them up the ladder one at a time.

## Architecture

```
                                  +-----------------+
                                  |  config/bots/   |
                                  |  *.yml (6 bots) |
                                  +--------+--------+
                                           |
                                           v
   +-----------+    +-------------+    +-------+-----+    +----------------+
   | BarSource | -> |   Strategy  | -> | RiskGate    | -> | FleetAllocator |
   | (IB live, |    | (per-bot)   |    | (per-bot)   |    | (one for the   |
   |  parquet, |    | on_bar() -> |    | approve_or_ |    |  whole fleet)  |
   |  signals) |    | OrderIntent |    | deny()      |    +-------+--------+
   +-----------+    +-------------+    +-------------+            |
                                                                  v
                                                          +-------+--------+
                                                          | ExecutionClient|
                                                          | (sim / IB /    |
                                                          |  topstepx)     |
                                                          +-------+--------+
                                                                  |
                                                                  v
                                                          +-------+--------+
                                                          | Journal (per-  |
                                                          | bot SQLite)    |
                                                          +----------------+
```

`FleetRuntime` builds one `LiveTradingLoop` per bot, runs them concurrently under `asyncio.gather`, and exposes a side-car dashboard on 127.0.0.1 for read-only monitoring.

Risk is centralized: every order goes through `TopstepRiskGate` (per-bot) and then `FleetAllocator` (account-wide) before reaching the broker. There is no bypass path — strategies cannot place orders directly.

## Running a backtest

Simplest path — single bot, CSV fixture, defaults:

```bash
python -m bot.backtest \
  --bot surgebot_nq \
  --start 2024-01-01 --end 2024-01-31 \
  --data-fixture path/to/1min_bars.csv \
  --proof-output state/proof/run1/
```

The CSV must be `timestamp,open,high,low,close,volume` with UTC ISO timestamps — one bar per row. This loads `config/bots/surgebot_nq.yml`, builds the ORB + tiered sizing strategy, runs the engine through the bot's own `TopstepRiskGate`, and writes a proof bundle (HTML + JSON + equity curve PNG + trade log) to `state/proof/run1/`. The proof bundle is the load-bearing artifact.

For sweeps / walk-forward / Monte Carlo, see `docs/superpowers/specs/2026-05-22-futures-bot/05-backtest-harness.md`.

## The 4-rail test ladder

Each rail has one command. The promotion criterion is "the previous rail's proof bundle is clean."

### Rail 1 — Backtest
```bash
python -m bot.backtest --bot <bot_name> --start <YYYY-MM-DD> --end <YYYY-MM-DD>
```

### Rail 2 — IB Paper
```bash
# Requires Interactive Brokers Gateway (paper account) on 127.0.0.1:4002.
python -m bot.runtime --config config/<bot>.yml --check  # smoke
python -m bot.runtime --config config/<bot>.yml          # live paper
```

### Rail 3 — TopstepX Sim
```bash
# .env must contain TOPSTEPX_USERNAME / API_KEY / ACCOUNT_NAME pointed at sim.
python -m bot.runtime --bots config/bots/ --check
python -m bot.runtime --bots config/bots/
```

### Rail 4 — TopstepX Live
```bash
# Same command — but the account is the real funded one and `env: live`
# in the bot YAML.
python -m bot.runtime --bots config/bots/ --dashboard
```

## Enabling a bot for live

Every bot ships `enabled: false`. Promotion to live is a 5-step protocol:

1. **Backtest pass.** The bot has at least one fresh proof bundle showing no rule violations and within the strategy's expected risk profile.
2. **IB Paper run.** At least one full week of IB-paper running with zero ungraceful exits.
3. **TopstepX Sim run.** At least one full week of TopstepX-sim with zero reconcile mismatches in `state/journal_<bot>.db`.
4. **Flip the YAML.** `enabled: true` in `config/bots/<bot>.yml`. Commit the change. Tag it.
5. **Run with `--dashboard`.** First live run goes with `python -m bot.runtime --bots config/bots/ --dashboard` so the operator can watch heartbeats + per-bot status in the v2 React UI (see "Dashboard v2" below).

The `FleetRuntime` will refuse to boot a bot with `combine_intraday` risk + `always` schedule (`live_only_guard`). That's a Topstep ToS thing — Combine accounts must flatten by 15:10 CT.

## Where things live

| Path | What |
| --- | --- |
| `src/bot/` | All runtime code. |
| `src/bot/runtime/` | Fleet orchestration, CLI, lifecycle hooks. |
| `src/bot/risk/` | `TopstepRiskGate`, policies (Combine / EFA), news calendar. |
| `src/bot/strategy/` | Strategies (ORB, trend, mean reversion, signal). |
| `src/bot/backtest/` | Backtest engine, `SimExecutionClient`, tracker. |
| `src/bot/execution/` | Broker adapters (IB, TopstepX, sim). |
| `src/bot/journal/` | Per-bot SQLite journal + queries. |
| `src/bot/dashboard/` | FastAPI side-car: SPA host (v2), REST + WS API, legacy v1 HTML. |
| `dashboard-ui/` | React + Vite + shadcn/ui frontend; built to `src/bot/dashboard/v2/static/dist/`. |
| `config/bots/*.yml` | The 6 bot specs. |
| `config/profiles/` | Strategy parameter profiles. |
| `tests/` | Unit + integration tests (~990 total). |
| `tests/integration/` | Multi-component e2e — per-bot + full fleet. |
| `docs/superpowers/specs/2026-05-22-futures-bot/` | Architecture specs (00 - 10). |
| `docs/superpowers/plans/` | Implementation plans (1 - 22). |
| `state/` | Runtime artifacts (journal DBs, proof bundles, heartbeats). |
| `deploy/` | launchd plist + deploy helpers (macOS). |

## Dashboard v2 (Plan 23)

The dashboard ships as a React SPA served by the FastAPI side-car. Open
`http://127.0.0.1:8765/` after starting the fleet with `--dashboard`.

```bash
# Build the SPA bundle once (re-run after pulling frontend changes).
cd dashboard-ui && pnpm install && pnpm build && cd ..

# Start the fleet with the dashboard.
python -m bot.runtime --bots config/bots/ --dashboard
# → SPA at http://127.0.0.1:8765/
# → REST + WS under /api/* and /ws
# → Legacy Jinja fleet/bot pages at /v1/ (read-only fallback)
```

What the dashboard gives the operator:

- **Overview** — fleet grid + aggregated account roll-up + heartbeat
  indicator + live `account_update` / `fill` events via WebSocket.
- **Bot detail** — per-bot intent (`"Watching for ORB breakout > X"`),
  equity curve (TradingView Lightweight Charts), positions, recent
  fills, and a `Tune Bot` drawer (ParamsEditor) that writes
  `strategy_params` / `risk_params` / `schedule_params` overrides
  scoped to the active profile.
- **Profiles** — per-user multi-tenant overrides under
  `state/profiles/<name>/`. Create / fork / delete / activate. The
  `default` profile cannot be deleted. Activation flips the active
  marker; restart the fleet to rebuild bots with the new effective
  spec.
- **Settings** — theme / refresh-rate / timezone, persisted to the
  active profile's `prefs.json` via `PUT /api/profiles/{name}/prefs`.
- **Flatten all** — kill-switch button in the topbar. Confirmation
  modal; one click on confirm calls `force_flatten_now()` for every
  bot's RiskGate (cancels working orders + closes positions).

Profile layout on disk (filesystem-isolated; one user's overrides cannot
leak into another's):

```
state/profiles/
├── default/
│   ├── overrides.yaml      # {} initially
│   ├── prefs.json
│   ├── history.jsonl       # append-only audit
│   └── .lock               # fcntl flock sentinel
└── <username>/             # auto-created on first run
    └── …
```

## Operational footguns (read these)

- **iCloud sync corrupts SQLite WAL.** `bot.runtime.icloud_check` warns at startup; move `state/` outside `~/Library/Mobile Documents/` for production.
- **15:10 CT hard-flat is policy-driven.** `CombineIntradayDrawdown` enforces it; the two EFA policies do not. Don't manually re-add it via a schedule cutoff — the gate is the source of truth.
- **TopstepX bans VPS / VPN.** Live runs MUST be from the operator's own host. See `bot.runtime.host_guard`.
- **`account_max_mini` defaults to 5** (Topstep $50K Combine). Bigger accounts pass `--account-max-mini 10` ($100K), 15 ($150K), etc.
- **Lux Bot** needs either `DISCORD_BOT_TOKEN` env (production) or `LUX_BOT_FIXTURE_PATH` env (replay) before boot — or it will fail loudly at registry-build time.

## Next steps

- Read `docs/superpowers/specs/2026-05-22-futures-bot/00-architecture-overview.md`.
- Skim `docs/superpowers/plans/` — 22 chronological plans (`2026-05-2*-plan-NN-...`) trace the codebase by feature. Reading them in order is the fastest path to understanding why a given piece of code looks the way it does.
- Run the full-fleet smoke test: `pytest tests/integration/test_full_fleet_smoke.py -v`. It boots all 6 bots concurrently and is the single best demonstration of what the system does.
