# Plan 11 — TopstepX Sim Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Make every Topstep-specific code path end-to-end testable without touching the real TopstepX API or paying for a Combine. After this plan: the four-rail test ladder (backtest → IB Paper → **TopstepX Sim** → TopstepX Live) is complete, and the user can validate any new bot through Topstep semantics for $0.

**Architecture:** A new `TopstepXSimClient` implements the same `ExecutionClient` Protocol as `TopstepXExecutionClient` but is backed by an in-memory `TopstepSimEngine` that mirrors Topstep's account state machine (Combine intraday-trailing MLL → pass/fail, EFA EoD-trailing MLL + Consistency 50%, Funded scaling tiers, hard-flat 15:10 CT, side-encoding inversion, max-position caps). Same orders, same fills, same rejections — only money and broker are fake.

**Tech Stack:** No new deps. Reuses `bot.execution.ports.ExecutionClient`, `bot.execution.topstepx_constants` (SIDE_BUY=0), `bot.risk.combine_drawdown`, `bot.risk.efa_drawdown`, `bot.types`. Tests use `pytest-asyncio` (already in dev deps).

**Scope notes:**
- The sim engine reuses the *same* `CombineIntradayDrawdown` / `EFAStandardEoDDrawdown` / `EFAConsistencyDrawdown` policies the live `TopstepRiskGate` already uses. That's the parity guarantee: sim and live behave identically on the rule side.
- Fills are deterministic (mid-price at bar timestamp + configurable slippage in ticks). No partial fills in v1.
- Account stage transitions (Combine-active → Combine-passed → EFA-active → EFA-payout → Funded) are scripted by scenario inputs, not by the sim guessing what Topstep would do.
- The sim does NOT model network latency, reconnect, or JWT refresh — those are TopstepX-client concerns, not Topstep-rule concerns.
- The CLI `python -m bot.execution.topstepx_sim --scenario combine_pass` runs an end-to-end synthetic-bar replay against a chosen scenario + the existing ORB strategy + the existing risk gate.

**Deliverable:**
- A `TopstepXSimClient` that the existing `LiveTradingLoop` can hold instead of `TopstepXExecutionClient` with zero other changes.
- 6 named scenarios run as integration tests (Combine pass, Combine fail by MLL, Combine fail by max-position, EFA payout flow, EFA Consistency breach, hard-flat 15:10).
- Parity test: synthetic bars + `TopstepRiskGate` produces identical approve/deny decisions whether downstream is `TopstepXSimClient` or a stub.
- CI green (ruff + mypy + 493 existing tests + ~25 new tests).
- Tag `plan-11-topstepx-sim-complete`.

---

## File structure

- Create: `src/bot/execution/topstepx_sim/__init__.py` — package marker, re-exports
- Create: `src/bot/execution/topstepx_sim/account.py` — `SimAccount` dataclass + transitions
- Create: `src/bot/execution/topstepx_sim/engine.py` — `TopstepSimEngine` (orders → fills → P&L → state)
- Create: `src/bot/execution/topstepx_sim/client.py` — `TopstepXSimClient` (ExecutionClient Protocol impl)
- Create: `src/bot/execution/topstepx_sim/scenarios.py` — named scenario builders
- Create: `src/bot/execution/topstepx_sim/cli.py` — `python -m bot.execution.topstepx_sim`
- Create: `src/bot/execution/topstepx_sim/__main__.py` — CLI entrypoint
- Create: `tests/execution/topstepx_sim/test_account.py`
- Create: `tests/execution/topstepx_sim/test_engine.py`
- Create: `tests/execution/topstepx_sim/test_client.py`
- Create: `tests/execution/topstepx_sim/test_scenarios.py`
- Create: `tests/execution/topstepx_sim/test_parity.py`
- Create: `tests/execution/topstepx_sim/__init__.py`

---

## Tasks

### T1: `SimAccount` state + stage transitions

