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
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=hw,
        is_combine=True,
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
