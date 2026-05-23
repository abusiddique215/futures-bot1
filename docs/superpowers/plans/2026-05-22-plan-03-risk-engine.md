# Plan 3 — Risk Engine (TopstepRiskGate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Ship the load-bearing safety component — `TopstepRiskGate` with seven rule checks, three `DrawdownPolicy` implementations, the phantom-MLL state machine, the stop-offset safety buffer, and the force-flatten handler. A bug here is real-money loss; every code path is property-tested + scenario-tested.

**Architecture:** Pure function `approve_or_deny(intent, state) → ApprovedOrder | OrderDenied`. State mutation happens via `dataclasses.replace`; the gate itself never mutates. Force-flatten triggers (15:10 CT clock alert + equity-touch on every tick) live in `TopstepRiskGate`, independent of strategy state. `DrawdownPolicy` is a strategy pattern — three concrete classes (Combine intraday / EFA Standard EoD / EFA Consistency).

**Tech Stack:** Adds to Plan 2: `hypothesis` (already in dev deps) for property-based testing, `freezegun` (already in dev deps) for DST timezone testing.

**Spec patches applied here** (per `docs/superpowers/research/2026-05-22-pre-plan1-verification.md`):
- §3.4 "Medium confidence" EFA scaling tiers → upgraded to **VERIFIED 2026-05-22**, 90-day stale-warning removed.
- §3.3 EFA prose: clarify that **both** Combine and EFA monitor real-time on unrealized P&L; difference is when the FLOOR ratchets (intraday vs EoD).
- Session-boundary gate on EFA tier increase (effective NEXT session after Trade Report posts; not intraday).

**Scope notes:**
- Pure-function gate. NO Nautilus runtime integration yet (driver wiring → Plan 4 backtest harness; Nautilus `RiskEngine` host → Plan 6 IB Paper).
- Force-flatten triggers `execution_client.cancel_all() + close_all_positions()`. ExecutionClient is mocked in this plan's tests; real adapters land in Plan 4/6/8.
- Cross-account hedging assertion stays minimal: refuse to start if `config.accounts_managed != 1`. v1 single-account.

**Deliverable verification:**
- `pytest -q` ≥ 111 (Plan 2) + ~70 (Plan 3 risk tests) ≈ 180 passing.
- All 7 rule checks have boundary tests (at-threshold, one-tick-below, one-tick-above).
- Property-based test asserts gate is deterministic + side-effect-free.
- DST test for `2026-03-08` (spring forward) and `2026-11-01` (fall back).
- Phantom-MLL worked example from spec 04 §3.4 reproduces step-by-step.
- `python -c "from bot.risk.gate import TopstepRiskGate, CombineIntradayDrawdown; print('imports OK')"` succeeds.

---

## File Structure

```
src/bot/risk/
├── __init__.py
├── policies.py             # (Plan 1) DrawdownPolicy Protocol
├── combine_drawdown.py     # CombineIntradayDrawdown impl
├── efa_drawdown.py         # EFAStandardEoDDrawdown + EFAConsistencyDrawdown
├── news.py                 # NewsCalendar Protocol + YAMLNewsCalendar
├── cancel_tracker.py       # RollingRatioTracker for rule 7
├── gate.py                 # TopstepRiskGate (the 7 rules)
└── config.py               # RiskConfig (Pydantic; gate construction params)

tests/
├── test_risk_combine_drawdown.py
├── test_risk_combine_worked_example.py     # the §3.4 spec walkthrough
├── test_risk_efa_drawdown.py
├── test_risk_news_calendar.py
├── test_risk_cancel_tracker.py
├── test_risk_gate_init.py
├── test_risk_gate_rule_1_hard_flat.py
├── test_risk_gate_rule_2_dll.py
├── test_risk_gate_rule_3_mll.py            # the load-bearing one
├── test_risk_gate_rule_4_max_position.py
├── test_risk_gate_rule_5_news.py
├── test_risk_gate_rule_6_consistency.py
├── test_risk_gate_rule_7_hft.py
├── test_risk_gate_stop_buffer.py
├── test_risk_gate_on_tick.py
├── test_risk_gate_force_flatten.py
├── test_risk_gate_property_based.py        # hypothesis
├── test_risk_gate_dst.py                   # freezegun
└── test_risk_gate_no_bypass.py             # conformance with ExecutionClient
```

---

## Tasks

### Task 1: `RiskConfig` Pydantic model

**Files:**
- Create: `src/bot/risk/config.py`
- Create: `tests/test_risk_config.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_risk_config.py
"""RiskConfig validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_risk_config_valid() -> None:
    from bot.risk.config import RiskConfig
    c = RiskConfig(
        env="backtest",
        accounts_managed=1,
        consistency_mode="soft",
        hft_cancel_to_fill_threshold=5.0,
        safety_buffer_ticks=5,
        tick_cadence_seconds=1.0,
    )
    assert c.env == "backtest"
    assert c.consistency_mode == "soft"


def test_risk_config_default_safety_buffer_is_5() -> None:
    from bot.risk.config import RiskConfig
    c = RiskConfig(env="backtest", accounts_managed=1)
    assert c.safety_buffer_ticks == 5
    assert c.consistency_mode == "soft"


def test_risk_config_rejects_multi_account() -> None:
    """v1: single-account only. Cross-account hedging is a Topstep ToS violation."""
    from bot.risk.config import RiskConfig
    with pytest.raises(ValidationError):
        RiskConfig(env="backtest", accounts_managed=2)
```

- [ ] **Step 2: Failure check.** ModuleNotFoundError.

- [ ] **Step 3: Write `src/bot/risk/config.py`**

```python
# src/bot/risk/config.py
"""Configuration for TopstepRiskGate. See spec 04 §3.7."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Env = Literal["backtest", "paper", "live"]
ConsistencyMode = Literal["soft", "hard"]


class RiskConfig(BaseModel):
    """Per-spec 04 §3.7."""
    model_config = ConfigDict(validate_default=True)

    env: Env
    accounts_managed: int = Field(default=1, ge=1, le=1)  # v1 single-account
    consistency_mode: ConsistencyMode = "soft"
    hft_cancel_to_fill_threshold: float = Field(default=5.0, gt=0)
    safety_buffer_ticks: int = Field(default=5, ge=0)
    tick_cadence_seconds: float = Field(default=1.0, gt=0)
    news_calendar_path: str | None = None
```

- [ ] **Step 4: Verify.** `pytest tests/test_risk_config.py -v && ruff check src/ tests/ && mypy src/ tests/`. Expect 3 passed, clean.

- [ ] **Step 5: Commit.**

```bash
git add src/bot/risk/config.py tests/test_risk_config.py
git commit -m "feat(risk): RiskConfig (single-account assertion, safety_buffer_ticks)"
```

---

### Task 2: `RollingRatioTracker` (cancel-to-fill, rule 7)

**Files:**
- Create: `src/bot/risk/cancel_tracker.py`
- Create: `tests/test_risk_cancel_tracker.py`

Source: spec 04 §3.2 rule 7.

- [ ] **Step 1: Failing tests**

