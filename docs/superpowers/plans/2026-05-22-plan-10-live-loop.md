# Plan 10 — Live Event Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Close the gap from Plan 9 — wire `IBLiveBarStream` (or any compatible bar source) into the same Strategy → RiskGate → Broker → Journal pipeline that `BacktestEngine` already proves works. After this plan: the LaunchAgent path actually trades end-to-end.

**Architecture:** `LiveTradingLoop` mirrors `BacktestEngine` but uses an async bar source instead of a sync Iterable. Heartbeat file updated every 30s. Force-flatten pending requests are drained at top of each loop iteration. SIGTERM triggers clean shutdown (best-effort flat + journal flush).

**Tech Stack:** No new deps. Reuses Plan 4 (BacktestEngine pattern), Plan 6 (IBLiveBarStream), Plan 7 (Journal + TelemetryBus), Plan 8 (TopstepX broker), Plan 9 (RuntimeState).

**Scope notes:**
- Tests use `SimExecutionClient` + synthetic async bar source (no real broker).
- Heartbeat path comes from `RuntimeState.heartbeat_path` (add to RuntimeState if missing).
- Shutdown grace period: 10 seconds max for in-flight orders to settle.

**Deliverable:**
- `LiveTradingLoop` integration test: 60 synthetic bars + ORB strategy + sim broker → final state has at least one approved order recorded in journal.
- `main.py`'s `_default_event_loop` REPLACED with `LiveTradingLoop.run(runtime)`.
- The smoke test from Plan 9 (`python -m bot.runtime --check`) still passes (early exits before loop).
- A new test invokes the loop directly (without `--check`) against synthetic config + sim broker.
- Tag `plan-10-live-loop-complete`.

---

## Tasks

### T1: `LiveBarSource` Protocol + sim adapter

`src/bot/runtime/bar_source.py`. `LiveBarSource(Protocol).subscribe() -> AsyncIterator[Bar]`. Also adds `SimBarSource(Iterable[Bar])` — wraps a sync iterable as async, used by tests + sim runs.

Tests:
- SimBarSource yields all bars in order.
- Empty source completes cleanly.

Commit: `feat(runtime): LiveBarSource Protocol + SimBarSource adapter`.

### T2: `LiveTradingLoop` core

`src/bot/runtime/live_loop.py`. Class `LiveTradingLoop` constructor accepts: `strategy, gate, tracker, broker, journal, telemetry, heartbeat_path, symbol`.

Method `async run(bar_source: LiveBarSource, *, max_bars: int | None = None)`:
1. Open journal session.
2. Loop over `async for bar in bar_source.subscribe()`:
   - `await gate.force_flatten_now()` — drain any pending request from previous iteration
   - `tracker.mark_to_market(bar)`
   - `state = tracker.snapshot(bar.timestamp)`
   - `state = gate.on_tick(state)`  (state machine update + may schedule flatten)
   - `intents = list(strategy.on_bar(bar, state))`
   - For each: `decision = gate.approve_or_deny(intent, state)`. If approved: `await broker.place_order(decision.intent)` + tracker.record_fill + `await journal.record_*`. If denied: `await journal.record_risk_decision(decision)`.
   - Write heartbeat (if 30s elapsed since last write).
   - Count bars; if max_bars reached, break.
3. Final flush — drain any pending flatten, close journal session.

Tests:
- Run with PlaceholderStrategy + 5 bars + sim broker: no fills, journal session opened + closed cleanly.
- Run with synthetic one-shot strategy emitting BUY on bar 0: journal has 1 approved order recorded.
- Run with gate denying everything (rule HARD_FLAT_CLOCK by setting bar timestamps after 15:10 CT): journal records denials.

Commit: `feat(runtime): LiveTradingLoop core (Bar stream → Strategy → Gate → Broker → Journal)`.

### T3: Heartbeat writer

`src/bot/runtime/heartbeat.py`. `Heartbeat(path: Path)` with `write_now(ts: datetime) -> None` (atomic rename for crash-safety). Integrate into LiveTradingLoop: write once per loop iteration if ≥ 30s since last write.

Tests:
- Heartbeat creates file with current timestamp.
- Atomic rename pattern (write to tmp + rename).
- Loop integration: heartbeat written periodically.

Commit: `feat(runtime): heartbeat writer with atomic rename + 30s cadence in LiveTradingLoop`.

### T4: SIGTERM clean shutdown

`src/bot/runtime/shutdown.py`. `install_shutdown_handler(loop_state)` registers a SIGTERM handler that sets a `_should_stop` event. LiveTradingLoop checks the event each iteration; on stop signal: drain pending intents, force-flatten if any open position, close journal session.

Tests (using `asyncio.Event` directly, not real signals):
- Setting the event mid-loop causes graceful exit.
- After stop: tracker shows positions closed (if SimBroker reports clean fills).
- Journal session is closed.

Commit: `feat(runtime): SIGTERM clean shutdown handler (graceful flat + journal flush)`.

### T5: Wire `LiveTradingLoop` into `main.py`

Replace `_default_event_loop` in `bot/runtime/main.py` with:
```python
async def _default_event_loop(runtime: RuntimeState) -> None:
    from bot.runtime.live_loop import LiveTradingLoop
    from bot.runtime.bar_source import _resolve_bar_source  # cfg → source
    loop = LiveTradingLoop(
        strategy=_resolve_strategy(runtime.cfg),
        gate=_build_gate(runtime),
        tracker=AccountStateTracker(...),
        broker=runtime.broker,
        journal=runtime.journal,
        telemetry=runtime.telemetry,
        heartbeat_path=runtime.cfg.heartbeat_path,
        symbol=runtime.cfg.data.symbol_primary,
    )
    await loop.run(bar_source=_resolve_bar_source(runtime.cfg))
```

For `env=dev` with `broker=sim`, use SimBarSource with a hardcoded empty source (loop exits immediately) — keeps `--check` smoke test passing.

Tests:
- main() with sim broker + empty bar source: exits 0.
- main() invoked without --check (longer-running): runs the loop, then exits. Use small `max_bars` to bound runtime.

Commit: `feat(runtime): replace main._default_event_loop stub with real LiveTradingLoop`.

### T6: Integration smoke + final verify + tag

End-to-end test: spin up a SimBroker + synthetic 60-bar source + ORB strategy + in-memory journal + run via `main()` → assert journal session row exists + tests still pass.

Run full sweep: `ruff check src/ tests/`, `mypy src/`, `pytest -q`. Tag `plan-10-live-loop-complete`.

Commit: `test(runtime): end-to-end smoke (synthetic bar stream → trade → journal)`.

---

## Constraints

- ALL async, no `asyncio.run()` in tests.
- Sim broker is the test broker (no real ib_async or project-x-py network).
- Each task one commit.
- ruff + mypy strict clean after each.
- `from __future__ import annotations`, `from datetime import UTC` everywhere.

## Test counts target

468 + ~25 = ~495.

## Out-of-scope

- ❌ Real IB Gateway connection in CI (manual operator step)
- ❌ Live TopstepX connection in CI
- ❌ Crash-replay (separate plan)
- ❌ Bar-source backfill on reconnect (use last-bar-timestamp filter to avoid duplicates — defer to v2)