`src/bot/execution/topstepx_sim/account.py`. Frozen dataclass `SimAccount(balance, equity, high_water_equity, realized_pnl, unrealized_pnl, open_positions, stage: Literal['combine_active','combine_passed','combine_failed','efa_active','efa_payout','funded'], start_balance, mll_amount)`. Plus pure transition functions: `apply_fill(account, fill) -> SimAccount`, `mark_to_market(account, mid_price, symbol) -> SimAccount`, `advance_stage(account, target: Stage) -> SimAccount`.

Tests:
- New account starts in `combine_active` with balance = start_balance.
- `apply_fill` increases unrealized_pnl on open position; on close-fill, realized = (close - open) * tick_value * sign.
- `mark_to_market` updates equity = balance + unrealized.
- `advance_stage` enforces legal transitions (combine_active → combine_passed/failed only; efa_active → efa_payout → funded; no skipping).
- Illegal transition raises `ValueError`.

Commit: `feat(topstepx_sim): SimAccount dataclass + stage transitions`.

### T2: `TopstepSimEngine` — order acceptance + fill simulation

`src/bot/execution/topstepx_sim/engine.py`. Class `TopstepSimEngine(account: SimAccount, *, combine_policy, efa_policy, slippage_ticks=0, hard_flat_time_ct=time(15,10), now: Callable[[], datetime])`.

Public surface:
- `submit_order(intent: OrderIntent, mid_price: float) -> OrderEvent` — checks max-position cap, hard-flat time, MLL phantom-floor liquidation; on accept: fills immediately at mid ± slippage, updates account, emits OrderEvent(status='filled', fill_price=...). On reject: emits OrderEvent(status='rejected', reason=...).
- `cancel_order(client_order_id: str) -> OrderEvent` — sim orders fill instantly so cancel always returns 'too_late'.
- `tick(mid_price: float, symbol: str) -> SimAccount` — mark-to-market; if equity ≤ phantom_mll(account, policy) → close all positions at mid, set stage='combine_failed' or 'efa_active'→'efa_failed'.
- `eod() -> SimAccount` — flat all open positions if past hard_flat_time_ct; update EFA EoD-trailing floor.

Tests:
- Reject when symbol position count exceeds policy.max_position.
- Reject when timestamp > hard_flat_time_ct (NEW orders only; existing positions still flatten on eod).
- Fill at mid + slippage_ticks * tick_size for BUY; mid - slippage_ticks * tick_size for SELL.
- Phantom-MLL liquidation: balance starts 50_000, mll=2_000, after losses equity=47_900 → liquidation triggered, stage='combine_failed'.
- Side encoding: when serializing intent to TopstepX wire format (uses `topstepx_side`), BUY→0, SELL→1 (parity check vs `bot.execution.topstepx_constants.topstepx_side`).

Commit: `feat(topstepx_sim): TopstepSimEngine — order acceptance + fill sim + MLL liquidation`.

### T3: `TopstepXSimClient` — ExecutionClient Protocol impl

`src/bot/execution/topstepx_sim/client.py`. Class `TopstepXSimClient` implements `ExecutionClient`. Constructor takes a `TopstepSimEngine` plus an async-mid-price source (a callable `(symbol) -> Awaitable[float]` so tests can pass a lambda from a synthetic price series).

All Protocol methods are async wrappers around the (sync) engine:
- `connect()`: no-op (returns immediately).
- `disconnect()`: flushes any pending state to in-memory log.
- `place_order(intent)`: looks up mid for `intent.symbol`, calls `engine.submit_order(intent, mid)`, returns OrderEvent.
- `cancel_order(coid)`: calls `engine.cancel_order(coid)`.
- `cancel_all(symbol)`: iterates client log, calls cancel on each.
- `get_positions()`: builds `Position` list from `engine.account.open_positions`.
- `get_open_orders()`: returns empty list (sim fills immediately; no working orders).

Tests:
- `place_order` round-trips OrderEvent.
- `get_positions` reflects post-fill state.
- mypy strict passes; Protocol conformance proven by assigning instance to `ExecutionClient` typed var.

Commit: `feat(topstepx_sim): TopstepXSimClient implementing ExecutionClient Protocol`.

### T4: Scenario builders

