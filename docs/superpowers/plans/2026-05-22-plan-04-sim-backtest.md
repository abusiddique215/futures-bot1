# Plan 4 — Sim Client + Backtest Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** First plan that produces a **runnable backtest**. Ships `SimExecutionClient` (implements ExecutionClient protocol with deterministic fill logic), `BacktestEngine` (wires Bar stream → Strategy → RiskGate → Sim), an `AccountStateTracker` (computes unrealized P&L per tick), a `TradeReport`, and a Topstep rule-replay reporter that re-runs trades through `TopstepRiskGate` and flags any rule violations the original strategy run missed.

**Architecture:** Backtest loop = for each Bar emit to AccountStateTracker → updates AccountState → gate.on_tick(state) → Strategy.on_bar(bar, state) → if strategy emits intent: gate.approve_or_deny → sim.place_order → update tracker. Single canonical Strategy interface = `Protocol` with `on_bar(bar, state) -> Iterable[OrderIntent]`. Walk-forward + parameter sweep + Monte Carlo are deferred to Plan 5 (when there's an actual strategy worth sweeping).

**Tech Stack:** No new deps beyond Plans 1-3. Uses Plan 1 types, Plan 2 data pipeline (`FirstRateDataLoader.load`), Plan 3 risk gate.

**Scope notes:**
- v1: market + bracket orders only. STOP / LIMIT / STOP_LIMIT defer to Plan 5+.
- Sim fills at the NEXT bar's open price (no intra-bar resolution; cleaner backtest signal).
- Bracket stops/take-profits check on every bar's high/low; first-touch wins.
- AccountStateTracker computes unrealized P&L from open positions × (current_bar.close - avg_entry_price) × tick_value / minTick.

**Deliverable:** `python -m bot.backtest --strategy placeholder --symbol MNQ --start 2023-12-01 --end 2023-12-31` runs end-to-end against ingested parquet, emits a summary, runs the rule-replay reporter, exits 0.

---

## File Structure

```
src/bot/backtest/
├── __init__.py
├── sim_client.py            # SimExecutionClient
├── strategy.py              # Strategy Protocol + PlaceholderStrategy
├── tracker.py               # AccountStateTracker (unrealized P&L per bar)
├── engine.py                # BacktestEngine (Bar loop → Strategy → Gate → Sim)
├── report.py                # TradeReport (PnL, drawdown, win rate)
├── rule_replay.py           # RuleReplayReporter
└── cli.py                   # python -m bot.backtest entry point

tests/
├── test_backtest_sim_client.py
├── test_backtest_strategy_protocol.py
├── test_backtest_tracker.py
├── test_backtest_engine_end_to_end.py
├── test_backtest_report.py
├── test_backtest_rule_replay.py
└── test_backtest_cli.py
```

---

## Tasks

### Task 1: `bot/backtest/` skeleton + Strategy Protocol

**Files:**
- Create: `src/bot/backtest/__init__.py` (`""\n`)
- Create: `src/bot/backtest/strategy.py`
- Create: `tests/test_backtest_strategy_protocol.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_backtest_strategy_protocol.py
"""Strategy Protocol contract."""
from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Iterable

from bot.types import AccountState, Bar, OrderIntent


def test_strategy_protocol_importable() -> None:
    from bot.backtest.strategy import Strategy
    assert Strategy is not None


def test_placeholder_strategy_emits_no_intents_by_default() -> None:
    from bot.backtest.strategy import PlaceholderStrategy
    s = PlaceholderStrategy()
    bar = Bar(symbol="MNQ", open=100.0, high=101.0, low=99.5, close=100.5,
              volume=10, timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
              interval="1m")
    state = AccountState(
        equity=50_000, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=bar.timestamp,
    )
    intents = list(s.on_bar(bar, state))
    assert intents == []


def test_placeholder_strategy_satisfies_protocol() -> None:
    """Structural conformance check via mypy + isinstance."""
    from bot.backtest.strategy import PlaceholderStrategy, Strategy
    s: Strategy = PlaceholderStrategy()
    assert s is not None
```

- [ ] **Step 2: Failure check.**

- [ ] **Step 3: Write `src/bot/backtest/strategy.py`**

```python
# src/bot/backtest/strategy.py
"""Strategy Protocol + PlaceholderStrategy (no signals, used for harness tests)."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from bot.types import AccountState, Bar, OrderIntent


@runtime_checkable
class Strategy(Protocol):
    """Backtest + live shared interface. on_bar(bar, state) -> intent stream."""

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]: ...


class PlaceholderStrategy:
    """Emits no intents. Used by harness tests + smoke runs."""

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        return []
```

- [ ] **Step 4: Verify + commit.** 3 tests pass; ruff + mypy clean. Commit: `feat(backtest): Strategy Protocol + PlaceholderStrategy`.

---

### Task 2: `AccountStateTracker`

**Files:**
- Create: `src/bot/backtest/tracker.py`
- Create: `tests/test_backtest_tracker.py`

`AccountStateTracker` maintains the running `AccountState` across bars during a backtest. It tracks:
- open positions (dict[symbol, signed_qty])
- entry prices per position
- realized P&L (closed positions)
- unrealized P&L (from current bar close)
- high_water_equity (via policy.update_on_tick — gate handles this)

The tracker is the source of `state.equity`, `state.unrealized_pnl`, etc. that get fed to the gate's `on_tick`.

- [ ] **Step 1: Failing tests** — verify start state + position-add + position-close + unrealized PnL computation. ~6 tests.

```python
# tests/test_backtest_tracker.py
"""AccountStateTracker (backtest-time AccountState builder)."""
from __future__ import annotations

from datetime import UTC, datetime

from bot.types import Bar


def _bar(close: float, ts: datetime | None = None) -> Bar:
    return Bar(
        symbol="MNQ", open=close, high=close, low=close, close=close,
        volume=100,
        timestamp=ts or datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
        interval="1m",
    )


def test_tracker_initial_state_at_start_balance() -> None:
    from bot.backtest.tracker import AccountStateTracker
    t = AccountStateTracker(start_balance=50_000, is_combine=True)
    state = t.snapshot(timestamp=datetime(2026, 1, 1, tzinfo=UTC))
    assert state.equity == 50_000
    assert state.open_positions == {}
    assert state.high_water_equity == 50_000


def test_tracker_records_filled_order_opens_position() -> None:
    """A filled BUY 2 MNQ at 16500 opens a long position of 2."""
    from bot.backtest.tracker import AccountStateTracker
    t = AccountStateTracker(start_balance=50_000, is_combine=True)
    t.record_fill(symbol="MNQ", signed_qty=2, fill_price=16_500.0,
                  ts=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    state = t.snapshot(timestamp=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    assert state.open_positions == {"MNQ": 2}


def test_tracker_unrealized_pnl_from_current_bar_close() -> None:
    """Long 2 MNQ at 16500; current close 16510 -> 10 pts * 2 contracts * $2 = $40."""
    from bot.backtest.tracker import AccountStateTracker
    t = AccountStateTracker(start_balance=50_000, is_combine=True)
    t.record_fill(symbol="MNQ", signed_qty=2, fill_price=16_500.0,
                  ts=datetime(2026, 1, 1, tzinfo=UTC))
    t.mark_to_market(bar=_bar(close=16_510.0))
    state = t.snapshot(timestamp=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    assert state.unrealized_pnl == 40.0  # 10 pts * 2 * $2/pt
    assert state.equity == 50_040.0


def test_tracker_closing_position_realizes_pnl() -> None:
    from bot.backtest.tracker import AccountStateTracker
    t = AccountStateTracker(start_balance=50_000, is_combine=True)
    t.record_fill(symbol="MNQ", signed_qty=2, fill_price=16_500.0,
                  ts=datetime(2026, 1, 1, 14, 0, tzinfo=UTC))
    t.record_fill(symbol="MNQ", signed_qty=-2, fill_price=16_520.0,
                  ts=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    state = t.snapshot(timestamp=datetime(2026, 1, 1, 14, 30, tzinfo=UTC))
    assert state.open_positions == {}
    assert state.realized_pnl_today == 80.0  # 20 pts * 2 * $2/pt
    assert state.unrealized_pnl == 0.0
```

- [ ] **Step 2-5: Implement, verify, commit.**

```python
# src/bot/backtest/tracker.py
"""AccountStateTracker — running AccountState for backtest."""
from __future__ import annotations

from datetime import datetime
from typing import Final

from bot.constants import MIN_TICK, TICK_VALUES
from bot.types import AccountState, Bar


# Point value: TICK_VALUES per tick × ticks per point. MNQ = 4 ticks/pt × $0.50 = $2/pt.
_POINT_VALUE: Final[dict[str, float]] = {
    sym: TICK_VALUES[sym] / MIN_TICK[sym] for sym in TICK_VALUES
}


class AccountStateTracker:
    def __init__(self, start_balance: float, is_combine: bool) -> None:
        self._start_balance = start_balance
        self._is_combine = is_combine
        self._realized = 0.0
        self._unrealized = 0.0
        self._positions: dict[str, int] = {}  # symbol -> signed qty
        self._avg_entry: dict[str, float] = {}  # symbol -> avg entry
        self._high_water = start_balance
        self._last_bar_close: dict[str, float] = {}

    def record_fill(self, symbol: str, signed_qty: int,
                    fill_price: float, ts: datetime) -> None:
        current = self._positions.get(symbol, 0)
        if current == 0:
            self._positions[symbol] = signed_qty
            self._avg_entry[symbol] = fill_price
            return
        new_qty = current + signed_qty
        if new_qty == 0 or (current * new_qty < 0):
            # Closing or flipping. Realize on the closed portion.
            closed_qty = min(abs(current), abs(signed_qty)) * (1 if current > 0 else -1)
            self._realize_pnl(symbol, closed_qty, fill_price)
            if new_qty == 0:
                del self._positions[symbol]
                del self._avg_entry[symbol]
            else:  # flip
                self._positions[symbol] = new_qty
                self._avg_entry[symbol] = fill_price
        else:
            # Adding to existing position — weighted avg entry
            old_avg = self._avg_entry[symbol]
            self._avg_entry[symbol] = (
                (old_avg * abs(current) + fill_price * abs(signed_qty)) /
                abs(current + signed_qty)
            )
            self._positions[symbol] = new_qty

    def _realize_pnl(self, symbol: str, closed_signed_qty: int, exit_price: float) -> None:
        entry = self._avg_entry[symbol]
        # PnL = (exit - entry) × signed_qty × point_value
        pnl = (exit_price - entry) * closed_signed_qty * _POINT_VALUE[symbol]
        self._realized += pnl

    def mark_to_market(self, bar: Bar) -> None:
        """Update unrealized P&L from the latest bar close for any open position
        in this symbol."""
        self._last_bar_close[bar.symbol] = bar.close
        self._recompute_unrealized()

    def _recompute_unrealized(self) -> None:
        total = 0.0
        for sym, qty in self._positions.items():
            if sym not in self._last_bar_close:
                continue
            mark = self._last_bar_close[sym]
            entry = self._avg_entry[sym]
            total += (mark - entry) * qty * _POINT_VALUE[sym]
        self._unrealized = total
        equity = self._start_balance + self._realized + self._unrealized
        if equity > self._high_water:
            self._high_water = equity

    def snapshot(self, timestamp: datetime) -> AccountState:
        equity = self._start_balance + self._realized + self._unrealized
        return AccountState(
            equity=equity,
            realized_pnl_today=self._realized,
            unrealized_pnl=self._unrealized,
            open_positions=dict(self._positions),
            pending_intent_count=0,
            high_water_equity=self._high_water,
            is_combine=self._is_combine,
            timestamp=timestamp,
            start_balance=self._start_balance,
        )
```

Commit: `feat(backtest): AccountStateTracker (realized + unrealized PnL per bar)`.

---

### Task 3: `SimExecutionClient`

**Files:**
- Create: `src/bot/backtest/sim_client.py`
- Create: `tests/test_backtest_sim_client.py`

Deterministic fill logic: market orders fill at next bar's open (or current bar's close in immediate mode). Bracket orders attach stop/take-profit checked on bar high/low.

