# Topstep Futures Trading Bot — Spec Index

Quick-navigation file. Read `00-architecture-overview.md` first; everything else assumes its locked decisions.

## Reading order

1. **`00-architecture-overview.md`** — start here. 17 locked decisions, Topstep rule constants, hexagonal architecture diagram, critical defensive items.
2. **`04-risk-engine.md`** — load-bearing safety component. Read second, even if you skim other specs. A bug here is real-money loss.
3. **`02-execution-clients.md`** — broker adapters (IB paper + TopstepX live). Contains the `SIDE_BUY=0` footgun defense.
4. **`01-data-pipeline.md`**, **`03-strategies.md`**, **`05-backtest-harness.md`**, **`06-observability.md`**, **`07-config-and-deploy.md`** — read as needed.

## What each file owns

| # | File | One-line purpose |
|---|---|---|
| 00 | `00-architecture-overview.md` | The contract every sibling spec inherits. |
| 01 | `01-data-pipeline.md` | OHLCV in, identical schema for backtest + live. |
| 02 | `02-execution-clients.md` | OrderIntent → broker. The only file with broker wire formats. |
| 03 | `03-strategies.md` | 5-min ORB rules. Surge + Maintenance YAML profiles. |
| 04 | `04-risk-engine.md` | Topstep rule enforcement. Force-flatten triggers. |
| 05 | `05-backtest-harness.md` | Walk-forward, Monte Carlo, parameter sweep, rule-replay. |
| 06 | `06-observability.md` | Logs, SQLite journal, Telegram alerts. |
| 07 | `07-config-and-deploy.md` | Config schema, secrets, Docker, LaunchAgent, restart contract. |
| 08 | `08-proof-surface.md` | Per-bot proof bundle (StrategyReport JSON + equity PNG + HTML). |
| 09 | `09-bot-lineup.md` | The six VSL-aligned bots — strategies, schedules, risk policies. |
| 10 | `10-dashboard-allocator.md` | Local read-only dashboard (v1) + cross-bot FleetAllocator. |
| 11 | `11-dashboard-v2.md` | React SPA + REST + WS + profile overlay (Plan 23). |

## Cross-reference cheat sheet

If you change something, here's what depends on it:

- **`OrderIntent` shape** → defined in `02 §4`, used by `03 §4`, `04 §4.2`, `05 §4`, `06 §3.5`.
- **`AccountState`** → defined in `04 §4.1`, populated by `02` (broker queries) + `06` (journal), consumed by `04 §3.2`.
- **`Bar` / `Tick`** → defined in `00 §3` (informal) + `01 §4` (canonical), used by `03`, `05`.
- **Topstep rule constants** → table in `00 §5`. `04` is the only file that imports and applies them.
- **Force-flatten contract** → owned by `04 §3.5`. Triggered by clock (15:10 CT), equity touch, broker-down-deadline (`02 §3.3` IB and `02 §3.3` TopstepX).
- **Data-feed disconnect → force-flatten** → owned by `01 §3.3` (>30s with open position) handing off to `04`.
- **TopstepX SignalR reconnect deadline** → 90s in `02 §3.3`, hands off to `04` force-flatten.

## Critical defensive items (every spec must respect)

Surfaced in `00 §7`. Listed here for quick reference:

1. **TopstepX `side` is inverted**: `0`=BUY, `1`=SELL. Hardcoded in `02 §3.4` with required unit test.
2. **Combine MLL is on UNREALIZED P&L in real time** → tick-driven `AccountState` updates (`04 §3.4`), not fill-driven.
3. **Hard flat by 15:10 CT** → timezone-aware clock alert (`04 §3.5`), DST-safe via `zoneinfo`.
4. **News throttle** → `04 §3.8` reads `news_calendar.yml`.
5. **VPS / VPN ban** → hostname-based guard at startup (`07 §3.6 step 3`).
6. **Broker truth on restart** → reconcile vs journal, refuse start on mismatch (`07 §3.6`).
7. **No multi-strategy registry in v1** → Surge + Maintenance are YAML profiles, not classes.

## Research basis (in `../research/`)

- `topstep-rules.md` — rule constants source.
- `prop-firm-strategy-literature.md` — Surge + Maintenance candidates, anti-patterns.
- `alpaca-futures-api.md` — confirms Alpaca is OUT (no futures in 2026).
- `tradovate-projectx-apis.md` — broker API quirks (the `side` inversion lives here).
- `backtesting-frameworks.md` — Nautilus rationale.
- `futures-data-sources.md` — FirstRateData + IB data source.
- `bot-architecture-patterns.md` — hexagonal core, broker-as-source-of-truth.

## Status

Spec phase complete. Awaiting user review at the brainstorming-skill review gate. Next: transition to `superpowers:writing-plans` to convert specs into an executable implementation plan.

## Inline fixes during self-review (already applied)

1. `03` — `OrderIntent` field-name mismatch with `02` owner (would have `TypeError` on construction).
2. `04` — EFA scaling-plan keyed off absolute equity instead of accumulated profit (would silently bypass scaling rule on a $50K EFA).
3. `04` — `AccountState.account_size_key` → `account_size` to match rule-4 reference.
4. `07` — `TelegramConfig.min_severity` `"WARNING"` → `"WARN"` to match `06`'s canonical name.

## Additional fixes after advisor pass (already applied)

5. `02` — added `Position` dataclass (was referenced but undefined).
6. `02` — added `OrderIntent` helper methods (`signed_qty`, `is_open_increasing_exposure`, `is_market_or_limit_open`, `with_stop`) that `04` calls but `02` didn't define.
7. `04` — env-conditional tick-cadence assertion (was unconditional 1 Hz, which would have prevented `05-backtest-harness` from instantiating the gate; now exempt in `env=backtest`).
8. `06` — journal impl sketch standardized on `aiosqlite` (async) to match `07`'s Dockerfile dep; was inconsistently using sync `sqlite3`.

## Known parked items needing user input (not blocking)

1. EFA scaling-plan thresholds — Medium confidence; verify from TopstepX Trade Report before EFA live.
2. Live-mode hostname whitelist — needs your actual Mac hostname (`scutil --get LocalHostName`).
3. Working tree currently in iCloud Drive — must move to local disk before live install.
