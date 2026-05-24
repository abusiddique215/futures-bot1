# 00 — Architecture Overview

**Project**: Topstep Futures Trading Bot
**Date**: 2026-05-22
**Status**: Spec — research phase complete, ready for implementation planning
**Owner**: abu.siddique215@gmail.com

This document is the load-bearing input for every sibling spec file in this folder. Read this before reading any of the others; every other file assumes the decisions below.

---

## 1. Mission

Build a Python-based automated futures trading bot for Topstep prop-firm Combine and Funded accounts on NQ/MNQ, with two operating modes:

- **Surge mode** — aggressive enough to hit the Combine profit target before the trailing drawdown catches up.
- **Maintenance mode** — conservative enough to never approach the trailing drawdown on a Funded account; designed to generate consistent small payouts.

Product shape modeled on `https://vsl.profit-insiders.com` (SurgeBot + maintenance bots, fully automated, set-and-forget, 24/5 operation). We are spec'ing the *structure* of that product; eventual P&L depends on which strategies test out in our backtests.

## 2. Locked decisions (with reasoning)

Every assumption a sibling spec is permitted to rely on. If you change one of these, update this section and notify the affected specs.

| # | Decision | Reasoning / Source |
|---|----------|---------------------|
| D1 | **Target prop firm: Topstep** | User selection. Lots of public algo literature. Strict but documented rules. |
| D2 | **Target instrument: MNQ (Micro E-mini Nasdaq-100)** primary, NQ-full optional later. _Plan 14 (2026-05-23): multi-market plumbing landed — NQ, MNQ, ES, MES, GC, MGC are all first-class via `bot.markets.registry.MARKETS`. Per-bot strategies (Gold Bot Plan 17, ES Scalper Plan 18) can target any registered market without per-symbol branches._ | $50K Combine has $2K MLL → one NQ-full bad trade ($20/pt × 100 pts) wipes the eval. MNQ ($2/pt) gives 10× more headroom. Both contracts allowed by Topstep. |
| D3 | **Target account size: $50K Combine** | Smallest available. Cheapest path to test the eval flow ($49/mo + $149 activation). Scale up after a Funded conversion. |
| D4 | **Two operating modes** (Surge / Maintenance), **one Strategy class** with YAML parameter profiles | Per architecture-patterns research: "don't build a multi-strategy plugin framework before the second strategy class exists." Profiles diverge in entry aggressiveness, position size, stop placement, time-of-day filter. |
| D5 | **v1 strategy: 5-min Opening Range Breakout (Zarattini–Aziz 2023)** | Most academically-validated intraday strategy on QQQ/NQ. 40-55% win rate, 1:2 R. No Topstep rule risk (no HFT, no news-trading dependency). Other candidates (Maróy intraday momentum, Larry Williams volatility breakout, Crabel NR7) live in `03-strategies.md` as v2 candidates. |
| D6 | **Paper rail: Interactive Brokers paper** account via `ib_async` | Confirmed: Alpaca has no futures in 2026. IB paper is free, supports MNQ/NQ, mature Python client. US Futures Value Bundle ($10/mo, waived at $30/mo commissions). |
| D7 | **Live rail: TopstepX API via `TexasCoding/project-x-py` SDK** | Topstep migrated off Tradovate Aug 2025. TopstepX is the only supported API. `project-x-py` is async, MIT, well-maintained (v3.5.8 Sept 2025). Same `accountId` swap moves you Practice → Combine → Funded — no second API integration needed. |
| D8 | **Runtime: NautilusTrader** (extend `Strategy`, `RiskEngine`, `ExecutionClient`) | Single engine for backtest/paper/live with **identical strategy code** — the only architectural property that delivers genuine backtest-to-live parity. Native FuturesContract specs + continuous rollover. Pre-trade `OrderDenied` rejection in Python. `clock.set_time_alert()` for force-flat. Pay 2-3 weeks learning curve. |
| D9 | **Historical data: FirstRateData** NQ + MNQ 1-min, 15+ years (~$200 one-time) | Cheapest path with quality sufficient for prop-firm-risk-tolerable backtests. Yahoo continuous NQ has stale overnight ticks — banned. |
| D10 | **Live data: IB US Futures Value Bundle** | Same broker as paper — no second integration. Bundled with the paper account. |
| D11 | **Continuous-contract roll: ratio-adjusted (proportional)** | Documented choice. Panama and ratio diverge 5-15% over 5 years on NQ — research and live MUST use the same method. See `01-data-pipeline.md` for the canonical implementation. |
| D12 | **Storage: SQLite** for trade journal + audit. **Broker is source of truth on restart.** | Per architecture-patterns: no event sourcing — the broker is already the event source. SQLite for audit/replay only. Startup reconciles journal vs broker; refuses to start on mismatch. |
| D13 | **Language: Python 3.12** | Matches Nautilus, `ib_async`, `project-x-py`. User's existing skill set. |
| D14 | **Hosting: User's physical Mac** (no cloud VM for live) | **Topstep ToS bans VPS/VPN for Funded accounts.** Docker is fine *on the Mac* as dev convenience. Cloud is fine for backtest-research-only workloads. |
| D15 | **Deployment: Docker on the Mac**, auto-start on login, structured logs to local disk | Matches D14. Mac becomes the production environment for live Topstep accounts. |
| D16 | **Observability: JSON-lines structured logs + SQLite trade journal + Telegram alerts** | Cheap, debuggable, no external dashboard service. Telegram for fill/error/rule-violation events; logs for forensics. |
| D17 | **Strategy interface: Nautilus `Strategy` subclass**, no separate base class abstraction in v1 | YAGNI per CLAUDE.md §2. If a non-Nautilus strategy provider materializes (e.g., grammatical-evolution generator), add the abstraction *then*. |