```python
# tests/test_risk_cancel_tracker.py
"""RollingRatioTracker (60-min rolling cancel/fill ratio). Spec 04 §3.2 rule 7."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def test_empty_tracker_ratio_is_zero() -> None:
    from bot.risk.cancel_tracker import RollingRatioTracker
    t = RollingRatioTracker(window_minutes=60)
    assert t.ratio(now=datetime(2026, 5, 22, 14, 0, tzinfo=UTC)) == 0.0


def test_one_fill_zero_cancels_ratio_is_zero() -> None:
    from bot.risk.cancel_tracker import RollingRatioTracker
    t = RollingRatioTracker(window_minutes=60)
    now = datetime(2026, 5, 22, 14, 0, tzinfo=UTC)
    t.record_fill(now)
    assert t.ratio(now=now) == 0.0


def test_three_cancels_one_fill_ratio_is_three() -> None:
    from bot.risk.cancel_tracker import RollingRatioTracker
    t = RollingRatioTracker(window_minutes=60)
    now = datetime(2026, 5, 22, 14, 0, tzinfo=UTC)
    t.record_cancel(now); t.record_cancel(now); t.record_cancel(now)
    t.record_fill(now)
    assert t.ratio(now=now) == pytest.approx(3.0)


def test_zero_fills_one_cancel_returns_infinity_sentinel() -> None:
    """No fills = degenerate; return a large value so rule 7 will trip."""
    from bot.risk.cancel_tracker import RollingRatioTracker
    t = RollingRatioTracker(window_minutes=60)
    now = datetime(2026, 5, 22, 14, 0, tzinfo=UTC)
    t.record_cancel(now)
    assert t.ratio(now=now) == float("inf")


def test_events_outside_window_drop() -> None:
    """Events older than window_minutes are excluded."""
    from bot.risk.cancel_tracker import RollingRatioTracker
    t = RollingRatioTracker(window_minutes=60)
    now = datetime(2026, 5, 22, 14, 0, tzinfo=UTC)
    old = now - timedelta(minutes=120)
    t.record_cancel(old); t.record_cancel(old)  # outside window
    t.record_fill(now)
    assert t.ratio(now=now) == 0.0
```

- [ ] **Step 2: Failure check.**

- [ ] **Step 3: Write `src/bot/risk/cancel_tracker.py`**

```python
# src/bot/risk/cancel_tracker.py
"""60-minute rolling cancel/fill ratio for rule 7 (HFT defensive cap).

Spec: 04 §3.2 rule 7. We self-impose 5.0/60-min by default since Topstep's
threshold is officially undefined.
"""
from __future__ import annotations

from datetime import datetime, timedelta


class RollingRatioTracker:
    """Stateful rolling tracker; pure functions on append + ratio."""

    def __init__(self, window_minutes: int) -> None:
        self._window = timedelta(minutes=window_minutes)
        self._cancels: list[datetime] = []
        self._fills:   list[datetime] = []

    def record_cancel(self, ts: datetime) -> None:
        self._cancels.append(ts)

    def record_fill(self, ts: datetime) -> None:
        self._fills.append(ts)

    def ratio(self, now: datetime) -> float:
        cutoff = now - self._window
        # Prune old entries (idempotent)
        self._cancels = [t for t in self._cancels if t >= cutoff]
        self._fills   = [t for t in self._fills   if t >= cutoff]
        if not self._fills:
            return float("inf") if self._cancels else 0.0
        return len(self._cancels) / len(self._fills)
```

- [ ] **Step 4: Verify.** Expect 5 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/bot/risk/cancel_tracker.py tests/test_risk_cancel_tracker.py
git commit -m "feat(risk): RollingRatioTracker (cancel/fill window for rule 7)"
```

---

### Task 3: `NewsCalendar` Protocol + `YAMLNewsCalendar`

**Files:**
- Create: `src/bot/risk/news.py`
- Create: `tests/fixtures/news_calendar_sample.yml`
- Create: `tests/test_risk_news_calendar.py`

Source: spec 04 §3.8.

- [ ] **Step 1: Sample fixture**

`tests/fixtures/news_calendar_sample.yml`:

```yaml
events:
  - time: 2026-06-12T08:30:00-05:00
    name: CPI
    impact: high
  - time: 2026-06-18T14:00:00-05:00
    name: FOMC
    impact: high
  - time: 2026-07-04T10:00:00-05:00
    name: Random_low_event
    impact: low
window_minutes_before: 5
window_minutes_after: 15
max_position_during_window: 1
```

- [ ] **Step 2: Failing tests**

```python
# tests/test_risk_news_calendar.py
"""YAMLNewsCalendar tests. Spec 04 §3.8."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_news_calendar_loads_events() -> None:
    from bot.risk.news import YAMLNewsCalendar
    cal = YAMLNewsCalendar(path=_FIXTURES / "news_calendar_sample.yml")
    assert cal.max_position_during_window() == 1


def test_news_calendar_in_window_at_event() -> None:
    from bot.risk.news import YAMLNewsCalendar
    cal = YAMLNewsCalendar(path=_FIXTURES / "news_calendar_sample.yml")
    # CPI is 2026-06-12 08:30 CT = 2026-06-12 13:30 UTC
    cpi_utc = datetime(2026, 6, 12, 13, 30, tzinfo=UTC)
    assert cal.in_window(cpi_utc)
    assert cal.in_window(cpi_utc - timedelta(minutes=3))   # within T-5
    assert cal.in_window(cpi_utc + timedelta(minutes=10))  # within T+15


def test_news_calendar_out_of_window_far_before() -> None:
    from bot.risk.news import YAMLNewsCalendar
    cal = YAMLNewsCalendar(path=_FIXTURES / "news_calendar_sample.yml")
    cpi_utc = datetime(2026, 6, 12, 13, 30, tzinfo=UTC)
    assert not cal.in_window(cpi_utc - timedelta(minutes=10))   # before T-5
    assert not cal.in_window(cpi_utc + timedelta(minutes=20))   # after T+15


def test_news_calendar_low_impact_events_ignored() -> None:
    """Only high-impact events trigger windows."""
    from bot.risk.news import YAMLNewsCalendar
    cal = YAMLNewsCalendar(path=_FIXTURES / "news_calendar_sample.yml")
    low_utc = datetime(2026, 7, 4, 15, 0, tzinfo=UTC)  # 10:00 ET = 15:00 UTC
    assert not cal.in_window(low_utc)
```

- [ ] **Step 3: Failure check.**

- [ ] **Step 4: Write `src/bot/risk/news.py`**

```python
# src/bot/risk/news.py
"""News calendar — high-impact event windows for rule 5.

Spec: 04 §3.8. v1 uses a YAML file maintained manually. v2 candidates
(Trading Economics, FRED ICS) are parked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml


@dataclass(frozen=True)
class NewsEvent:
    time: datetime       # tz-aware
    name: str
    impact: str          # "high" | "medium" | "low"


@runtime_checkable
class NewsCalendar(Protocol):
    def in_window(self, now: datetime) -> bool: ...
    def max_position_during_window(self) -> int: ...


