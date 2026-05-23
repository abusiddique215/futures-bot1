# Production Python Futures Bot — Architecture Patterns Survey

**Research date:** 2026-05-22
**Subject:** Top-level architecture, strategy interface, risk gating, broker adapters, state, backtest/live parity, failure modes, observability, configuration — scoped to a solo-dev Topstep-rules-compliant NQ/MNQ bot.

---

## Bottom line (read this first)

Adopt **ports-and-adapters (hexagonal) with a single-threaded async event loop in the core** — i.e. the NautilusTrader shape, simplified. The core domain (strategy + risk gate + position state) talks to the outside world (market data, broker, journal, alerts) only through interfaces. One in-process event loop fans events into the strategy; no actor framework, no message broker, no CQRS, no event-sourcing. SQLite is journal + reconciliation truth, not the event store.

The three patterns to adopt now:

1. **Risk engine as a synchronous pre-trade gatekeeper.** Strategy never calls the broker directly; it emits an `OrderIntent` that the risk engine either approves (forwards to the broker port) or denies (returns a typed rejection). This is the only place Topstep rules live. NautilusTrader's `RiskEngine` is the canonical reference. ([NautilusTrader Architecture — nautilustrader.io/docs/latest/concepts/architecture/](https://nautilustrader.io/docs/latest/concepts/architecture/))
2. **One Strategy class, two drivers (replay + live) feeding identical `on_bar` / `on_fill` callbacks.** No "backtest version" of the strategy. Backtest is a historical-data driver pushing bars through the same event loop, with a simulated broker port. This is how Nautilus, Jesse, and Lean all achieve research-to-live parity.
3. **Broker truth on restart, journal for audit.** On startup, query the broker for open positions/orders, reconcile against the SQLite journal, and refuse to start if they disagree. Don't try to event-source state — the broker already is the source of truth.

The antipattern that will tank this project: **building a multi-strategy plugin framework before two strategies exist.** Surge and Maintenance are two parameter sets on one strategy (or at most two subclasses sharing a base), not a plugin system. CLAUDE.md §2 ("no flexibility that wasn't requested") applies hard here.

---

## Important correction to the brief

The brief says the bot "paper-trades via Alpaca today" and "later deploys via a prop-firm-compatible adapter (Tradovate/Rithmic)." Two things changed since that was written:

1. **Alpaca does not offer futures of any kind in 2026.** Documented in the sibling research file `alpaca-futures-api.md` — Alpaca staff Feb 2026: "Futures are not currently on the project timelines for the next two quarters." NQ/MNQ paper trading on Alpaca is not possible. The "today" adapter has to be either (a) a TopstepX paper sub-account, (b) an internal paper simulator fed by CME-data, or (c) a different broker (e.g., Tradovate demo). Pick before designing the adapter — the choice changes interface shape.
2. **Topstep launched a first-party API in 2025/2026** — the **ProjectX Gateway API**, accessed via the TopstepX platform, $29/month subscription with 50% off for Topstep traders. ([TopstepX API Access — help.topstep.com/en/articles/11187768-topstepx-api-access](https://help.topstep.com/en/articles/11187768-topstepx-api-access), [ProjectX Gateway API docs — gateway.docs.projectx.com](https://gateway.docs.projectx.com/)). REST + SignalR/WebSocket. There is a mature async Python client: **`project-x-py` v3.3.4** by TexasCoding ([github.com/TexasCoding/project-x-py](https://github.com/TexasCoding/project-x-py)). This **replaces Tradovate/Rithmic as the live adapter target** — both for funded *and* eval accounts. The Rithmic path is no longer required.

Net effect: the adapter problem simplifies. The "today" adapter (paper) and the "later" adapter (funded) can both be `TopstepXAdapter` against the same ProjectX API, just pointed at different accounts. Alpaca drops from the picture for the futures bot.

---

## 1. Top-level architecture style

Five candidates were evaluated against the solo-dev constraint (binding constraint is cognitive load, per CLAUDE.md §2).

| Style | Best at | Worst at | Solo-dev fit |
|---|---|---|---|
| **Layered (data → strategy → risk → execution)** | Clarity of dependency direction | Tends toward request/response thinking; awkward for async event flow | Good as an *internal* organizing principle inside the hexagonal core |
| **Event-driven actor model** (Nautilus, Lean) | Determinism, backtest/live parity, async fan-out | Steep learning curve; actor frameworks are heavy | Right idea (event loop) but actor *framework* is overkill for solo dev |
| **Pipes-and-filters** | Stateless transforms | Strategies are inherently stateful (positions, indicators) — poor fit | No |
| **CQRS / event-sourced** | Audit, replay, distributed scaling | Massive complexity tax; needs read-model projection; useless when broker is already source of truth | No — antipattern at this scope |
| **Ports-and-adapters (hexagonal)** | Decouples core from broker/data/journal; easy to swap Alpaca↔TopstepX, real↔simulated | Slightly more upfront interface design | **Best fit** |

**Recommendation: hexagonal core with one async event loop inside it.** The core knows about `MarketDataPort`, `BrokerPort`, `JournalPort`, `AlertPort`, `ClockPort` — nothing else. Adapters implement those ports. Within the core, events flow: `MarketDataPort` → `EventBus` → `Strategy` → `OrderIntent` → `RiskEngine` → `BrokerPort` → `OrderEvent` → back through `EventBus` to `Strategy.on_fill` and `JournalPort`. One `asyncio` event loop runs the whole thing. NautilusTrader does this at scale; we do it at solo-dev scale by omitting the Rust core, the message bus abstraction, and the actor framework.

This is essentially NautilusTrader's shape ([nautilustrader.io/docs/latest/concepts/architecture/](https://nautilustrader.io/docs/latest/concepts/architecture/)) — "combines event-driven, actor-model, ports-and-adapters, DDD" — minus the actor framework and minus Rust. We keep the parts that earn their complexity (ports, event loop, pre-trade risk gate) and drop the parts that don't (separate kernel, message bus library, finite-state-machine for component lifecycle).

---

## 2. Strategy interface design

Three reference implementations were compared:

**NautilusTrader** ([example: ema_cross.py](https://github.com/nautechsystems/nautilus_trader/blob/master/nautilus_trader/examples/strategies/ema_cross.py)) — Strategy inherits from `Strategy` (an actor), overrides per-event callbacks:
- `on_start()`, `on_stop()`, `on_reset()`
- `on_bar(bar)`, `on_quote_tick(tick)`, `on_trade_tick(tick)`
- `on_order_event(event)` (covers accepted, filled, rejected, canceled)
- `on_position_event(event)`
- Strategy calls `self.submit_order(order)` — internally routed through `RiskEngine` first.
- Indicators are registered via `self.register_indicator_for_bars(bar_type, indicator)` and update automatically when bars arrive.

**Freqtrade IStrategy** ([docs.freqtrade.io](https://www.freqtrade.io/en/stable/strategy-customization/)) — dataframe-pass style:
- `populate_indicators(dataframe, metadata)` — add indicator columns
- `populate_entry_trend(dataframe, metadata)` — set `enter_long`/`enter_short` columns
- `populate_exit_trend(dataframe, metadata)` — set `exit_long`/`exit_short` columns
- Different mental model: vectorized columnar transforms over the whole history each tick. Works for crypto where signals are simple boolean conditions; poor fit for intraday futures with tight risk rules where you need to react to a specific fill.

**Jesse** ([jesse-ai/jesse](https://github.com/jesse-ai/jesse)) — class-based, per-candle:
- `should_long()`, `should_short()`, `should_cancel()`
- `go_long()`, `go_short()` (set entry/stop/take-profit together)
- `update_position()`, `on_open_position()`, `on_close_position()`
- Per-candle execution via `_step_simulator()`. Strategy doesn't see ticks — only candles.

**Recommendation for this project: NautilusTrader-style per-event callbacks**, because Topstep rules are event-shaped (a trailing-drawdown breach is triggered by a *fill*, not by a candle close), and because the bot must react to order events (partial fills, rejections) not just bars. Concretely:

```python
class Strategy(Protocol):
    def on_start(self, ctx: StrategyContext) -> None: ...
    def on_bar(self, bar: Bar) -> None: ...                # 1-min or whatever timeframe
    def on_order_event(self, event: OrderEvent) -> None: ... # accepted/filled/rejected/canceled
    def on_position_event(self, event: PositionEvent) -> None: ...
    def on_clock(self, now: datetime) -> None: ...         # for flat-by-time enforcement
```

No `on_tick` for v1 — Topstep doesn't reward tick-level latency and ticks make backtesting 100x slower. Add later only if a strategy actually needs it. Indicators: pass a simple `IndicatorBuffer` into the strategy at construction (rolling window with `update(bar)` and `value` properties); don't build an indicator-registration framework. Parameters: pydantic `BaseModel` per strategy, loaded from YAML. Multiple strategies: **don't compose them in v1** — pick one strategy, two parameter profiles (Surge / Maintenance). Strategy composition is the antipattern flagged in the bottom line.

---

## 3. Risk / rule-engine pattern

The pattern: **synchronous pre-trade gatekeeper**, not a decorator, not middleware-chain configuration, not a saga.

```
Strategy.on_bar
  └── strategy emits OrderIntent
        └── RiskEngine.check(intent, current_state) -> Approved | Denied(reason)
              ├── Approved → BrokerPort.submit(order); journal.record(intent, approved)
              └── Denied  → strategy receives OrderDenied event; journal.record(intent, denied, reason)
```

Key properties:
- **Strategy cannot bypass it.** The strategy doesn't have a reference to `BrokerPort`. The only way out of the core is through `OrderIntent`, and only `RiskEngine` consumes those.
- **All Topstep rules live in one place.** Daily-loss, trailing drawdown, max contracts, flat-by-time, max-position-per-symbol. One file. One test file. The strategy is rule-agnostic.
- **Stateful but deterministic.** RiskEngine holds running session state: realized P&L today, current peak-to-trough drawdown vs the trailing threshold, current open contracts. State derived from fills, not from strategy intent. Reset boundary is the session boundary (5pm CT for Topstep, configurable).
- **Composable rules.** Each rule is a small object with `check(intent, state) -> Optional[Denial]`. Engine runs them in order; first denial wins. Easy to test in isolation.
- **Drawdown policy is swappable, not hard-coded.** Topstep's trailing-drawdown calc differs by program stage — historically Combine has used an intraday peak, while funded (XFA) accounts have used an end-of-day peak that freezes once equity reaches a threshold above the starting balance. These rules change occasionally. Encode the calc as a `DrawdownPolicy` strategy object (e.g., `CombineIntradayDrawdown`, `FundedEodDrawdown`) selected by config per environment. Two failure modes if you don't: (a) modelling intraday-peak against a funded account → bot self-halts on phantom breaches the broker doesn't recognize; (b) modelling EOD-peak against a Combine account → bot lets a real rule breach through. Verify the current calc against the active Topstep rulebook before each new program stage.

Reference implementations to study:
- **NautilusTrader `RiskEngine`** — production prop-quality reference. Pre-trade checks for position/notional limits, order rate limits, returns `OrderDenied` events. Source: [nautilus_trader/risk/engine.pyx](https://github.com/nautechsystems/nautilus_trader/tree/master/nautilus_trader/risk).
- **Jesse risk management** — simpler, position-sized risk per trade based on stop distance. Less applicable to Topstep daily/trailing rules but useful for per-trade sizing patterns.
- **No public Topstep-specific bot is worth recommending** — most are private repos or bot-builder GUIs. Implement the Topstep rules directly from the Topstep program rulebook ([topstep.com/programs/trading-combine/rules](https://www.topstep.com/), retrieve current rules; rules change occasionally).

**Anti-patterns observed in surveyed code:**
- Putting risk checks inside the strategy ("if drawdown > X: return"). Inevitable rule duplication across strategies; impossible to audit.
- Decorator pattern (`@check_drawdown`) on strategy methods. Hides control flow, and doesn't compose with stateful rules.
- Middleware-chain configuration in YAML. Over-engineered for a fixed rulebook from one prop firm.

---

## 4. Broker adapter pattern

**Common interface (the `BrokerPort`):**

```python
class BrokerPort(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def submit(self, order: Order) -> OrderAck: ...
    async def cancel(self, client_order_id: str) -> CancelAck: ...
    async def modify(self, client_order_id: str, **changes) -> ModifyAck: ...
    async def get_positions(self) -> list[Position]: ...   # used on startup reconcile
    async def get_open_orders(self) -> list[Order]: ...    # used on startup reconcile
    async def get_account(self) -> AccountSnapshot: ...    # equity, day P&L, etc.
    # event streams, exposed as async iterators or callback registration
    def on_order_event(self, handler: Callable[[OrderEvent], None]) -> None: ...
    def on_fill(self, handler: Callable[[Fill], None]) -> None: ...
    def on_account_update(self, handler: Callable[[AccountSnapshot], None]) -> None: ...
```

Adapters:
- **`TopstepXAdapter`** — the only real adapter. Wraps `project-x-py` ([github.com/TexasCoding/project-x-py](https://github.com/TexasCoding/project-x-py)). REST for orders/positions/account, SignalR WebSocket for real-time updates. Use for both paper (TopstepX Combine/eval) and live (funded).
- **`SimBrokerAdapter`** — in-process simulator with configurable slippage and fill model. Used for backtests and for unit tests of the risk engine. Fed by `MarketDataPort` historical replay.
- **(`AlpacaAdapter` is dropped from the futures path.)** If we keep Alpaca for equity-correlated paper experiments, it lives in a separate bot, not this one.

**Symbol translation lives in the adapter, not the core.** The core deals only in a stable internal symbol (e.g., `NQ` for "front-month NQ continuous", `MNQ` similarly). The adapter resolves this to the exchange-listed contract (`NQM6`, `NQU6`, etc.) at session start and on roll. The strategy never sees a contract month. Roll logic is in `TopstepXAdapter` (it knows the exchange and the convention); the core gets notified only via `on_symbol_roll(old_contract, new_contract, position_state)`.

**Contract test for adapter parity:** every adapter passes the same conformance test suite — connect, submit market order, receive fill event, reconnect after WebSocket drop, query positions, idempotent cancel. `SimBrokerAdapter` and `TopstepXAdapter` must both pass. This is what prevents "works in sim, breaks live."

---

## 5. State management & resumability

**Truth model:**

| State category | Source of truth | SQLite role |
|---|---|---|
| Open positions | Broker | Mirror, for audit |
| Open orders | Broker | Mirror, for audit |
| Today's realized P&L | Broker (`get_account()`) | Mirror |
| Trailing drawdown peak | Computed locally from fill history via the active `DrawdownPolicy` (Combine intraday vs Funded EOD); the policy variant must be set per program stage in config | **Authoritative** — broker doesn't expose this metric in the same form |
| Fills history | Broker (event stream) | Authoritative for audit / backtest replay |
| Strategy indicator state | Reconstructable from bars | Not stored; rebuilt at startup from recent bars |
| Strategy parameters | Config file | Not stored |

**Restart sequence:**

```
1. Load config; instantiate strategy with parameters; do NOT start it yet.
2. Connect adapter.
3. Pull truth: get_positions(), get_open_orders(), get_account().
4. Pull SQLite journal: positions, orders, fills since last clean shutdown.
5. Reconcile:
   - If broker shows position the journal doesn't know about → ABORT and alert.
   - If journal shows position the broker doesn't have → ABORT and alert.
   - If counts/sizes match → proceed.
6. Replay last N bars to warm up strategy indicators (no orders generated during warmup).
7. Recompute trailing drawdown peak from full fills history in journal.
8. Subscribe to live data; start the event loop.
```

Refusing to start on mismatch is non-negotiable. A bot that auto-reconciles ("oh, there's a position I don't know about, I'll just adopt it") will eventually adopt a manual hedge as algo state and exit it at the worst possible moment.

**No event sourcing.** The broker is the event source. Re-deriving authoritative state from an internal event log when the broker has the same events for free is duplicated work. The advisor and the empirical reference (Nautilus uses a state machine, not event sourcing, for component state; broker is truth for position state) agree on this.

**Snapshot, don't append.** After every fill, write a row to `fills` (append-only) and *upsert* the latest `position_state` and `risk_state` rows. SQLite WAL mode. Don't engineer a snapshot/compaction system.

---

## 6. Backtest-to-live parity

The architectural guarantee: **one `Strategy` class, two drivers feeding identical events to identical callbacks.**

```
                          ┌────────────────────────┐
                          │  Strategy (one class)  │
                          │  on_bar, on_fill, …    │
                          └─────────┬──────────────┘
                                    │ same OrderIntent
                                    ▼
                          ┌────────────────────────┐
                          │      RiskEngine        │
                          └─────────┬──────────────┘
                                    │
                  ┌─────────────────┴───────────────────┐
                  ▼                                      ▼
        ┌─────────────────────┐              ┌─────────────────────┐
        │  HistoricalDriver   │              │     LiveDriver      │
        │  + SimBrokerAdapter │              │  + TopstepXAdapter  │
        │  (backtest)         │              │  (paper/live)       │
        └─────────────────────┘              └─────────────────────┘
```

Implementation rules:
- **Strategy receives only Bar/OrderEvent/PositionEvent/Clock objects.** Same types in backtest and live. No `if backtest:` branches.
- **Clock is a port.** Strategy reads time only via `ctx.clock.now()`. In backtest, clock advances by historical bar timestamps. In live, clock is `datetime.now(tz=UTC)`.
- **SimBrokerAdapter implements `BrokerPort` exactly.** Same `submit/cancel/modify/get_positions/get_open_orders/get_account` shape. Fill events generated synchronously in backtest (next bar) or with configurable latency model.
- **Bar boundaries identical.** Backtest bars are 1-min bars from your data vendor; live bars are 1-min bars from TopstepX/CME feed. If the schemas differ, normalize at the adapter layer, not in the strategy.
- **Conformance test:** record a live session's bar stream and order events; replay them through the backtest engine; assert identical orders are generated. Catches drift between paths.

This is the most underrated property of NautilusTrader and Jesse (both explicitly tout "same code, backtest and live"). It's also where most homegrown bots fail — they write a backtest that takes a `DataFrame` and a live bot that takes a `WebSocketClient`, and the strategy logic ends up doubled.

---

## 7. Failure modes & graceful degradation

The rule: **on any uncertainty, flatten and pause, don't guess.** Topstep rule violations are unrecoverable; missed P&L is recoverable.

| Failure | Detection | Response |
|---|---|---|
| WebSocket disconnect (market data) | Heartbeat timeout (e.g., no message for 30s during RTH) | Pause new entries; existing stops remain on broker. Reconnect with exponential backoff. After 3 min of no data, flatten via broker REST and stop trading for the session. Alert. |
| WebSocket disconnect (order updates) | Same | More serious — we may have phantom fills. Immediately poll `get_open_orders()` + `get_positions()` and reconcile. If reconcile fails, flatten and stop. |
| Broker REST 5xx on order submission | HTTP status / exception | Retry with backoff up to 3 times within order's validity window. On final failure, treat as denied; alert. Never duplicate-submit (use deterministic `client_order_id`). |
| Broker REST timeout on order submission (unknown ack state) | Timeout, no response | **Do not retry blindly.** Poll `get_open_orders()` by `client_order_id`. If found → it succeeded. If not → safe to retry. This is the only correct pattern for at-most-once order submission. |
| Data gap (missed bars on reconnect) | Bar timestamp jump | Backfill via REST historical query before resuming event loop. If gap > N bars, treat indicators as cold; warmup-mode (no entries) for K bars. |
| Partial fill | Fill event with `qty < order.qty` | Update position state with partial qty. Strategy decides whether to wait, cancel residual, or modify. Don't auto-cancel — partial fills are normal. |
| Slippage outside model | Fill price > configured tolerance from intent | Log loudly, alert, but accept the fill — it's done. Risk engine recomputes drawdown from actual fill price. |
| Approaching Topstep loss limit | RiskEngine check on every fill | At 80% of daily loss limit: refuse new entries, manage existing only. At 95%: flatten and stop for the day. Alert at each threshold. |
| Approaching flat-by-time | Clock event 5 min before cutoff | Refuse new entries. At cutoff: cancel working orders, market-flatten any position. |
| Process crash | Supervisor / systemd / Docker restart policy | Restart triggers the reconcile-on-startup sequence (§5). If reconcile fails, exit non-zero and alert — do not auto-trade after an unclear restart. |
| Clock skew (Mac sleep, VM time drift) | Compare local clock to broker server time on every heartbeat | If drift > 2s, alert; if > 10s, flatten and stop. Topstep flat-by-time rules use exchange time, and clock skew can cause silent rule violations. |

Three-state operating mode: `RUNNING` (normal), `MANAGE_ONLY` (no new entries, manage existing), `HALTED` (no orders, alerting). Transitions are one-way down (only manual restart goes back up). Risk engine and supervisor both can force state down.

---

## 8. Observability

**Structured logs.** JSON lines, one event per line. `loguru` or stdlib `logging` with a JSON formatter. Required fields on every event:
- `ts` (UTC ISO8601 with microseconds)
- `session_id` (per bot process start)
- `level` (DEBUG/INFO/WARNING/ERROR/CRITICAL)
- `event` (string enum: `bar`, `intent`, `order_submitted`, `order_filled`, `risk_denied`, `reconcile_ok`, `reconcile_mismatch`, etc.)
- `symbol`, `qty`, `price`, `client_order_id` when relevant
- `mode` (`surge` / `maintenance`)
- `strategy_state` (small dict: position, day_pnl, drawdown_from_peak)

**Trade journal (SQLite) schema** — minimal v1:

```sql
CREATE TABLE sessions (
  session_id TEXT PRIMARY KEY,
  started_at TEXT, ended_at TEXT, mode TEXT,
  strategy_name TEXT, strategy_params_json TEXT,
  start_equity REAL, end_equity REAL,
  end_reason TEXT  -- clean_shutdown | risk_halt | crash | flat_by_time
);

CREATE TABLE intents (
  intent_id TEXT PRIMARY KEY, session_id TEXT, ts TEXT,
  symbol TEXT, side TEXT, qty INTEGER, type TEXT,
  limit_price REAL, stop_price REAL,
  decision TEXT,  -- approved | denied
  denial_reason TEXT
);

CREATE TABLE orders (
  client_order_id TEXT PRIMARY KEY, intent_id TEXT, session_id TEXT,
  submitted_at TEXT, broker_order_id TEXT,
  status TEXT,  -- pending | accepted | filled | partial | canceled | rejected
  final_qty INTEGER, avg_fill_price REAL
);

CREATE TABLE fills (
  fill_id TEXT PRIMARY KEY, client_order_id TEXT, session_id TEXT,
  ts TEXT, symbol TEXT, side TEXT, qty INTEGER, price REAL, fees REAL
);

CREATE TABLE equity_snapshots (
  session_id TEXT, ts TEXT, equity REAL, day_pnl REAL,
  open_position_qty INTEGER, drawdown_from_peak REAL,
  PRIMARY KEY (session_id, ts)
);

CREATE TABLE risk_events (
  session_id TEXT, ts TEXT, event TEXT, threshold REAL, value REAL, action TEXT
);
```

Equity snapshots every 60s + on every fill. That's enough to draw a per-session equity curve later without an analytics system.

**Telegram alerts** — discriminated by severity, not volume:
- `CRITICAL`: risk halt, reconcile mismatch, flat-by-time triggered, repeated broker errors. Sent immediately, every occurrence.
- `WARNING`: 80% loss limit, websocket reconnect, slippage outside model. Sent immediately, deduped within 5min.
- `INFO`: session start/stop, end-of-day P&L summary. Sent on event.
- *Not on Telegram*: individual fills, bar events. Those are log-only. Telegram fatigue is a real failure mode.

**No Prometheus, no Grafana, no OpenTelemetry in v1.** Solo dev, one process. Tail `journalctl` or the JSON log file. Add metrics infra only if you're running multiple bots or remote ops.

---

## 9. Configuration

**Recommendation: pydantic v2 + YAML.** Reasoning: pydantic gives type-checked config with validators (e.g., "max contracts ≥ 1", "flat-by-time before market close"), YAML is human-editable, and pydantic loads YAML cleanly via `pydantic-settings` or a `yaml.safe_load`-then-`Model.model_validate()`.

Not Python dataclasses: weaker validation, no environment overlay.
Not TOML: less ergonomic for nested config (Topstep rules are nested).
Not Python files (`config.py`): tempting but defeats the per-environment split.

**Layered config:**
```
config/
  default.yaml          # shared defaults
  environments/
    paper.yaml          # broker_endpoint=paper, max_contracts=1, alerts=warn
    funded.yaml         # broker_endpoint=live,  max_contracts=3, alerts=critical
  strategies/
    surge.yaml          # aggressive thresholds for eval
    maintenance.yaml    # conservative for funded
  topstep_rules/
    50k.yaml            # daily_loss=1000, trailing_drawdown=2000, max_contracts=3
    150k.yaml           # …
```

Merge order: `default` ← `environment` ← `strategy` ← `topstep_rules` ← env-var overrides (for secrets only — API keys never in YAML). One CLI flag selects the environment, one selects the strategy, one selects the account size. That's it.

**Secrets** in `.env` loaded by `pydantic-settings`. Never in YAML, never in git.

---

## 10. Open-source references worth reading

| Repo | License | Study this for | URL |
|---|---|---|---|
| **nautechsystems/nautilus_trader** | LGPL v3.0 | The pre-trade `RiskEngine` gatekeeper pattern, the `Strategy` actor callbacks (`on_bar`, `on_order_event`), the single-kernel backtest/live parity model. Don't import the framework — read the architecture and the `nautilus_trader/risk/` directory. | [github.com/nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) |
| **freqtrade/freqtrade** | GPL v3.0 | Telegram bot integration patterns, SQLite trade journaling, configuration layering, the supervisor/process loop. Strategy style itself (`populate_indicators`/`populate_entry_trend`) is the wrong shape for our use case but the surrounding infra is mature. | [github.com/freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) |
| **jesse-ai/jesse** | MIT (verify) | Per-candle backtest/live shared code path, `_step_simulator()` design, strategy lifecycle (`go_long`/`update_position`/`on_open_position`/`on_close_position`). Closest in spirit to what we're building, modulo asset class. | [github.com/jesse-ai/jesse](https://github.com/jesse-ai/jesse) |
| **TexasCoding/project-x-py** | check repo | The actual library we'll wrap in `TopstepXAdapter`. Read the async client, the SignalR streaming setup, and the retry/auth flow. Pin to a version; SDK is moving (v3.3.4 as of fetch). | [github.com/TexasCoding/project-x-py](https://github.com/TexasCoding/project-x-py) |

Honourable mentions, lower priority:
- **QuantConnect/Lean** (C#, but the architecture writeups are good) — for the abstract Algorithm/Securities/Portfolio model.
- **mceesincus/tsxapi4py** — alternative TopstepX Python wrapper; compare against `project-x-py` before committing.

---

## Architecture overview (the diagram for the spec)

```
┌──────────────────────────────────────────────────────────────────────┐
│                          CORE  (hexagonal)                            │
│                                                                       │
│   ┌────────────┐    OrderIntent    ┌──────────────┐                  │
│   │  Strategy  │ ─────────────────►│  RiskEngine  │                  │
│   │            │◄──── events ──────│  (Topstep)   │                  │
│   └────┬───────┘                   └──────┬───────┘                  │
│        │                                  │ approved Order            │
│        │ subscribes              ┌────────▼───────┐                  │
│        ▼                         │   EventBus     │                  │
│   ┌─────────┐                    │  (async loop)  │                  │
│   │ Indicators│                  └────────┬───────┘                  │
│   └─────────┘                             │                          │
│                                           ▼                          │
└──────────┬───────────┬───────────┬────────┬──────────┬───────────────┘
           │           │           │        │          │
       ┌───▼───┐   ┌──▼───┐   ┌────▼───┐ ┌──▼────┐ ┌──▼─────┐
       │MktData│   │Broker│   │Journal │ │Alerts │ │ Clock  │
       │ Port  │   │ Port │   │  Port  │ │ Port  │ │  Port  │
       └───┬───┘   └──┬───┘   └────┬───┘ └──┬────┘ └──┬─────┘
           │          │            │        │         │
   ┌───────▼──┐  ┌────▼──────┐  ┌──▼─────┐ ┌▼─────┐  │
   │TopstepX  │  │TopstepX   │  │ SQLite │ │Telegr│  │
   │ data feed│  │ Adapter   │  │        │ │  am  │  │
   │ adapter  │  │ (proj-x-py│  │        │ │      │  │
   │          │  │           │  │        │ │      │  │
   └──────────┘  └───────────┘  └────────┘ └──────┘  │
                                                  (system clock or
                                                   simulated clock
                                                   for backtest)
```

Backtest swap: `MktData` adapter → historical replay; `Broker` adapter → `SimBrokerAdapter`. Strategy and RiskEngine code unchanged.

---

## Gotchas for this scope (the three that matter most)

1. **Clock skew between Mac/VM/exchange will silently violate flat-by-time.** Topstep enforces flat-by-time in exchange time, your `datetime.now()` is local-system time, and a Mac coming out of sleep can be 5-10s off. Build a clock-port that compares local time to broker server time on every heartbeat and refuses to operate beyond a small tolerance. This is invisible until it bites you.
2. **"At-most-once" order submission is harder than it looks.** A REST POST that times out doesn't tell you whether the order made it. Naive retry → double position → busted trailing drawdown. The pattern: always send a deterministic `client_order_id`, and on timeout, *query* (`get_open_orders` by id) before retrying. Most homegrown bots get this wrong, and most of the time it doesn't matter — until it does, during a network blip on a winning day.
3. **Continuous-contract roll is non-trivial and lives in the adapter.** Strategy thinks it owns `NQ`. On roll day, the exchange-listed contract changes from `NQM6` to `NQU6`. If you don't handle this in the adapter (close `NQM6`, open `NQU6`, preserve drawdown state across the roll), the strategy will see a "phantom flat" followed by an "unexpected position" and the reconciler will refuse to start. Decide roll convention (first notice day? open interest threshold?) once, encode in adapter, test.

Also worth naming, less critical: the antipattern in the bottom line — **building a multi-strategy plugin framework before the second strategy exists**. Surge vs Maintenance is a config switch. Don't build a `StrategyRegistry`.

---

## Concrete recommendation, restated

**Top-level shape:** hexagonal core with one async event loop. Ports: `MarketDataPort`, `BrokerPort`, `JournalPort`, `AlertPort`, `ClockPort`. Adapters: `TopstepXAdapter` (real, via `project-x-py`), `SimBrokerAdapter` (backtest), `HistoricalReplayAdapter` (backtest market data), `SQLiteJournalAdapter`, `TelegramAlertAdapter`, `SystemClockAdapter` / `SimulatedClockAdapter`.

**Key patterns:** (1) synchronous pre-trade `RiskEngine` gatekeeper holding all Topstep rules; (2) one `Strategy` class with `on_bar` / `on_order_event` / `on_position_event` / `on_clock` callbacks, driven identically by replay or live; (3) startup reconcile against broker truth, refuse to start on mismatch.

**Explicit non-features for v1:** message bus library, actor framework, event sourcing, CQRS, multi-strategy plugin system, indicator-registration framework, Prometheus, Kubernetes, multi-account multiplexing. None of these earn their complexity until the bot is profitable and stable.

---

## Sources

Primary:
- [NautilusTrader Architecture — nautilustrader.io/docs/latest/concepts/architecture/](https://nautilustrader.io/docs/latest/concepts/architecture/)
- [NautilusTrader GitHub — github.com/nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader)
- [NautilusTrader EMA Cross example — github.com/nautechsystems/nautilus_trader/blob/master/nautilus_trader/examples/strategies/ema_cross.py](https://github.com/nautechsystems/nautilus_trader/blob/master/nautilus_trader/examples/strategies/ema_cross.py)
- [Freqtrade Strategy Customization — freqtrade.io/en/stable/strategy-customization/](https://www.freqtrade.io/en/stable/strategy-customization/)
- [Freqtrade sample_strategy.py — github.com/freqtrade/freqtrade/blob/develop/freqtrade/templates/sample_strategy.py](https://github.com/freqtrade/freqtrade/blob/develop/freqtrade/templates/sample_strategy.py)
- [Jesse GitHub — github.com/jesse-ai/jesse](https://github.com/jesse-ai/jesse)
- [TopstepX API Access — help.topstep.com/en/articles/11187768-topstepx-api-access](https://help.topstep.com/en/articles/11187768-topstepx-api-access)
- [ProjectX Gateway API docs — gateway.docs.projectx.com](https://gateway.docs.projectx.com/)
- [TexasCoding/project-x-py — github.com/TexasCoding/project-x-py](https://github.com/TexasCoding/project-x-py)
- [project-x-py docs — project-x-py.readthedocs.io](https://project-x-py.readthedocs.io/en/latest/)
- [NautilusTrader licensing — nautilustrader.io/legal/open-source-licensing/](https://nautilustrader.io/legal/open-source-licensing/)

Sibling research (this repo):
- `docs/superpowers/research/alpaca-futures-api.md` — establishes that Alpaca has no futures path, which forces the Alpaca-drops-from-the-design conclusion in this document.
- `docs/superpowers/research/futures-data-sources.md` — relevant for the historical-replay adapter for backtests.