## 3. Reality check (acknowledged, not hidden)

Topstep's own published 2025 cohort data: **16.8% Combine pass rate**, **0.71% reach Live Funded**. Industry-wide algo-only data is scarcer; vendor claims of "78% bot pass rate" are marketing, not independent.

**Budget assumption**: 2–4 Combine attempts ($49 + $149 activation = $198 each at 50K tier, less with monthly resets) before either a pass or a strategic pivot. Failure mode if the bot can't pass: kill it, not your wallet.

Bot's job is **rule compliance + edge from the strategy**, not magic. The hexagonal core means the strategy is swappable in ~one file.

## 4. Top-level architecture

```
                ┌─────────────────────────────────────────────────────┐
                │   Driver  (one of: Backtest / IB-Paper / TopstepX) │
                │   pushes events: bar, tick, order_event, position  │
                └────────────────────────┬────────────────────────────┘
                                         ↓ events
                ┌─────────────────────────────────────────────────────┐
                │   Strategy   (Nautilus Strategy subclass)           │
                │   on_bar / on_tick / on_order_event / on_clock     │
                │   emits → OrderIntent (broker-agnostic)             │
                └────────────────────────┬────────────────────────────┘
                                         ↓ OrderIntent
                ┌─────────────────────────────────────────────────────┐
                │   RiskEngine   (TopstepRiskGate)                    │
                │   - approves or denies (typed rejection)            │
                │   - encodes ALL Topstep rules in one file           │
                │   - maintains phantom MLL state on every tick       │
                │   - swappable DrawdownPolicy (Combine vs Funded)    │
                └────────────────────────┬────────────────────────────┘
                                         ↓ approved Order
                ┌─────────────────────────────────────────────────────┐
                │   ExecutionClient   (Nautilus port; one per broker) │
                │   - IBExecutionClient   (paper)                     │
                │   - TopstepXExecutionClient   (live)                │
                │   - translates OrderIntent → broker-specific calls  │
                └─────────────────────────────────────────────────────┘
                                         │
                                         ↓ on every event
                ┌─────────────────────────────────────────────────────┐
                │   Journal (SQLite) + Telemetry (logs + Telegram)    │
                └─────────────────────────────────────────────────────┘
```