class YAMLNewsCalendar:
    """Loads events from a YAML file. v1 implementation."""

    def __init__(self, path: Path) -> None:
        data = yaml.safe_load(path.read_text())
        self._events: list[NewsEvent] = []
        for raw in data.get("events", []):
            t = raw["time"]
            if isinstance(t, str):
                t = datetime.fromisoformat(t)
            if t.tzinfo is None:
                raise ValueError(f"NewsEvent {raw['name']!r}: time must be tz-aware")
            self._events.append(NewsEvent(time=t, name=raw["name"], impact=raw["impact"]))
        self._before = timedelta(minutes=int(data.get("window_minutes_before", 5)))
        self._after  = timedelta(minutes=int(data.get("window_minutes_after", 15)))
        self._cap    = int(data.get("max_position_during_window", 1))

    def in_window(self, now: datetime) -> bool:
        return any(
            (e.time - self._before) <= now <= (e.time + self._after)
            for e in self._events
            if e.impact == "high"
        )

    def max_position_during_window(self) -> int:
        return self._cap
```

- [ ] **Step 5: Verify.** Expect 4 passed.

- [ ] **Step 6: Commit.**

```bash
git add src/bot/risk/news.py tests/fixtures/news_calendar_sample.yml tests/test_risk_news_calendar.py
git commit -m "feat(risk): NewsCalendar Protocol + YAMLNewsCalendar"
```

---

### Task 4: `CombineIntradayDrawdown` (phantom-MLL state machine)

**Files:**
- Create: `src/bot/risk/combine_drawdown.py`
- Create: `tests/test_risk_combine_drawdown.py`

Source: spec 04 §3.4 (transition diagram) + §4.3 (CombineIntradayDrawdown pseudocode).

- [ ] **Step 1: Failing tests**

```python
# tests/test_risk_combine_drawdown.py
"""CombineIntradayDrawdown — phantom-MLL state machine. Spec 04 §3.4, §4.3."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from bot.types import AccountState


def _state(equity: float, hw: float | None = None, **kw) -> AccountState:
    return AccountState(
        equity=equity,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=hw if hw is not None else equity,
        is_combine=True,
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
        **kw,
    )


def test_phantom_mll_starts_at_start_balance_minus_mll() -> None:
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)
    s = _state(equity=50_000)
    assert p.phantom_mll(s) == pytest.approx(48_000)


def test_high_water_ratchets_on_tick() -> None:
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)
    s1 = _state(equity=51_000, hw=50_000)
    s2 = p.update_on_tick(s1)
    assert s2.high_water_equity == 51_000


def test_high_water_does_not_drop_on_drawdown() -> None:
    """One-way ratchet."""
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)
    s1 = _state(equity=50_500, hw=51_000)
    s2 = p.update_on_tick(s1)
    assert s2.high_water_equity == 51_000  # unchanged
    assert p.phantom_mll(s2) == 49_000     # 51_000 - 2_000


def test_locks_at_start_balance_when_high_water_hits_threshold() -> None:
    """When high_water >= start_balance + MLL, lock at start_balance permanently."""
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)
    s1 = _state(equity=52_000, hw=51_999)
    s2 = p.update_on_tick(s1)
    assert s2.is_locked is True
    assert s2.lock_point == 50_000
    assert p.phantom_mll(s2) == 50_000


def test_locked_phantom_mll_stays_at_lock_point_after_further_climbing() -> None:
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)
    s = _state(equity=55_000, hw=55_000)
    s = replace(s, is_locked=True, lock_point=50_000.0)
    assert p.phantom_mll(s) == 50_000


def test_max_position_mnq_is_max_mini_times_10() -> None:
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)
    s = _state(equity=50_000)
    assert p.max_position("MNQ", s) == 50


def test_max_position_nq_is_max_mini() -> None:
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)
    s = _state(equity=50_000)
    assert p.max_position("NQ", s) == 5


def test_max_position_unknown_symbol_raises() -> None:
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)
    s = _state(equity=50_000)
    with pytest.raises(ValueError, match="Unsupported symbol"):
        p.max_position("ES", s)


def test_update_on_eod_is_noop_for_combine() -> None:
    """Combine ratchets on every tick; EoD is a no-op."""
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)
    s = _state(equity=51_000, hw=51_000)
    assert p.update_on_eod(s) == s
```

- [ ] **Step 2: Failure check.**

- [ ] **Step 3: Write `src/bot/risk/combine_drawdown.py`**

```python
# src/bot/risk/combine_drawdown.py
"""CombineIntradayDrawdown — real-time on unrealized P&L; locks at start_balance.

Spec: 04 §3.4 transition diagram, §4.3 pseudocode.

The phantom MLL ratchets ONE WAY: high_water_equity only increases. When
high_water_equity ≥ start_balance + MLL_AMOUNT, the floor locks PERMANENTLY at
start_balance. After lock, the floor never moves regardless of equity.
"""
from __future__ import annotations

from dataclasses import replace

from bot.types import AccountState


class CombineIntradayDrawdown:
    """$50K/$100K/$150K Combine drawdown policy (real-time on unrealized)."""

    def __init__(self, start_balance: float, mll_amount: float, max_mini: int) -> None:
        self._start_balance = start_balance
        self._mll_amount = mll_amount
        self._max_mini = max_mini

    def update_on_tick(self, state: AccountState) -> AccountState:
        new_hw = max(state.high_water_equity, state.equity)
        new_locked = state.is_locked
        new_lock_point = state.lock_point
        if not new_locked and new_hw >= self._start_balance + self._mll_amount:
            new_locked = True
            new_lock_point = self._start_balance
        return replace(
            state,
            high_water_equity=new_hw,
            is_locked=new_locked,
            lock_point=new_lock_point,
        )

    def update_on_eod(self, state: AccountState) -> AccountState:
        return state  # Combine intraday policy is tick-driven; EoD is no-op

    def phantom_mll(self, state: AccountState) -> float:
        if state.is_locked and state.lock_point is not None:
            return state.lock_point
        return state.high_water_equity - self._mll_amount

    def is_locked(self, state: AccountState) -> bool:
        return state.is_locked

    def max_position(self, symbol: str, state: AccountState) -> int:
        if symbol.startswith("MNQ"):
            return self._max_mini * 10  # 10 micros = 1 mini
        if symbol.startswith("NQ"):
            return self._max_mini
        raise ValueError(f"Unsupported symbol for Topstep: {symbol}")
```

- [ ] **Step 4: Verify.** Expect 9 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/bot/risk/combine_drawdown.py tests/test_risk_combine_drawdown.py
git commit -m "feat(risk): CombineIntradayDrawdown (phantom-MLL state machine)"
```

---

### Task 5: Spec §3.4 worked-example walkthrough

**Files:**
- Create: `tests/test_risk_combine_worked_example.py`

This is a single test that replays the exact §3.4 worked-example table line by line. Catches regressions in the state-machine math that simpler unit tests might miss.

- [ ] **Step 1: Write the test**

```python
# tests/test_risk_combine_worked_example.py
"""Spec 04 §3.4 worked-example walkthrough.

| Event             | Equity | HW    | locked | lock_pt | phantom_mll |
|-------------------|--------|-------|--------|---------|-------------|
| Start             | 50_000 | 50_000| False  | None    | 48_000      |
| Up tick to 51_000 | 51_000 | 51_000| False  | None    | 49_000      |
| Down to 50_500    | 50_500 | 51_000| False  | None    | 49_000      |
| Up tick to 51_999 | 51_999 | 51_999| False  | None    | 49_999      |
| Up tick to 52_000 | 52_000 | 52_000| True   | 50_000  | 50_000      |
| Down to 51_000    | 51_000 | 52_000| True   | 50_000  | 50_000      |
| Down to 49_999    | 49_999 | 52_000| True   | 50_000  | 50_000 (breach)|
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.types import AccountState


