# Plan 12 — Multi-Bot Runtime + Per-Bot Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Replace the single-strategy runtime resolver with N-bot orchestration. After this plan: each YAML config under `config/bots/<bot_name>.yml` becomes a separately-lifecycled bot with its own strategy, broker binding, risk profile, and schedule. The LaunchAgent runs a *fleet*, not one bot.

**Architecture:** New `BotSpec` (frozen dataclass) describes one bot. `BotRegistry` loads N specs from `config/bots/`. `FleetRuntime` constructs N `LiveTradingLoop` instances and runs them concurrently via `asyncio.gather`. Per-bot isolation: each bot owns its own Strategy + RiskGate + Tracker + Journal session — failures in one bot don't crash the fleet. Shared resources (broker connection pool, telemetry bus, heartbeat) are dependency-injected.

**Tech Stack:** No new deps. Reuses `bot.runtime.live_loop.LiveTradingLoop`, `bot.runtime.main` (refactored), `bot.config.load_config` (extended).

**Scope notes:**
- v1 supports one ExecutionClient instance shared by all bots in the fleet (single Topstep account, multiple strategies). Future v2 (Plan 21 allocator) handles per-bot account binding.
- One Journal *file* per bot (`state/journal_<bot_name>.db`); WAL-mode SQLite per bot avoids cross-bot lock contention.
- One heartbeat file (`state/heartbeat.txt`) for the fleet; the watchdog cares that the fleet is alive, not which bot.
- Per-bot schedule: each `BotSpec` includes a `schedule` field (always, market_hours, custom_windows) — the bot's LiveTradingLoop checks the schedule before processing each bar.
- The existing single-bot path (legacy `config/profiles/{surge,maintenance}.yml`) keeps working in a back-compat shim until Plan 15 migrates SurgeBot to the new layout.

**Deliverable:**
- `python -m bot.runtime --bots config/bots/` boots N bots and runs them concurrently.
- A failing bot logs its error, marks itself stopped, and does NOT crash the fleet.
- New integration test: 3 synthetic bots × 30 bars each → all three journals show expected fills.
- CI green (existing 552 + ~20 new tests).
- Tag `plan-12-multi-bot-runtime-complete`.

---

## File structure

- Create: `src/bot/runtime/fleet/__init__.py`
- Create: `src/bot/runtime/fleet/spec.py` — `BotSpec` dataclass + `load_bot_specs(dir: Path) -> list[BotSpec]`
- Create: `src/bot/runtime/fleet/registry.py` — `BotRegistry` (resolves strategy + risk policy from spec)
- Create: `src/bot/runtime/fleet/runtime.py` — `FleetRuntime` (concurrent loop orchestrator)
- Create: `src/bot/runtime/fleet/schedule.py` — `Schedule` Protocol + `AlwaysOn`, `MarketHours`, `CustomWindows`
- Modify: `src/bot/runtime/main.py` — new `--bots` flag; back-compat for `--config` single-bot
- Modify: `src/bot/runtime/cli.py` — argparse for `--bots <dir>`
- Modify: `src/bot/runtime/live_loop.py` — add `schedule: Schedule` constructor param; default `AlwaysOn`
- Create: `config/bots/example_orb_nq.yml` — example BotSpec for the current ORB strategy
- Create: `tests/runtime/fleet/test_spec.py`
- Create: `tests/runtime/fleet/test_registry.py`
- Create: `tests/runtime/fleet/test_runtime.py`
- Create: `tests/runtime/fleet/test_schedule.py`
- Create: `tests/runtime/fleet/__init__.py`

---

## Tasks

### T1: `Schedule` Protocol + 3 implementations