**Three drivers, same Strategy code**: this is the backtest-to-live parity guarantee. The conformance test suite (see `02-execution-clients.md`) asserts that `SimBroker`, `IBBroker`, and `TopstepXBroker` produce identical Strategy callback sequences given the same event stream.

**Strategy never holds a broker reference.** It cannot bypass the RiskEngine. The only way to place an order is to emit an `OrderIntent` that flows through the gate.

## 5. Topstep $50K Combine rule constants

To be encoded in `04-risk-engine.md`. Source: `docs/superpowers/research/topstep-rules.md` (High confidence).

| Constant | Value | Notes |
|----------|-------|-------|
| Profit target | $3,000 | Combine pass threshold |
| Daily Loss Limit (DLL) | $1,000 | Per calendar trading day |
| Max Loss Limit (MLL) — Combine | $2,000 | **Trailing, on unrealized P&L, real-time.** An intraday wick can liquidate. |
| Max Loss Limit — Funded (Standard EFA) | $2,000 | EoD-trailing (not intraday) |
| Max position | 5 mini OR 50 micro | Cannot mix mini and micro to exceed |
| Hard flat-by time | **3:10 PM CT** | All positions must be closed |
| Overnight positions | **Forbidden** | |
| Consistency rule (Combine) | best-day-vs-target ≤ 50% | |
| Consistency rule (EFA Consistency variant only) | best-day-vs-net-profit ≤ 40% | |
| EFA scaling | Start 2-3 contracts regardless of buying power | Full size unlocks at next-day session boundary after profit milestones |
| Profit split | 90/10 to trader | Accounts opened on/after 2026-01-12 |
| Per-payout cap (EFA Standard) | $2,000 | At 50K tier |
| News trading | "Maximum position news trading" prohibited | Bot must auto-reduce size around FOMC / NFP / CPI |
| HFT threshold | Undefined ("excessive orders/cancellations") | Self-impose: cancel-to-fill ratio cap |
| Cross-account hedging | Prohibited | Don't run correlated bots on multiple accounts |
| Remote VPS / cloud | **Prohibited** | Bot must run on user's physical machine for live |

## 6. Component map (sibling spec files)

Each file owns one part of the architecture. Files reference each other by number for stability.

| File | Owns | Reads |
|------|------|-------|
| `00-architecture-overview.md` | this doc, locked decisions, rule constants | — |
| `01-data-pipeline.md` | Historical (FirstRateData) loader, IB live WebSocket, continuous-roll method, contract calendar | research/futures-data-sources |
| `02-execution-clients.md` | `IBExecutionClient`, `TopstepXExecutionClient`, conformance test suite, `SIDE_BUY=0` defensive constants | research/alpaca-futures-api, research/tradovate-projectx-apis |
| `03-strategies.md` | `Strategy` subclass (5m ORB), Surge YAML profile, Maintenance YAML profile, v2 candidate strategies registry | research/prop-firm-strategy-literature |
| `04-risk-engine.md` | `TopstepRiskGate`, all Topstep rule encoding, phantom-MLL state machine, `DrawdownPolicy` Combine vs Funded variants, news-throttle, hard-flat trigger | research/topstep-rules |
| `05-backtest-harness.md` | Walk-forward, Monte Carlo, parameter sweep wrappers around Nautilus, walk-forward report format | research/backtesting-frameworks |
| `06-observability.md` | JSON-lines log schema, SQLite trade journal schema, Telegram alert taxonomy + thresholds, equity-curve snapshot cadence | — |
| `07-config-and-deploy.md` | Pydantic config schema, env handling, Docker layout for Mac, restart/state-recovery sequence, broker-truth reconciliation | research/bot-architecture-patterns |

## 7. Critical defensive items (every sibling spec must respect)

Non-negotiables surfaced by research. Violation = real-money loss or ToS violation.

1. **TopstepX `side` encoding is inverted**: `0` = BUY (Bid), `1` = SELL (Ask). Industry-wide silent-loss footgun.
   - `02-execution-clients.md` MUST hardcode `SIDE_BUY = 0` / `SIDE_SELL = 1` constants with loud names.
   - Unit test MUST assert: `client.translate(OrderIntent(side="BUY")) == {"side": 0, ...}`.