`src/bot/execution/topstepx_sim/scenarios.py`. Functions returning fully-configured `(SimAccount, TopstepSimEngine, TopstepXSimClient, list[Bar])` tuples:

- `combine_pass_50k()` — $50K Combine, NQ price series that crosses $3K profit target without breaching MLL → terminates with stage='combine_passed'.
- `combine_fail_mll_50k()` — same setup, price series that drives equity to $48K → stage='combine_failed'.
- `combine_fail_max_position()` — strategy submits oversized order → engine rejects, no fill.
- `efa_payout_flow_50k()` — start in stage='efa_active', $1K profit → eligible for payout, advance stage='efa_payout'.
- `efa_consistency_breach()` — single-day P&L = 60% of total → EFA Consistency policy denies (uses existing `EFAConsistencyDrawdown.CONSISTENCY_THRESHOLD`).
- `hard_flat_at_1510_ct()` — strategy submits order at 15:11 CT → engine rejects with reason='HARD_FLAT_CLOCK'.

Tests: each scenario runs to completion, asserts final stage matches name.

Commit: `feat(topstepx_sim): 6 named scenarios + tests for each`.

### T5: Parity test — sim vs live-stub through `TopstepRiskGate`

`tests/execution/topstepx_sim/test_parity.py`. Same input bars + same OrderIntent stream through `TopstepRiskGate.approve_or_deny` produce identical decisions whether the downstream broker reports its state via `TopstepXSimClient` or via a hand-built stub that mimics what the real `TopstepXExecutionClient` would report. This is the load-bearing test: if it passes, the sim is a credible substitute for live Topstep for risk-gate validation.

Implementation: use the existing `SimExecutionClient` (from Plan 4 / `bot.backtest.sim_client`) as the comparison stub. Both clients receive the same fills; both produce the same `AccountState` updates; the gate's approve/deny decisions must match exactly across 60 synthetic bars + 10 intents.

Commit: `test(topstepx_sim): parity vs SimExecutionClient through TopstepRiskGate`.

### T6: CLI — `python -m bot.execution.topstepx_sim --scenario <name>`

`src/bot/execution/topstepx_sim/cli.py` + `__main__.py`. Argparse: `--scenario` (required, must be a registered name), `--bars` (optional path to a CSV bar file; defaults to scenario's synthetic series), `--json-out` (optional path to write final SimAccount as JSON).

On run: builds scenario, instantiates `LiveTradingLoop` from `bot.runtime.live_loop` with strategy=`OpeningRangeBreakoutStrategy` (from existing `bot.strategy.orb`) + the sim client, runs to completion, prints final stage + balance + equity + total trades + breach reason (if any).

Tests:
- `python -m bot.execution.topstepx_sim --scenario combine_pass_50k` exits 0, stdout contains "stage=combine_passed".
- `--scenario unknown` exits non-zero with usage error.

Commit: `feat(topstepx_sim): CLI runner for named scenarios end-to-end`.

### T7: Documentation update + tag

Update `docs/superpowers/specs/2026-05-22-futures-bot/02-execution-clients.md` to reference the sim adapter as the third test rail. Add a "Test ladder" section to that spec describing the four-rail progression: backtest → IB Paper → TopstepX Sim → TopstepX Live.

Then:
```
git tag plan-11-topstepx-sim-complete
git push origin main --tags
```

Commit: `docs(spec): add TopstepX Sim adapter as third test rail + four-rail ladder`.

---

## Verification

End-to-end:
```bash
cd ~/futures-bot1
source ~/.venvs/topstep-bot/bin/activate
ruff check . && mypy --strict src/ && pytest -x -q
python -m bot.execution.topstepx_sim --scenario combine_pass_50k
python -m bot.execution.topstepx_sim --scenario combine_fail_mll_50k
python -m bot.execution.topstepx_sim --scenario hard_flat_at_1510_ct
```

Expected:
- All 6 scenarios exit 0 and print the expected final stage.
- CI green: 493 + ~25 new tests pass.
- Tag `plan-11-topstepx-sim-complete` exists on `main` and pushed to GitHub.

End state: any new bot (Plans 15-20) can be validated against Topstep semantics without spending a dollar on a Combine.