For Plan 4, simplest: market order fills IMMEDIATELY at the price passed to `place_order` via `intent.limit_price` or a fill_price param. The BacktestEngine drives the fill price; sim_client doesn't care.

Actually simpler: SimExecutionClient.place_order returns an OrderEvent(PENDING). The engine then calls sim.execute_fill(intent, fill_price) to materialize the fill. Cleaner separation.

- [ ] Tests: place_order returns PENDING, execute_fill returns FILLED + tracks position via callback.
- [ ] Impl: just records in-memory state.
- [ ] Commit: `feat(backtest): SimExecutionClient (deterministic in-memory fills)`.

(Full code follows the Plan 1 ExecutionClient protocol exactly. Each method returns appropriate OrderEvent/Position lists from in-memory state.)

---

### Task 4: `BacktestEngine` (Bar loop)

**Files:**
- Create: `src/bot/backtest/engine.py`
- Create: `tests/test_backtest_engine_end_to_end.py`

The engine ties everything together:

```
for bar in bars:
    tracker.mark_to_market(bar)
    state = tracker.snapshot(timestamp=bar.timestamp)
    state = gate.on_tick(state)
    if intents := strategy.on_bar(bar, state):
        for intent in intents:
            decision = gate.approve_or_deny(intent, state)
            if isinstance(decision, ApprovedOrder):
                fill_price = bar.close  # or next bar open per config
                tracker.record_fill(...)
                sim.execute_fill(intent, fill_price)
```