def _make_state(equity: float, hw: float) -> AccountState:
    return AccountState(
        equity=equity,
        realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=hw, is_combine=True,
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )


def test_worked_example_walkthrough() -> None:
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)

    rows: list[tuple[float, float, bool, float | None, float]] = [
        # equity, expected_hw, expected_locked, expected_lock_pt, expected_phantom
        (50_000, 50_000, False, None, 48_000),
        (51_000, 51_000, False, None, 49_000),
        (50_500, 51_000, False, None, 49_000),
        (51_999, 51_999, False, None, 49_999),
        (52_000, 52_000, True, 50_000, 50_000),
        (51_000, 52_000, True, 50_000, 50_000),
        (49_999, 52_000, True, 50_000, 50_000),
    ]

    state = _make_state(equity=50_000, hw=50_000)
    for i, (equity, exp_hw, exp_locked, exp_lock_pt, exp_phantom) in enumerate(rows):
        if i > 0:
            state = replace(state, equity=equity)
            state = p.update_on_tick(state)
        assert state.high_water_equity == exp_hw, f"row {i}: hw"
        assert state.is_locked == exp_locked, f"row {i}: locked"
        assert state.lock_point == exp_lock_pt, f"row {i}: lock_pt"
        assert p.phantom_mll(state) == exp_phantom, f"row {i}: phantom"

    # Row 7 is the breach: equity (49_999) < phantom_mll (50_000)
    assert state.equity < p.phantom_mll(state)
```

- [ ] **Step 2: Verify.** Expect 1 passed (catches any state-machine regression).

- [ ] **Step 3: Commit.**

```bash
git add tests/test_risk_combine_worked_example.py
git commit -m "test(risk): spec 04 §3.4 worked-example walkthrough"
```

---

### Task 6: `EFAStandardEoDDrawdown` + `EFAConsistencyDrawdown`

**Files:**
- Create: `src/bot/risk/efa_drawdown.py`
- Create: `tests/test_risk_efa_drawdown.py`

Source: spec 04 §3.3 + §4.4. **Scaling tiers VERIFIED 2026-05-22** per pre-Plan-1 research: 2/3/5 minis at < $1,500 / $1,500-$2,000 / > $2,000 accumulated profit. EFA also monitors real-time unrealized; floor ratchets EoD only.

- [ ] **Step 1: Failing tests**

```python
# tests/test_risk_efa_drawdown.py
"""EFAStandardEoDDrawdown + EFAConsistencyDrawdown. Spec 04 §3.3, §4.4.

Scaling tiers VERIFIED 2026-05-22 (pre-Plan-1 verification).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from bot.types import AccountState


def _state(equity: float, hw: float | None = None) -> AccountState:
    return AccountState(
        equity=equity,
        realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=hw if hw is not None else equity,
        is_combine=False,
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
        start_balance=50_000,
    )


def test_efa_update_on_tick_is_noop() -> None:
    """EFA floor only ratchets at EoD. Tick updates are no-ops."""
    from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
    p = EFAStandardEoDDrawdown(mll_amount=2_000)
    s = _state(equity=51_000, hw=50_000)
    assert p.update_on_tick(s) == s


def test_efa_update_on_eod_ratchets_high_water() -> None:
    from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
    p = EFAStandardEoDDrawdown(mll_amount=2_000)
    s = _state(equity=51_000, hw=50_000)
    s2 = p.update_on_eod(s)
    assert s2.high_water_equity == 51_000


def test_efa_phantom_mll_locks_at_zero_once_peak_reaches_mll() -> None:
    from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
    p = EFAStandardEoDDrawdown(mll_amount=2_000)
    s = _state(equity=50_000, hw=2_500)
    # floor = max(0, hw) - mll = max(0, 2_500) - 2_000 = 500, capped at 0
    assert p.phantom_mll(s) == pytest.approx(0.0)


def test_efa_scaling_tier_below_1500_is_2_mini() -> None:
    from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
    p = EFAStandardEoDDrawdown(mll_amount=2_000)
    s = _state(equity=51_499)  # profit = 1499
    assert p.max_position("NQ",  s) == 2
    assert p.max_position("MNQ", s) == 20  # 10 micros per mini


def test_efa_scaling_tier_at_1500_is_3_mini() -> None:
    from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
    p = EFAStandardEoDDrawdown(mll_amount=2_000)
    s = _state(equity=51_500)  # profit = 1500 → tier 2
    assert p.max_position("NQ",  s) == 3


def test_efa_scaling_tier_at_2000_is_5_mini() -> None:
    from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
    p = EFAStandardEoDDrawdown(mll_amount=2_000)
    s = _state(equity=52_000)  # profit = 2000 → tier 3
    assert p.max_position("NQ", s) == 5


def test_efa_consistency_inherits_drawdown_from_standard() -> None:
    from bot.risk.efa_drawdown import EFAConsistencyDrawdown, EFAStandardEoDDrawdown
    p_std = EFAStandardEoDDrawdown(mll_amount=2_000)
    p_con = EFAConsistencyDrawdown(mll_amount=2_000)
    s = _state(equity=51_000, hw=51_000)
    assert p_std.phantom_mll(s) == p_con.phantom_mll(s)
    assert p_std.max_position("NQ", s) == p_con.max_position("NQ", s)


def test_efa_consistency_check_passes_when_under_40pct() -> None:
    """EFA Consistency 40% rule applies at PAYOUT time, not per-trade.

    The policy exposes a separate `gate_payout(best_day, net_profit)` for the
    payout adapter to call; per-trade approval is the same as EFA Standard.
    """
    from bot.risk.efa_drawdown import EFAConsistencyDrawdown
    p = EFAConsistencyDrawdown(mll_amount=2_000)
    # best_day = 300, net_profit = 1_000 → 30% → passes
    assert p.gate_payout(best_day=300, net_profit=1_000) is True


def test_efa_consistency_check_fails_when_over_40pct() -> None:
    from bot.risk.efa_drawdown import EFAConsistencyDrawdown
    p = EFAConsistencyDrawdown(mll_amount=2_000)
    # best_day = 500, net_profit = 1_000 → 50% → fails
    assert p.gate_payout(best_day=500, net_profit=1_000) is False
```

- [ ] **Step 2: Failure check.**

- [ ] **Step 3: Write `src/bot/risk/efa_drawdown.py`**

```python
# src/bot/risk/efa_drawdown.py
"""EFA drawdown policies. Spec 04 §3.3 + §4.4.

Both EFA Standard and EFA Consistency:
- Floor ratchets EoD only (NOT intraday).
- BUT: equity-touch check (`state.equity ≤ phantom_mll(state)`) still runs
  every tick in TopstepRiskGate.on_tick. The DIFFERENCE between Combine and
  EFA is when the floor itself moves (every tick vs once per day), not what
  triggers liquidation (always real-time unrealized).

Scaling tiers verified 2026-05-22 per pre-Plan-1 research:
  profit < $1,500       → 2 mini-equiv
  $1,500 ≤ profit < $2,000 → 3 mini-equiv
  profit ≥ $2,000       → 5 mini-equiv

