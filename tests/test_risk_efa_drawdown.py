"""EFAStandardEoDDrawdown + EFAConsistencyDrawdown. Spec 04 §3.3, §4.4.

Scaling tiers VERIFIED 2026-05-22 (pre-Plan-1 verification).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.types import AccountState


def _state(equity: float, hw: float | None = None) -> AccountState:
    return AccountState(
        equity=equity,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
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
    s = _state(equity=51_500)  # profit = 1500 -> tier 2
    assert p.max_position("NQ",  s) == 3


def test_efa_scaling_tier_at_2000_is_5_mini() -> None:
    from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
    p = EFAStandardEoDDrawdown(mll_amount=2_000)
    s = _state(equity=52_000)  # profit = 2000 -> tier 3
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
    # best_day = 300, net_profit = 1_000 -> 30% -> passes
    assert p.gate_payout(best_day=300, net_profit=1_000) is True


def test_efa_consistency_check_fails_when_over_40pct() -> None:
    from bot.risk.efa_drawdown import EFAConsistencyDrawdown
    p = EFAConsistencyDrawdown(mll_amount=2_000)
    # best_day = 500, net_profit = 1_000 -> 50% -> fails
    assert p.gate_payout(best_day=500, net_profit=1_000) is False