- [ ] Test: run engine with PlaceholderStrategy + 10 bars → no fills, no errors, final equity == 50_000.
- [ ] Test: run engine with a custom strategy that BUYs once + closes once → tracker shows 1 round-trip + matching realized PnL.
- [ ] Commit: `feat(backtest): BacktestEngine (Bar loop + Strategy + RiskGate + Sim)`.

---

### Task 5: `TradeReport`

**Files:**
- Create: `src/bot/backtest/report.py`
- Create: `tests/test_backtest_report.py`

Summary stats: total trades, total realized PnL, max drawdown, win rate, profit factor.

- [ ] Tests for each metric.
- [ ] Commit: `feat(backtest): TradeReport (PnL, drawdown, win rate, profit factor)`.

---

### Task 6: `RuleReplayReporter`

**Files:**
- Create: `src/bot/backtest/rule_replay.py`
- Create: `tests/test_backtest_rule_replay.py`

Replays trades through TopstepRiskGate and reports any rule violations. Catches strategy-runs-where-gate-was-bypassed bugs.

- [ ] Test: trade sequence that violates rule 4 (max position) → replay detects.
- [ ] Test: clean trade sequence → no violations reported.
- [ ] Commit: `feat(backtest): RuleReplayReporter (replays trades through TopstepRiskGate)`.

---

### Task 7: CLI + final verification + tag

```bash
python -m bot.backtest --strategy placeholder --symbol MNQ --start 2023-12-01 --end 2023-12-31
```

- [ ] CLI argparse + entry point
- [ ] Test: subprocess invocation, exit 0, summary printed
- [ ] Final ruff + mypy + pytest
- [ ] Tag: `plan-04-sim-backtest-complete`

---

## Out-of-scope for Plan 4

- ❌ Walk-forward / parameter sweep / Monte Carlo (Plan 5 once the ORB strategy exists)
- ❌ Nautilus runtime integration (deferred — Plan 4's engine is a simple Python loop; Plan 6 may swap in Nautilus)
- ❌ Realistic slippage model (sim fills at bar close in v1)
- ❌ Partial fills (v1 fills all-or-nothing)

---

## Notes

- Aim for ~150 new tests across Plan 4 → ~340 total project tests.
- The engine MUST call `gate.on_tick(state)` every bar BEFORE any approve_or_deny — Combine MLL state machine depends on it.
- Run rule-replay on EVERY backtest by default. The gate is supposed to prevent rule violations during the live run; if replay finds one, it's a bug.