TopstepX-quirk: 10 micros = 1 mini for scaling purposes. We use that.
Tier upgrade takes effect NEXT session after Trade Report posts — not enforced
in the policy itself (the policy just reports the cap given current state);
the driver is responsible for snapshotting AccountState at session boundary.
"""
from __future__ import annotations

from bot.types import AccountState


class EFAStandardEoDDrawdown:
    """EFA Standard: EoD-trailing floor; profit-gated scaling plan."""

    def __init__(self, mll_amount: float) -> None:
        self._mll_amount = mll_amount

    def update_on_tick(self, state: AccountState) -> AccountState:
        return state  # EFA floor ratchets EoD only

    def update_on_eod(self, state: AccountState) -> AccountState:
        from dataclasses import replace
        new_hw = max(state.high_water_equity, state.equity)
        return replace(state, high_water_equity=new_hw)

    def phantom_mll(self, state: AccountState) -> float:
        # EFA: floor = max(0, peak_eod) - mll, capped at 0.
        floor = max(0.0, state.high_water_equity) - self._mll_amount
        return min(floor, 0.0)

    def is_locked(self, state: AccountState) -> bool:
        return state.high_water_equity >= self._mll_amount

    def max_position(self, symbol: str, state: AccountState) -> int:
        # Profit-gated tiers (VERIFIED 2026-05-22). Keyed off accumulated profit.
        profit = state.equity - state.start_balance
        if profit < 1500:
            cap_mini = 2
        elif profit < 2000:
            cap_mini = 3
        else:
            cap_mini = 5
        if symbol.startswith("MNQ"):
            return cap_mini * 10
        if symbol.startswith("NQ"):
            return cap_mini
        raise ValueError(f"Unsupported symbol for Topstep: {symbol}")


class EFAConsistencyDrawdown(EFAStandardEoDDrawdown):
    """EFA Consistency: same per-trade rules + payout-window 40% cap."""

    CONSISTENCY_THRESHOLD: float = 0.40

    def gate_payout(self, best_day: float, net_profit: float) -> bool:
        """True iff payout request is allowed (best_day / net_profit ≤ 40%).

        Called at request_payout() time, NOT per-trade.
        """
        if net_profit <= 0:
            return False
        return (best_day / net_profit) <= self.CONSISTENCY_THRESHOLD
```

- [ ] **Step 4: Verify.** Expect 9 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/bot/risk/efa_drawdown.py tests/test_risk_efa_drawdown.py
git commit -m "feat(risk): EFAStandardEoDDrawdown + EFAConsistencyDrawdown (verified 2/3/5 scaling tiers)"
```

---

### Task 7: `TopstepRiskGate.__init__` + dependency assertions

**Files:**
- Create: `src/bot/risk/gate.py`
- Create: `tests/test_risk_gate_init.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_risk_gate_init.py
"""TopstepRiskGate init + cross-account assertion."""
from __future__ import annotations

import pytest


class _MockClient:
    async def cancel_all(self, symbol: str) -> list: return []
    async def close_all_positions(self) -> None: return None
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def place_order(self, intent): ...
    async def cancel_order(self, coid): ...
    async def get_positions(self): return []
    async def get_open_orders(self): return []
    async def get_account(self): ...


class _MockTelemetry:
    def alert(self, kind: str, **kw) -> None: pass


class _MockNewsCal:
    def in_window(self, now) -> bool: return False
    def max_position_during_window(self) -> int: return 1


def test_gate_constructs_with_combine_policy() -> None:
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    from bot.risk.config import RiskConfig
    from bot.risk.gate import TopstepRiskGate
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    gate = TopstepRiskGate(
        policy=policy, news_calendar=_MockNewsCal(),
        execution_client=_MockClient(),
        telemetry=_MockTelemetry(),
        config=cfg,
    )
    assert gate is not None


def test_gate_rejects_multi_account_via_config() -> None:
    """Single-account assertion enforced via RiskConfig validation."""
    from bot.risk.config import RiskConfig
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RiskConfig(env="backtest", accounts_managed=3)


def test_gate_tick_cadence_assertion_paper_live_only() -> None:
    """Backtest exempt from tick-cadence assertion; paper/live enforce it."""
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    from bot.risk.config import RiskConfig
    from bot.risk.gate import TopstepRiskGate

    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    # backtest: high cadence is FINE
    cfg_bt = RiskConfig(env="backtest", accounts_managed=1, tick_cadence_seconds=60.0)
    TopstepRiskGate(policy=policy, news_calendar=_MockNewsCal(),
                    execution_client=_MockClient(), telemetry=_MockTelemetry(),
                    config=cfg_bt)  # no exception

    # paper: cadence > 1.0s SHOULD fail
    cfg_paper = RiskConfig(env="paper", accounts_managed=1, tick_cadence_seconds=2.0)
    with pytest.raises(AssertionError, match="tick cadence"):
        TopstepRiskGate(policy=policy, news_calendar=_MockNewsCal(),
                        execution_client=_MockClient(), telemetry=_MockTelemetry(),
                        config=cfg_paper)
```

- [ ] **Step 2: Failure check.**

- [ ] **Step 3: Write initial `src/bot/risk/gate.py`**

```python
# src/bot/risk/gate.py
"""TopstepRiskGate — the single, mandatory choke point between Strategy
decisions and broker order placement.

Spec: 04. A bug here is real-money loss; every rule has property + scenario +
boundary tests.

Tasks 8-15 add the seven rule checks + stop-offset buffer.
Tasks 16-17 add on_tick + force_flatten.
"""
from __future__ import annotations

from bot.execution.ports import ExecutionClient
from bot.risk.cancel_tracker import RollingRatioTracker
from bot.risk.config import RiskConfig
from bot.risk.news import NewsCalendar
from bot.risk.policies import DrawdownPolicy


class _Telemetry:
    """Minimal Protocol for telemetry; satisfied by Plan 7's full impl."""
    def alert(self, kind: str, **kw: object) -> None: ...  # noqa: D401


class TopstepRiskGate:
    """Pre-trade rule check + tick-driven state updates + force-flatten triggers."""

    def __init__(
        self,
        *,
        policy: DrawdownPolicy,
        news_calendar: NewsCalendar,
        execution_client: ExecutionClient,
        telemetry: _Telemetry,
        config: RiskConfig,
    ) -> None:
        assert config.accounts_managed == 1, (
            "Multi-account orchestration is out of scope for v1. "
            "Cross-account hedging is a Topstep ToS violation."
        )
        if config.env in ("paper", "live"):
            assert config.tick_cadence_seconds <= 1.0, (
                "Combine MLL is monitored on unrealized P&L in real time; "
                "the gate must receive tick updates at least once per second "
                "in paper/live mode. Backtest mode is exempt."
            )
        self.policy = policy
        self.news_calendar = news_calendar
        self.execution_client = execution_client
        self.telemetry = telemetry
        self.config = config
        self.cancel_to_fill_tracker = RollingRatioTracker(window_minutes=60)
        self._flattening = False
```

- [ ] **Step 4: Verify.** Expect 3 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/bot/risk/gate.py tests/test_risk_gate_init.py
git commit -m "feat(risk): TopstepRiskGate.__init__ + cross-account + tick-cadence assertions"
```

---

### Task 8: Rule 1 — Hard-flat clock check (15:00 / 15:10 CT)

**Files:**
- Modify: `src/bot/risk/gate.py` (add `_check_hard_flat` + initial `approve_or_deny`)
- Create: `tests/test_risk_gate_rule_1_hard_flat.py`

Source: spec 04 §3.2 rule 1.

