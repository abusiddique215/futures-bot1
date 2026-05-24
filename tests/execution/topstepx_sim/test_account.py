"""SimAccount dataclass + stage transition tests (Plan 11 T1)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.execution.topstepx_sim.account import (
    SimAccount,
    SimFill,
    advance_stage,
    apply_fill,
    mark_to_market,
)


def _new_account() -> SimAccount:
    return SimAccount.new(start_balance=50_000.0, mll_amount=2_000.0)


def test_new_account_starts_in_combine_active_with_start_balance() -> None:
    a = _new_account()
    assert a.stage == "combine_active"
    assert a.balance == 50_000.0
    assert a.equity == 50_000.0
    assert a.high_water_equity == 50_000.0
    assert a.realized_pnl == 0.0
    assert a.unrealized_pnl == 0.0
    assert a.open_positions == {}
    assert a.start_balance == 50_000.0
    assert a.mll_amount == 2_000.0


def test_apply_fill_opens_position_on_first_fill() -> None:
    a = _new_account()
    fill = SimFill(
        symbol="MNQ", signed_qty=1, fill_price=18_000.0,
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )
    a2 = apply_fill(a, fill)
    assert a2.open_positions == {"MNQ": (1, 18_000.0)}
    assert a2.realized_pnl == 0.0


def test_apply_fill_close_realizes_pnl_long_winner() -> None:
    a = _new_account()
    ts = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    a = apply_fill(a, SimFill("MNQ", 1, 18_000.0, ts))
    a = apply_fill(a, SimFill("MNQ", -1, 18_010.0, ts))
    # MNQ: 10 pts * $2/pt * 1 = $20
    assert a.realized_pnl == pytest.approx(20.0)
    assert "MNQ" not in a.open_positions
    assert a.balance == pytest.approx(50_020.0)


def test_apply_fill_close_realizes_pnl_short_winner() -> None:
    a = _new_account()
    ts = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    a = apply_fill(a, SimFill("MNQ", -1, 18_000.0, ts))
    a = apply_fill(a, SimFill("MNQ", 1, 17_990.0, ts))
    assert a.realized_pnl == pytest.approx(20.0)


def test_mark_to_market_sets_unrealized_and_equity() -> None:
    a = _new_account()
    ts = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    a = apply_fill(a, SimFill("MNQ", 1, 18_000.0, ts))
    a = mark_to_market(a, mid_price=18_005.0, symbol="MNQ")
    # 5 pts * $2/pt = $10
    assert a.unrealized_pnl == pytest.approx(10.0)
    assert a.equity == pytest.approx(50_010.0)


def test_mark_to_market_flat_position_zero_unrealized() -> None:
    a = _new_account()
    a = mark_to_market(a, mid_price=18_000.0, symbol="MNQ")
    assert a.unrealized_pnl == 0.0
    assert a.equity == 50_000.0


def test_advance_stage_combine_active_to_passed_allowed() -> None:
    a = _new_account()
    a2 = advance_stage(a, "combine_passed")
    assert a2.stage == "combine_passed"


def test_advance_stage_combine_active_to_failed_allowed() -> None:
    a = _new_account()
    a2 = advance_stage(a, "combine_failed")
    assert a2.stage == "combine_failed"


def test_advance_stage_efa_active_to_payout_allowed() -> None:
    a = SimAccount.new(start_balance=50_000.0, mll_amount=2_000.0, stage="efa_active")
    a2 = advance_stage(a, "efa_payout")
    assert a2.stage == "efa_payout"


def test_advance_stage_efa_payout_to_funded_allowed() -> None:
    a = SimAccount.new(start_balance=50_000.0, mll_amount=2_000.0, stage="efa_payout")
    a2 = advance_stage(a, "funded")
    assert a2.stage == "funded"


def test_advance_stage_efa_active_to_failed_allowed() -> None:
    a = SimAccount.new(start_balance=50_000.0, mll_amount=2_000.0, stage="efa_active")
    a2 = advance_stage(a, "efa_failed")
    assert a2.stage == "efa_failed"


def test_advance_stage_skip_combine_to_funded_raises() -> None:
    a = _new_account()
    with pytest.raises(ValueError, match="illegal transition"):
        advance_stage(a, "funded")


def test_advance_stage_combine_to_efa_active_allowed() -> None:
    """Combine pass → broker promotes to EFA-active for next session."""
    a = SimAccount.new(start_balance=50_000.0, mll_amount=2_000.0, stage="combine_passed")
    a2 = advance_stage(a, "efa_active")
    assert a2.stage == "efa_active"


def test_advance_stage_from_terminal_failed_raises() -> None:
    a = SimAccount.new(start_balance=50_000.0, mll_amount=2_000.0, stage="combine_failed")
    with pytest.raises(ValueError, match="illegal transition"):
        advance_stage(a, "combine_passed")
