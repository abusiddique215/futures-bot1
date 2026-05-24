# 10 — Dashboard + Cross-Bot Allocator

Plan 21 deliverables. Two distinct features sharing the FleetRuntime
lifecycle: a read-only local monitoring dashboard and a cross-bot
account-position cap (the "FleetAllocator"). Both ship behind one CLI
flag (`--dashboard`) so the operator gets monitoring + safety as a
single opt-in step.

## Why these two together

The VSL-aligned bot family (Plans 14-20) is a single Topstep
account-style configuration shared across N bots — SurgeBot, PropBot,
Gold Bot, ES Scalper, Lux Bot, NQ Maintenance. Plan 12 established the
single shared broker per fleet but punted on "what if two bots each
open +5 MNQ" — Plan 21 is where that contention gets a real answer.
Concurrent with the safety work, the operator needs a way to see what
the fleet is doing without tailing six SQLite files; the dashboard is
the answer.

## FleetAllocator (`bot.runtime.fleet.allocator`)

### Contract

```python
allocator = FleetAllocator(
    account_max_mini=5,         # Topstep $50K Combine baseline
    market_lookup=get_market,   # from bot.markets.registry
)
result = await allocator.approve_intent(
    bot_name="propbot_nq",
    intent=OrderIntent(symbol="MNQH26", side="BUY", quantity=3, ...),
    fleet_positions={"surgebot_nq": {"MNQH26": 2}, "propbot_nq": {}},
)
# -> ApprovedOrder | OrderDenied(rule="FLEET_POSITION_CAP")
```

### Algorithm (under `asyncio.Lock` for race safety)

1. `market = market_lookup(intent.symbol)` — handles bare roots
   ("MNQ") and contract-suffixed forms ("MNQH26") transparently.
2. `cap = account_max_mini * market.micro_to_full_ratio if is_micro
    else account_max_mini`. So `5` becomes `50` contracts for micros,
   `5` for full minis.
3. `settled = sum(positions[symbol] for positions in fleet_positions.values())`.
4. `pending = sum(pending[symbol] for pending in self._pending.values())`.
   Pending allocations are intents this allocator approved but for which
   the bot's tracker hasn't seen the fill yet — without this, two
   concurrent bots could both pass the cap check using stale tracker
   state.
5. `projected = settled + pending + intent.signed_qty()`. Deny iff
   `abs(projected) > cap`.

### Lifecycle

- `approve_intent` → if approved, allocator records the bot's pending
  contribution in `_pending[bot_name][symbol]`.
- `settle_intent` → called by `LiveTradingLoop` AFTER `record_fill` so
  the tracker now reflects the qty; the pending slot is cleared.
- `release_intent` → escape hatch for broker rejects (v1: not wired
  from `LiveTradingLoop`; the SimExecutionClient doesn't reject. Reserved
  for future TopstepX-reject propagation.)

### Where it runs

`LiveTradingLoop` calls `await allocator.approve_intent(...)` AFTER the
per-bot risk gate approves but BEFORE `broker.place_order(...)`. The
ordering is load-bearing: per-bot enforcement first (own DLL/MLL/etc),
fleet-wide cap second (shared account ceiling). A FLEET_POSITION_CAP
denial is journalled the same as any other risk denial so the operator
sees it in the dashboard's recent-trades view.

### Why this is the right abstraction

Account-level position caps live OUTSIDE per-bot policy because Topstep
enforces them on the entire account, not per-strategy. Putting the
check inside `DrawdownPolicy.max_position` would force every policy
class to know about the fleet, which is the wrong direction of
dependency. The allocator lives next to FleetRuntime — the layer that
already knows "we share one broker across N bots" — and the per-bot
gate stays pure.

## Strategy.setup() hook (FleetRuntime lifecycle)

Plan 19's `SignalStrategy` spawns an `asyncio.Task` (the Discord pump)
that drains the source into its deque. Before Plan 21, FleetRuntime
didn't know to start this task — flipping `enabled: true` on
`lux_bot.yml` was a silent no-op in production. Plan 21 adds the
missing hook:

```python
# bot.runtime.fleet.runtime — pre-loop:
if hasattr(bot.strategy, "setup"):
    result = bot.strategy.setup()
    if asyncio.iscoroutine(result):
        await result
```

The hook is opt-in via `hasattr` so the Strategy Protocol stays pure —
Plan 11 strategies (ORB, MeanReversion, TrendFollowing) don't need to
add a no-op `setup`. SignalStrategy's `setup` calls `self.start()`;
future async-driven strategies follow the same pattern.

## Dashboard (`bot.dashboard.*`)

### Architecture