2. **Combine MLL is on UNREALIZED P&L in real time**.
   - `04-risk-engine.md` MUST compute phantom MLL on every tick, not on every fill.
   - Stops must be placed at a configurable **wide offset** from the MLL (default: MLL − 5 ticks safety buffer).
3. **Hard flat by 3:10 PM CT** — non-negotiable, independent of strategy state.
   - `04-risk-engine.md` schedules `clock.set_time_alert("15:10:00 America/Chicago")` → `force_flatten_all()`.
   - DST handling: use timezone-aware `America/Chicago`, never naive UTC offset.
4. **News throttle**: pre-configured FOMC / NFP / CPI calendar; risk engine auto-reduces max-position-size to 1 contract in the X-minute window around each event (default: T−5 to T+15 minutes).
5. **VPS / VPN ban**: live Topstep bot runs on user's physical Mac.
   - `07-config-and-deploy.md` provides Docker config for the Mac, NOT for any cloud target.
   - Backtest research workloads on cloud are fine (no Topstep account touched).
6. **Broker truth on restart**: on every startup, the bot:
   - Queries broker for current positions, open orders, account state.
   - Reconciles against the SQLite trade journal.
   - **Refuses to start if there is a mismatch** — operator must intervene.
   - This prevents "phantom positions" where bot thinks it's flat but broker holds an open contract.
7. **No multi-strategy registry in v1**. Surge + Maintenance are YAML profiles of the same Strategy class. Adding a registry requires a third concrete strategy that can't be expressed as a parameter profile.

## 8. Out of scope for v1

YAGNI items consciously excluded. Each is a candidate for a future spec, not this one.

- ML-based signal generation (regime classifier, news predictor)
- Grammatical evolution auto-strategy generator
- Multi-asset trading (only NQ/MNQ in v1)
- Multi-account orchestration (one bot, one account at a time)
- Web dashboard (logs + Telegram suffice for v1)
- Cloud deployment for live (Topstep ToS)
- Live broker beyond IB + TopstepX (no Tradovate adapter)
- Options on futures
- Replay-debugger for production state machine (audit logs cover post-mortem)

## 9. Open questions parked for sibling specs to resolve

Each linked spec resolves these inline; this list exists so they don't get lost.

- `01-data-pipeline`: Does FirstRateData include exchange-traded volume or just print volume? If only print, do we need a separate volume source for the ORB?
- `02-execution-clients`: TopstepX SignalR reconnect strategy — exponential backoff or fixed interval? What's the reconnect deadline before we force-flatten?
- `03-strategies`: ORB window — first 5 minutes only, or first 15 minutes? Zarattini-Aziz used 5; community variants use 15. Resolve via backtest sweep.
- `04-risk-engine`: News calendar source — is there a free Python-accessible economic-calendar API in 2026, or do we maintain a static YAML?
- `05-backtest-harness`: Walk-forward window — 6 months train / 2 months test (3:1 ratio standard) or longer?
- `06-observability`: Telegram alert frequency cap — how do we avoid alert-fatigue without missing real signals?
- `07-config-and-deploy`: macOS LaunchAgent vs cron @reboot vs `launchctl` for auto-start? What's the recovery contract if the bot crashes mid-trade?

## 10. References

- VSL product reference (shape only, not method): `https://vsl.profit-insiders.com`
- Topstep rules research: `../research/topstep-rules.md`
- Strategy literature research: `../research/prop-firm-strategy-literature.md`
- Broker API research (TopstepX + Tradovate): `../research/tradovate-projectx-apis.md`
- Alpaca (negative result): `../research/alpaca-futures-api.md`
- Backtester framework research: `../research/backtesting-frameworks.md`
- Data sources research: `../research/futures-data-sources.md`
- Architecture patterns research: `../research/bot-architecture-patterns.md`
- Existing Harvard RBI repo (reference implementation, Hyperliquid not Topstep): `../../../tradingbot/aistudydata/Harvard-Algorithmic-Trading-with-AI/`
