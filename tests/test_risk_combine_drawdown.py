"""CombineIntradayDrawdown — phantom-MLL state machine. Spec 04 §3.4, §4.3."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from bot.types import AccountState


def _state(equity: float, hw: float | None = None, **kw: Any) -> AccountState:
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
    """Symbol that has no registered MarketSpec raises ValueError.

    Plan 14: ES/GC and their micros are now registered, so this regression
    test uses CL (crude oil — not in scope) to keep exercising the unknown-
    symbol path.
    """
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)
    s = _state(equity=50_000)
    with pytest.raises(ValueError, match="Unsupported symbol"):
        p.max_position("CL", s)


# Plan 14: registry-driven multi-market support. NQ/MNQ rows are the original
# regression cases (kept above); ES/MES/GC/MGC verify the registry lookup.
@pytest.mark.parametrize(
    ("symbol", "expected_cap"),
    [
        ("NQ",  5),
        ("MNQ", 50),
        ("ES",  5),
        ("MES", 50),
        ("GC",  5),
        ("MGC", 50),
        # IB / TopstepX format with month-year suffix also resolves correctly.
        ("NQH26",  5),
        ("MGCG26", 50),
    ],
)
def test_max_position_per_market(symbol: str, expected_cap: int) -> None:
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)
    s = _state(equity=50_000)
    assert p.max_position(symbol, s) == expected_cap


def test_update_on_eod_is_noop_for_combine() -> None:
    """Combine ratchets on every tick; EoD is a no-op."""
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    p = CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5)
    s = _state(equity=51_000, hw=51_000)
    assert p.update_on_eod(s) == s