- `bot.dashboard.queries` — pure data layer. Sync sqlite3 reads using
  `file:<path>?mode=ro` URIs so the dashboard can NEVER race the
  LiveTradingLoop's WAL writer. No FastAPI dependency in this module.
- `bot.dashboard.app.create_app(state)` — FastAPI factory. Stashes the
  `DashboardState` (bots_dir + heartbeat_path) + Jinja2 environment on
  `app.state` so the route handlers don't need module-level globals.
- `bot.dashboard.routes.build_router()` — three GETs: `/`, `/bots/{name}`,
  `/healthz`. All HTML responses inherit `base.html.j2` which carries
  the `<meta http-equiv="refresh" content="5">` directive; the
  operator's browser polls every 5 seconds instead of holding open
  WebSockets / SSE channels.

### Templates

- `base.html.j2` — single shared CSS + the auto-refresh meta tag.
- `fleet.html.j2` — one table row per bot: name (link), symbol,
  enabled flag, status badge (running / no_data).
- `bot_detail.html.j2` — summary table (equity / realized P&L / open
  positions), recent-trades table (newest 20 fills), equity-curve tail
  (last 20 snapshots).

### Side-car wiring

`FleetRuntime.run()` spawns a `uvicorn.Server.serve()` task alongside
the per-bot LiveTradingLoop tasks when `dashboard_port` is set. The
server binds to `127.0.0.1` ONLY — never `0.0.0.0`. A dashboard crash
is caught in the `_serve()` wrapper (logged, not propagated) so a
broken template can't take the fleet down.

Graceful shutdown via `FleetRuntime.request_shutdown()`:
1. Sets the stop_event each LiveTradingLoop watches.
2. Sets `server.should_exit = True` so uvicorn drains in-flight
   requests and exits cleanly.
3. The `run()` finally block waits up to 2s for the server task to
   complete before closing journals.

uvicorn 0.47's `capture_signals` contextmanager would otherwise
install SIGINT/SIGTERM handlers that fight the fleet's own signal
story; we call `server._serve(None)` directly to bypass them. The
`should_exit` mechanism is unchanged.

### Safety properties

- **Loopback-only**: hard-coded `host="127.0.0.1"` in
  `FleetRuntime._launch_dashboard`. No configuration knob exposes
  `0.0.0.0`. The dashboard is for the local operator only.
- **Read-only**: no POST routes, no buttons. v1 is a monitoring page.
  Start/stop controls are explicitly out of scope until the operator
  has confidence in the safety wiring.
- **WAL-safe**: all SQLite reads go through `?mode=ro` URIs. The
  LiveTradingLoop writers + the dashboard readers can never
  contend for the journal.

## CLI

```
python -m bot.runtime --bots config/bots/ --dashboard
python -m bot.runtime --bots config/bots/ --dashboard --dashboard-port 9090
python -m bot.runtime --bots config/bots/ --dashboard --check
```

`--dashboard` enables both the dashboard side-car AND the FleetAllocator
(account_max_mini=5 — the $50K Combine baseline). One flag wires the
two production-quality features the VSL-aligned family needed before
operators flip `enabled: true` on the YAMLs.

`--check --dashboard` logs the would-be URL but does NOT bind a port.
Smoke tests stay portable.

## Cross-plan note: Tracker symbol-suffix awareness

Plan 21 also resolved a latent footgun in `AccountStateTracker`:
`_POINT_VALUE` was keyed on bare roots ("MNQ"), so a tracker fed a
contract-suffixed symbol ("MNQH26") raised KeyError. Plan 21 routes
the lookup through `bot.markets.registry.get_market` which accepts
both forms. Four of the five e2e tests (propbot, gold_bot, es_scalper,
nq_maintenance, lux_bot) now use the contract-suffixed symbols that
match their shipped YAMLs — closing a gap between the test fixtures
and production config.

The fifth, `test_surgebot_e2e`, still uses bare "MNQ" because
`OpeningRangeBreakoutStrategy.ORBProfile.symbol` is typed
`Literal["MNQ", "NQ"]`. Expanding that Literal to accept contract
suffixes is orthogonal to this plan.

## Deferred (not Plan 21)

- **`_check_hard_flat` policy-awareness**: the risk gate's 15:10 CT
  hard-flat denies opens regardless of the active policy. A 24/7 EFA
  bot therefore can't open new positions during 15:10-17:00 CT despite
  EFA permitting it. Documented as a known limitation in
  `09-bot-lineup.md` (NQ Maintenance § "Known limitation"); making the
  check policy-aware is a future plan.
- **Dashboard control surface**: buttons for "flatten all", "pause bot",
  "resume bot", live config reload. Explicitly out of scope until the
  monitoring surface is proven in production.
- **WebSockets / SSE**: not needed. A single-user local dashboard with
  5-second polling is fine.