- [ ] **Step 1: Failing tests**

```python
# tests/test_risk_gate_rule_1_hard_flat.py
"""Rule 1: hard-flat clock check. Spec 04 §3.2."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.types import AccountState, OrderIntent


CT = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")


class _MockClient:
    async def cancel_all(self, symbol): return []
    async def close_all_positions(self): return None
    async def connect(self): pass
    async def disconnect(self): pass
    async def place_order(self, intent): pass
    async def cancel_order(self, coid): pass
    async def get_positions(self): return []
    async def get_open_orders(self): return []
    async def get_account(self): pass


class _MockTel:
    def alert(self, kind, **kw): pass


class _NoNews:
    def in_window(self, now): return False
    def max_position_during_window(self): return 1


def _make_gate() -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=_MockClient(),
        telemetry=_MockTel(),
        config=RiskConfig(env="backtest", accounts_managed=1),
    )


def _at_ct(hh: int, mm: int) -> datetime:
    return datetime(2026, 5, 22, hh, mm, tzinfo=CT).astimezone(UTC)


def _intent(side: str = "BUY", qty: int = 1) -> OrderIntent:
    return OrderIntent(symbol="MNQ", side=side, quantity=qty,
                       order_type="MARKET", client_order_id="t-1",
                       timestamp=_at_ct(15, 5))


def _state(ts_ct_hh: int, ts_ct_mm: int, positions: dict[str, int] | None = None) -> AccountState:
    return AccountState(
        equity=50_000, realized_pnl_today=0, unrealized_pnl=0,
        open_positions=positions or {}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=_at_ct(ts_ct_hh, ts_ct_mm),
    )


def test_open_at_15_11_ct_denied_HARD_FLAT_CLOCK() -> None:
    gate = _make_gate()
    result = gate.approve_or_deny(_intent(), _state(15, 11))
    from bot.types import OrderDenied
    assert isinstance(result, OrderDenied)
    assert result.rule == "HARD_FLAT_CLOCK"


def test_open_at_15_05_ct_denied_HARD_FLAT_PREEMPT() -> None:
    gate = _make_gate()
    result = gate.approve_or_deny(_intent(), _state(15, 5))
    from bot.types import OrderDenied
    assert isinstance(result, OrderDenied)
    assert result.rule == "HARD_FLAT_PREEMPT"


def test_open_at_14_59_ct_allowed() -> None:
    gate = _make_gate()
    result = gate.approve_or_deny(_intent(), _state(14, 59))
    from bot.types import OrderDenied
    # NOT denied by rule 1 (may be denied by rule 2 due to no stop — accept that
    # for now; rule 2 is task 9).
    if isinstance(result, OrderDenied):
        assert result.rule != "HARD_FLAT_CLOCK"
        assert result.rule != "HARD_FLAT_PREEMPT"


def test_close_at_15_11_ct_allowed() -> None:
    """A REDUCING order (closes existing long) is allowed even at 15:11."""
    gate = _make_gate()
    # Long 2 MNQ; SELL 1 MNQ → reducing
    state = _state(15, 11, positions={"MNQ": 2})
    intent_close = OrderIntent(
        symbol="MNQ", side="SELL", quantity=1,
        order_type="MARKET", client_order_id="close-1",
        timestamp=_at_ct(15, 11),
    )
    result = gate.approve_or_deny(intent_close, state)
    from bot.types import OrderDenied
    # Rule 1 doesn't deny closes. Rule 2 might (no bracket stop on a market close
    # — but spec says reducers don't need stops). For now: assert rule 1 didn't fire.
    if isinstance(result, OrderDenied):
        assert result.rule not in ("HARD_FLAT_CLOCK", "HARD_FLAT_PREEMPT")
```

- [ ] **Step 2: Failure check.** `AttributeError` on `approve_or_deny`.

- [ ] **Step 3: Add `approve_or_deny` skeleton + `_check_hard_flat` to gate**

Append inside `TopstepRiskGate`:

```python

    def approve_or_deny(self, intent, state):  # type: ignore[no-untyped-def]
        """Pre-trade gate. Spec 04 §3.2."""
        from bot.types import ApprovedOrder, OrderDenied  # noqa: F401

        decision = self._check_hard_flat(intent, state)
        if decision is not None:
            return decision

        # Rules 2-7 land in subsequent tasks. For now, after rule 1 passes,
        # approve unconditionally.
        from bot.types import ApprovedOrder
        return ApprovedOrder(
            intent=intent, state_snapshot=state, timestamp=state.timestamp,
        )

    def _check_hard_flat(self, intent, state):  # type: ignore[no-untyped-def]
        """Rule 1: hard-flat clock check. Spec 04 §3.2."""
        from datetime import time
        from zoneinfo import ZoneInfo
        from bot.types import OrderDenied

        now_ct = state.timestamp.astimezone(ZoneInfo("America/Chicago"))
        now_t = now_ct.time()

        is_open = intent.is_open_increasing_exposure(state.open_positions)
        if now_t >= time(15, 10):
            if is_open:
                return OrderDenied(
                    intent=intent, reason="hard-flat 15:10 CT passed",
                    rule="HARD_FLAT_CLOCK",
                    state_snapshot=state, timestamp=state.timestamp,
                )
        elif now_t >= time(15, 0):
            if is_open:
                return OrderDenied(
                    intent=intent, reason="approaching hard-flat 15:10 CT",
                    rule="HARD_FLAT_PREEMPT",
                    state_snapshot=state, timestamp=state.timestamp,
                )
        return None
```