`src/bot/runtime/fleet/schedule.py`. Protocol `Schedule.should_trade(now: datetime) -> bool`. Three implementations:
- `AlwaysOn()` — returns True always (for 24/7 maintenance bots).
- `MarketHours(open_ct=time(8,30), close_ct=time(15,10))` — returns True iff `now.astimezone(CT).time()` in [open, close].
- `CustomWindows(windows: list[tuple[time, time]], tz: ZoneInfo)` — returns True iff `now` falls in any window (for Gold Bot's 7 session windows).

Tests:
- AlwaysOn returns True at 3am UTC and 9pm UTC.
- MarketHours returns True at 14:00 CT, False at 16:00 CT, False at 03:00 CT.
- CustomWindows with [(08:30, 11:30), (13:30, 15:00)] returns True at 09:00, False at 12:00, True at 14:30.

Commit: `feat(fleet): Schedule Protocol + AlwaysOn/MarketHours/CustomWindows`.

### T2: `BotSpec` dataclass + YAML loader

`src/bot/runtime/fleet/spec.py`. Frozen dataclass with: `name: str`, `enabled: bool`, `symbol: str`, `strategy_id: str` (e.g., "orb_5m", "voodoo_tiered"), `strategy_params: dict[str, Any]`, `risk_policy: Literal["combine_intraday","efa_standard","efa_consistency"]`, `risk_params: dict[str, Any]`, `schedule_type: Literal["always","market_hours","custom_windows"]`, `schedule_params: dict[str, Any]`, `journal_path: Path`.

Function `load_bot_specs(dir: Path) -> list[BotSpec]` — globs `*.yml` in dir, parses each into a BotSpec, validates (no duplicate names, journal_path is unique). Raises `ConfigError` with the offending file + reason.

Tests:
- Round-trip: write YAML, read back, fields match.
- Two YAML files in the dir → list of two specs.
- Duplicate names across files → ConfigError.
- Missing required field → ConfigError with field name.
- `enabled: false` bots are loaded (registry decides whether to run them).

Commit: `feat(fleet): BotSpec dataclass + load_bot_specs YAML loader`.

### T3: `BotRegistry` — spec → live components

`src/bot/runtime/fleet/registry.py`. Class `BotRegistry` with:
- `register_strategy(id: str, factory: Callable[[dict], Strategy])` — for "orb_5m" the factory is `lambda p: OpeningRangeBreakoutStrategy(**p)`.
- `register_risk_policy(id: str, factory)` — for "combine_intraday" → `CombineIntradayDrawdown`, etc.
- `register_schedule(id: str, factory)` — maps "always"/"market_hours"/"custom_windows" → the Schedule classes from T1.
- `build(spec: BotSpec) -> ResolvedBot` — looks up factories by id, calls them with params, returns `ResolvedBot(name, strategy, risk_gate, schedule, journal_path)`.

Pre-register the existing strategies + policies at module import.

Tests:
- Built-in registration: "orb_5m" + "combine_intraday" + "always" resolve.
- Unknown strategy_id → KeyError with id.
- Custom registration: register a stub strategy, build a spec using it, verify resolution.

Commit: `feat(fleet): BotRegistry — spec resolution with pluggable strategy/policy/schedule factories`.

### T4: `LiveTradingLoop.schedule` integration

`src/bot/runtime/live_loop.py`. Add optional `schedule: Schedule | None = None` constructor param (default `AlwaysOn`). In the bar loop, before processing each bar: `if not self.schedule.should_trade(bar.timestamp): continue`. (Mark-to-market still runs; only new orders skip.)

Tests:
- ORB strategy + MarketHours schedule: 100 synthetic bars spanning 16:00 CT → only bars within hours produce intents.
- AlwaysOn schedule: same behavior as no schedule (regression).
- CustomWindows with one [09:00-10:00] window: only bars in that hour produce intents.

Commit: `feat(runtime): LiveTradingLoop honors per-bot Schedule`.

### T5: `FleetRuntime` — concurrent orchestration

`src/bot/runtime/fleet/runtime.py`. Class `FleetRuntime(bots: list[ResolvedBot], broker: ExecutionClient, bar_source_factory: Callable[[BotSpec], LiveBarSource], telemetry, heartbeat_path)`.

`async run() -> dict[str, BotResult]`:
1. For each ResolvedBot: construct LiveTradingLoop + open Journal at spec's journal_path.
2. `await asyncio.gather(*[loop.run(bar_source_factory(bot.spec)) for bot in bots], return_exceptions=True)`.
3. Collect per-bot result (completed, exception, n_bars_processed). Failures don't propagate.
4. Return `dict[bot.name -> BotResult]`.

Tests:
- 3 synthetic bots × 30 bars each → all 3 journals open + closed cleanly; results dict has 3 entries.
- 1 of 3 bots raises an exception mid-loop → other 2 complete; result dict shows 1 error.
- Empty bot list → returns empty dict, no error.

Commit: `feat(fleet): FleetRuntime concurrent orchestration with per-bot isolation`.

### T6: `main.py` integration + CLI

`src/bot/runtime/main.py` + `src/bot/runtime/cli.py`. Add `--bots <dir>` flag (mutually exclusive with `--config`). When `--bots`:
1. `load_bot_specs(dir)` → list of BotSpec.
2. `[reg.build(s) for s in specs if s.enabled]` → list of ResolvedBot.
3. Construct shared broker via existing hydrate path.
4. Construct FleetRuntime, await `run()`.
5. Print summary table: name | result | n_orders | final_equity.

Keep `--config` path working unchanged.

Tests:
- `python -m bot.runtime --bots config/bots/ --check` boots the registry, validates all specs, prints summary, exits 0.
- `--bots <empty-dir>` exits non-zero with "no enabled bots found".
- Existing `python -m bot.runtime --check` (no `--bots` flag) still works.

Commit: `feat(runtime): --bots flag wires FleetRuntime; back-compat --config preserved`.

### T7: Example config + spec doc update + tag

Write `config/bots/example_orb_nq.yml` (commented, references the current ORB strategy):
```yaml
name: example_orb_nq
enabled: false  # disabled by default; example only
symbol: MNQ
strategy_id: orb_5m
strategy_params:
  range_minutes: 5
  atr_multiplier: 1.0
  reward_ratio: 2.0
  max_trades_per_day: 2
risk_policy: combine_intraday
risk_params:
  start_balance: 50000
  mll_amount: 2000
  max_mini: 5
schedule_type: market_hours
schedule_params:
  open_ct: "08:30"
  close_ct: "15:10"
journal_path: state/journal_example_orb_nq.db
```

Update `docs/superpowers/specs/2026-05-22-futures-bot/00-architecture-overview.md` D17 to reflect the multi-bot runtime (one Strategy class abstraction is now real, since N bots = N strategy instances).

Then:
```
git tag plan-12-multi-bot-runtime-complete
git push origin main --tags
```

Commit: `docs(spec): multi-bot runtime + example config`.

---

## Verification

```bash
cd ~/futures-bot1
source ~/.venvs/topstep-bot/bin/activate
ruff check . && mypy --strict src/ && pytest -x -q
python -m bot.runtime --bots config/bots/ --check
```

Expected:
- CI green: ~572 tests (552 existing + ~20 new).
- `--check` prints "0 enabled bots; example_orb_nq disabled" and exits 0.
- Tag `plan-12-multi-bot-runtime-complete` exists + pushed.

End state: Plans 15-20 (the actual user-facing bots) each become a single YAML file + a strategy class.