- [ ] **Step 4: Verify.** Expect 4 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/bot/risk/gate.py tests/test_risk_gate_rule_1_hard_flat.py
git commit -m "feat(risk): TopstepRiskGate rule 1 (hard-flat 15:10 CT + 15:00 preempt)"
```

---

### Task 9: Rules 2-3 (DLL + STOP_REQUIRED + MLL phantom) — the load-bearing rules

**Files:**
- Modify: `src/bot/risk/gate.py` (add `_check_dll`, `_check_mll`, types + helpers)
- Create: `tests/test_risk_gate_rule_2_dll.py`
- Create: `tests/test_risk_gate_rule_3_mll.py`

Source: spec 04 §3.2 rules 2 + 3. These two rules are the MOST critical — they prevent account blowup.

- [ ] **Step 1: Tests for rule 2 (DLL + stop required)**

```python
# tests/test_risk_gate_rule_2_dll.py
"""Rule 2: DLL + stop-required sub-check."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.types import AccountState, Bracket, OrderDenied, OrderIntent


class _MC:
    async def cancel_all(self, s): return []
    async def close_all_positions(self): pass
    async def connect(self): pass
    async def disconnect(self): pass
    async def place_order(self, i): pass
    async def cancel_order(self, c): pass
    async def get_positions(self): return []
    async def get_open_orders(self): return []
    async def get_account(self): pass


class _Tel:
    def alert(self, k, **kw): pass


class _NoNews:
    def in_window(self, n): return False
    def max_position_during_window(self): return 1


def _gate() -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=_MC(),
        telemetry=_Tel(),
        config=RiskConfig(env="backtest", accounts_managed=1),
    )


def _ts() -> datetime:
    return datetime(2026, 5, 22, 14, 0, tzinfo=UTC)


def _state(realized: float = 0) -> AccountState:
    return AccountState(
        equity=50_000, realized_pnl_today=realized, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=_ts(),
    )


def _intent_with_bracket(stop_ticks: int = 10, qty: int = 1) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=qty,
        order_type="BRACKET", client_order_id="t-1", timestamp=_ts(),
        bracket=Bracket(stop_loss_ticks=stop_ticks, take_profit_ticks=20),
    )


def test_open_without_bracket_denied_STOP_REQUIRED() -> None:
    intent = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="MARKET", client_order_id="t-1", timestamp=_ts(),
    )
    result = _gate().approve_or_deny(intent, _state())
    assert isinstance(result, OrderDenied)
    assert result.rule == "STOP_REQUIRED"


def test_dll_breach_denied() -> None:
    """realized=-900 + worst-case-loss (10 ticks × $0.50/tick × 1 MNQ = $5)
    is -905. NOT a breach. Use larger numbers: realized = -995, stop 10 ticks
    → -995 - 5 = -1000 → equality breach."""
    intent = _intent_with_bracket(stop_ticks=10, qty=1)
    state = _state(realized=-995)
    result = _gate().approve_or_deny(intent, state)
    assert isinstance(result, OrderDenied)
    assert result.rule == "DLL"


def test_dll_just_under_limit_allowed() -> None:
    """realized=-994, stop 10 ticks → -994 - 5 = -999 → just OK."""
    intent = _intent_with_bracket(stop_ticks=10, qty=1)
    state = _state(realized=-994)
    result = _gate().approve_or_deny(intent, state)
    # Should NOT be denied by rule 2; rules 3+ might still fire — assert rule != DLL
    if isinstance(result, OrderDenied):
        assert result.rule != "DLL"
```

- [ ] **Step 2: Tests for rule 3 (MLL phantom)**

```python
# tests/test_risk_gate_rule_3_mll.py
"""Rule 3: MLL phantom check (the load-bearing one)."""
from __future__ import annotations

from datetime import UTC, datetime

from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.types import AccountState, Bracket, OrderDenied, OrderIntent


class _MC:
    async def cancel_all(self, s): return []
    async def close_all_positions(self): pass
    async def connect(self): pass
    async def disconnect(self): pass
    async def place_order(self, i): pass
    async def cancel_order(self, c): pass
    async def get_positions(self): return []
    async def get_open_orders(self): return []
    async def get_account(self): pass


class _Tel:
    def alert(self, k, **kw): pass


class _NoNews:
    def in_window(self, n): return False
    def max_position_during_window(self): return 1


def _gate() -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=_MC(),
        telemetry=_Tel(),
        config=RiskConfig(env="backtest", accounts_managed=1),
    )


def _state(equity: float, hw: float | None = None) -> AccountState:
    return AccountState(
        equity=equity, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=hw if hw is not None else equity,
        is_combine=True,
        timestamp=datetime(2026, 5, 22, 14, 0, tzinfo=UTC),
    )


def _intent(stop_ticks: int = 10, qty: int = 1) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=qty,
        order_type="BRACKET", client_order_id="t-1",
        timestamp=datetime(2026, 5, 22, 14, 0, tzinfo=UTC),
        bracket=Bracket(stop_loss_ticks=stop_ticks, take_profit_ticks=20),
    )


def test_mll_breach_when_worst_case_loss_below_phantom() -> None:
    """equity=48_005, phantom=48_000 (initial). Worst-case loss 10 ticks × 0.50
    × 1 MNQ = $5 → projected 48_000. Strict less-than → denied."""
    result = _gate().approve_or_deny(_intent(stop_ticks=10, qty=1), _state(equity=48_005))
    assert isinstance(result, OrderDenied)
    assert result.rule == "MLL"


def test_mll_no_breach_when_far_from_phantom() -> None:
    """equity=51_000, phantom=49_000 (hw=51_000). Worst-case loss $5 →
    projected 50_995 > phantom 49_000 → allowed (rule 3 doesn't fire)."""
    result = _gate().approve_or_deny(_intent(), _state(equity=51_000, hw=51_000))
    if isinstance(result, OrderDenied):
        assert result.rule != "MLL"
```

- [ ] **Step 3: Verify failure** — `rule="STOP_REQUIRED"` / `"DLL"` / `"MLL"` strings not yet returned.

- [ ] **Step 4: Add `_check_dll` + `_check_mll` to gate**

Insert into `TopstepRiskGate.approve_or_deny` between hard-flat and the unconditional approve:

```python
        decision = self._check_dll(intent, state)
        if decision is not None:
            return decision

        decision = self._check_mll(intent, state)
        if decision is not None:
            return decision
```

Append the methods:

```python

    _TICK_VALUES = {"MNQ": 0.50, "NQ": 5.00}
    _DLL_AMOUNT = 1_000.0

    def _worst_case_loss(self, intent) -> float:  # type: ignore[no-untyped-def]
        """stop_distance_ticks * tick_value * qty."""
        if intent.bracket is None:
            return 0.0
        return (intent.bracket.stop_loss_ticks
                * self._TICK_VALUES[intent.symbol]
                * abs(intent.quantity))

    def _check_dll(self, intent, state):  # type: ignore[no-untyped-def]
        """Rule 2: Daily Loss Limit + stop-required sub-check."""
        from bot.types import OrderDenied

        # Sub-check 2a: open-exposure orders REQUIRE a bracket stop
        if intent.is_market_or_limit_open() and (
            intent.bracket is None or intent.bracket.stop_loss_ticks is None
        ):
            # Closes (reducing orders) don't need stops
            if intent.is_open_increasing_exposure(state.open_positions):
                return OrderDenied(
                    intent=intent, reason="open-exposure order missing bracket stop",
                    rule="STOP_REQUIRED",
                    state_snapshot=state, timestamp=state.timestamp,
                )

        worst = self._worst_case_loss(intent)
        projected_realized = state.realized_pnl_today - worst
        if projected_realized <= -self._DLL_AMOUNT:
            return OrderDenied(
                intent=intent, reason="DLL would be breached",
                rule="DLL",
                state_snapshot=state, timestamp=state.timestamp,
            )
        return None

    def _check_mll(self, intent, state):  # type: ignore[no-untyped-def]
        """Rule 3: MLL phantom check."""
        from bot.types import OrderDenied
        phantom = self.policy.phantom_mll(state)
        projected_floor = state.equity - self._worst_case_loss(intent)
        if projected_floor < phantom:
            return OrderDenied(
                intent=intent, reason="MLL phantom would be breached",
                rule="MLL",
                state_snapshot=state, timestamp=state.timestamp,
            )
        return None
```

- [ ] **Step 5: Verify.** Expect rule 2 tests (3 passed) + rule 3 tests (2 passed).

- [ ] **Step 6: Commit.**

```bash
git add src/bot/risk/gate.py tests/test_risk_gate_rule_2_dll.py tests/test_risk_gate_rule_3_mll.py
git commit -m "feat(risk): TopstepRiskGate rules 2-3 (STOP_REQUIRED + DLL + MLL phantom)"
```

---

### Tasks 10-15: Rules 4-7 + safety buffer

For each remaining rule, follow the same TDD pattern: write 2-3 boundary tests, add the `_check_<rule>` method to `TopstepRiskGate.approve_or_deny`, verify, commit. Skim spec 04 §3.2 rules 4-7 + §3.6.

- **T10: Rule 4 (max position) + Rule 5 (news throttle)** — combined task. Both look at `state.open_positions` + `intent.signed_qty()`.
- **T11: Rule 6 (consistency, soft-warn default) + Rule 7 (HFT cancel/fill)** — combined task. Rule 6 needs `journal.best_day_pnl_so_far()` + `net_pnl_so_far()` — for v1, accept these as injected callables (driver supplies them in Plan 4+).
- **T12: §3.6 stop-offset safety buffer** — augments approved intent's `with_stop()` call; min(strategy's stop, phantom_mll_distance_in_ticks - safety_buffer).

Each task: ~2-4 tests + ~30 lines of impl + commit. See spec for the exact rule math.

---

### Task 13: `on_tick` (state-machine update + equity-touch trigger)

**Files:**
- Modify: `src/bot/risk/gate.py`
- Create: `tests/test_risk_gate_on_tick.py`

Source: spec 04 §3.5 (equity-touch trigger) + §3.4 (state machine).

- [ ] **Step 1: Tests**

```python
# tests/test_risk_gate_on_tick.py
"""TopstepRiskGate.on_tick — state update + equity-touch trigger."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest


class _TrackingClient:
    """Mock that records calls to cancel_all + close_all_positions."""
    def __init__(self) -> None:
        self.cancel_all_calls = 0
        self.close_all_calls = 0
    async def cancel_all(self, symbol): self.cancel_all_calls += 1; return []
    async def close_all_positions(self): self.close_all_calls += 1
    async def connect(self): pass
    async def disconnect(self): pass
    async def place_order(self, intent): pass
    async def cancel_order(self, coid): pass
    async def get_positions(self): return []
    async def get_open_orders(self): return []
    async def get_account(self): pass


class _Tel:
    def __init__(self): self.alerts = []
    def alert(self, kind, **kw): self.alerts.append((kind, kw))


class _NoNews:
    def in_window(self, n): return False
    def max_position_during_window(self): return 1


def test_on_tick_returns_updated_state_with_high_water_ratcheted() -> None:
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    from bot.risk.config import RiskConfig
    from bot.risk.gate import TopstepRiskGate
    from bot.types import AccountState

    gate = TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=_TrackingClient(),
        telemetry=_Tel(),
        config=RiskConfig(env="backtest", accounts_managed=1),
    )
    s = AccountState(
        equity=51_000, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=datetime(2026, 5, 22, 14, 0, tzinfo=UTC),
    )
    s2 = gate.on_tick(s)
    assert s2.high_water_equity == 51_000


def test_on_tick_below_phantom_mll_triggers_force_flatten() -> None:
    """equity (47_500) < phantom_mll (48_000) → force_flatten."""
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    from bot.risk.config import RiskConfig
    from bot.risk.gate import TopstepRiskGate
    from bot.types import AccountState

    client = _TrackingClient()
    gate = TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=client,
        telemetry=_Tel(),
        config=RiskConfig(env="backtest", accounts_managed=1),
    )
    s = AccountState(
        equity=47_500, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={"MNQ": 1}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=datetime(2026, 5, 22, 14, 0, tzinfo=UTC),
    )
    gate.on_tick(s)
    # force_flatten is async — we need to drain the coro for this sync test.
    import asyncio
    asyncio.run(gate._drain_flatten())  # see impl in Task 14
    assert client.cancel_all_calls >= 1
    assert client.close_all_calls >= 1
```

- [ ] **Step 2: Failure check.**

- [ ] **Step 3: Add `on_tick` + `force_flatten` skeleton to gate.** Force-flatten goes into a queue; a `_drain_flatten` helper runs it. (Plan 4 will wire this to Nautilus's event loop properly; for now, the queue + drain is enough to test.)

Append to `TopstepRiskGate`:

```python

    def on_tick(self, state):  # type: ignore[no-untyped-def]
        new_state = self.policy.update_on_tick(state)
        phantom = self.policy.phantom_mll(new_state)
        if new_state.equity <= phantom:
            self._schedule_force_flatten("MLL_EQUITY_TOUCH")
        return new_state

    def _schedule_force_flatten(self, reason: str) -> None:
        if self._flattening:
            return
        self._flattening = True
        self._pending_flatten_reason = reason

    async def _drain_flatten(self) -> None:
        """Drain any pending force-flatten. Called by the driver's event loop."""
        if not hasattr(self, "_pending_flatten_reason"):
            return
        reason = self._pending_flatten_reason
        try:
            await self.execution_client.cancel_all(symbol="MNQ")
            await self.execution_client.close_all_positions()  # type: ignore[attr-defined]
            self.telemetry.alert("FORCE_FLATTEN", reason=reason)
        except Exception as e:
            self.telemetry.alert("FORCE_FLATTEN_FAILED", reason=reason, error=str(e))
            raise
        finally:
            delattr(self, "_pending_flatten_reason")
```

- [ ] **Step 4: Verify + commit.**

```bash
pytest tests/test_risk_gate_on_tick.py -v
git add src/bot/risk/gate.py tests/test_risk_gate_on_tick.py
git commit -m "feat(risk): TopstepRiskGate.on_tick + equity-touch force-flatten trigger"
```

---

### Tasks 14-17: Hardening + final verification

- **T14: Force-flatten idempotency + strategy-disabled latch** — second force_flatten call is a no-op; after flatten, `approve_or_deny` returns `OrderDenied(rule="STRATEGY_DISABLED")`.
- **T15: Property-based tests** with hypothesis — `approve_or_deny(intent, state) == approve_or_deny(intent, state)`, no state mutation, monotone in equity.
- **T16: DST tests** with freezegun — clock alert at "15:10 America/Chicago" fires at correct UTC instant on 2026-03-08 + 2026-11-01.
- **T17: Conformance with ExecutionClient** — strategy can't bypass the gate; verify `ExecutionClient.place_order` is NEVER called on `OrderDenied` paths.

For each: write 3-5 tests, ensure they pass, commit.

---

### Task 18: Final verification + tag

```bash
source ~/.venvs/topstep-bot/bin/activate
cd "/Users/abusiddique/Library/Mobile Documents/com~apple~CloudDocs/projects/algo trade training"
ruff check src/ tests/
mypy src/ tests/
pytest -v
```

Expect ~180 tests pass; ruff/mypy clean.

```bash
git tag plan-03-risk-engine-complete
```

---

## Out-of-scope for Plan 3

- ❌ Nautilus `RiskEngine` host wiring (Plan 4 backtest harness / Plan 6 IB Paper)
- ❌ Real `Telemetry` adapter (`bot.journal` / Telegram → Plan 7)
- ❌ Force-flatten path through real broker (Plan 4 Sim / Plan 6 IB / Plan 8 TopstepX)
- ❌ EFA Consistency payout-window detection (the `gate_payout` is per-call; payout-orchestration UI is Plan 7+)
- ❌ News calendar API integration (Trading Economics / FRED) — manual YAML for v1

---

## Notes for the executor

- Tasks 10-12 (rules 4-7 + safety buffer) are bundled aggressively; expand into more tasks if you need finer-grained commits.
- The gate is PURE — no I/O. All side effects (telemetry, execution_client calls) happen in `_drain_flatten` and are async; the rule-check pure-function core stays synchronous.
- Property-based tests (T15) are the highest-leverage tests in the entire plan. Spend time on them.
