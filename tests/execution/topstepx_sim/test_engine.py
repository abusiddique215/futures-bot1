"""TopstepSimEngine — order acceptance + fill simulation tests (Plan 11 T2)."""
from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from bot.execution.topstepx_constants import SIDE_BUY, SIDE_SELL, topstepx_side
from bot.execution.topstepx_sim.account import SimAccount
from bot.execution.topstepx_sim.engine import TopstepSimEngine
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.types import Bracket, OrderIntent


def _intent(
    *,
    side: str = "BUY",
    qty: int = 1,
    ts: datetime | None = None,
    coid: str = "o-1",
    bracket: Bracket | None = None,
) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ",
        side=side,  # type: ignore[arg-type]
        quantity=qty,
        order_type="MARKET",
        client_order_id=coid,
        timestamp=ts or datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
        bracket=bracket,
    )


def _engine(
    *,
    slippage_ticks: int = 0,
    now: datetime | None = None,
    stage: str = "combine_active",
) -> TopstepSimEngine:
    account = SimAccount.new(
        start_balance=50_000.0, mll_amount=2_000.0,
        stage=stage,  # type: ignore[arg-type]
    )
    policy = CombineIntradayDrawdown(50_000.0, 2_000.0, max_mini=5)
    now_dt = now or datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    return TopstepSimEngine(
        account=account,
        combine_policy=policy,
        efa_policy=None,
        slippage_ticks=slippage_ticks,
        now=lambda: now_dt,
    )


def test_submit_market_buy_fills_at_mid() -> None:
    eng = _engine()
    ev = eng.submit_order(_intent(), mid_price=18_000.0)
    assert ev.status == "FILLED"
    assert ev.avg_fill_price == pytest.approx(18_000.0)
    assert ev.filled_quantity == 1
    assert eng.account.open_positions["MNQ"] == (1, 18_000.0)


def test_submit_market_buy_with_slippage_fills_at_mid_plus_ticks() -> None:
    eng = _engine(slippage_ticks=2)
    ev = eng.submit_order(_intent(side="BUY"), mid_price=18_000.0)
    # MNQ tick = 0.25 pt -> 2 ticks = 0.50 pt
    assert ev.avg_fill_price == pytest.approx(18_000.50)


def test_submit_market_sell_with_slippage_fills_at_mid_minus_ticks() -> None:
    eng = _engine(slippage_ticks=2)
    ev = eng.submit_order(_intent(side="SELL"), mid_price=18_000.0)
    assert ev.avg_fill_price == pytest.approx(17_999.50)


def test_submit_order_exceeding_max_position_is_rejected() -> None:
    eng = _engine()
    # Combine 50K cap on MNQ = 5 mini * 10 = 50. Send 51.
    ev = eng.submit_order(_intent(qty=51), mid_price=18_000.0)
    assert ev.status == "REJECTED"
    assert ev.metadata is not None
    assert ev.metadata.get("reason") == "MAX_POSITION"
    assert "MNQ" not in eng.account.open_positions


def test_submit_open_after_hard_flat_is_rejected() -> None:
    # 15:11 CT in May 2026 = 20:11 UTC (CDT, UTC-5)
    after = datetime(2026, 5, 22, 20, 11, tzinfo=UTC)
    eng = _engine(now=after)
    ev = eng.submit_order(_intent(ts=after), mid_price=18_000.0)
    assert ev.status == "REJECTED"
    assert ev.metadata is not None
    assert ev.metadata.get("reason") == "HARD_FLAT_CLOCK"


def test_submit_close_after_hard_flat_is_accepted() -> None:
    """Reducer / close order after 15:10 CT still fills (the engine only blocks
    new exposure, not flatten orders)."""
    after = datetime(2026, 5, 22, 20, 11, tzinfo=UTC)
    before = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)

    # Open a position before the cutoff.
    eng = _engine(now=before)
    eng.submit_order(_intent(side="BUY", coid="open-1", ts=before), mid_price=18_000.0)
    # Now jump clock past hard-flat and send a close.
    eng.set_now(after)
    ev = eng.submit_order(
        _intent(side="SELL", coid="close-1", ts=after), mid_price=18_000.0,
    )
    assert ev.status == "FILLED"


def test_tick_triggers_mll_liquidation_and_sets_combine_failed() -> None:
    """Equity dipping below phantom MLL flattens positions and marks failed."""
    eng = _engine()
    # Open 1 lot MNQ; price moves against us 2 pts → -$4. Then move way down.
    eng.submit_order(_intent(side="BUY"), mid_price=18_000.0)
    # Drop equity to 47_900 ($2_100 loss = need MNQ down by 1_050 pts = mid -> 16_950)
    acc_after = eng.tick(mid_price=16_950.0, symbol="MNQ")
    assert acc_after.stage == "combine_failed"
    assert acc_after.open_positions == {}


def test_tick_efa_active_mll_liquidation_marks_efa_failed() -> None:
    eng = _engine(stage="efa_active")
    eng.submit_order(_intent(side="BUY"), mid_price=18_000.0)
    acc_after = eng.tick(mid_price=16_950.0, symbol="MNQ")
    assert acc_after.stage == "efa_failed"


def test_tick_without_breach_is_no_op_on_stage() -> None:
    eng = _engine()
    eng.submit_order(_intent(side="BUY"), mid_price=18_000.0)
    acc_after = eng.tick(mid_price=18_001.0, symbol="MNQ")
    assert acc_after.stage == "combine_active"
    assert acc_after.open_positions == {"MNQ": (1, 18_000.0)}


def test_eod_flattens_positions_past_hard_flat() -> None:
    after = datetime(2026, 5, 22, 20, 11, tzinfo=UTC)
    before = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    eng = _engine(now=before)
    eng.submit_order(_intent(side="BUY", ts=before), mid_price=18_000.0)
    eng.set_now(after)
    acc_after = eng.eod(mid_price=18_005.0, symbol="MNQ")
    assert acc_after.open_positions == {}


def test_cancel_order_always_returns_too_late() -> None:
    eng = _engine()
    ev = eng.cancel_order("nonexistent")
    assert ev.status == "REJECTED"
    assert ev.metadata is not None
    assert ev.metadata.get("reason") == "TOO_LATE"


def test_side_encoding_matches_topstepx_constants() -> None:
    """Engine's wire-encode of a fill matches `topstepx_side` exactly.

    Locks in the SIDE_BUY=0 footgun on the sim side too: if any future refactor
    diverges, parity vs the real adapter is broken and this test catches it.
    """
    assert topstepx_side("BUY") == SIDE_BUY == 0
    assert topstepx_side("SELL") == SIDE_SELL == 1

    eng = _engine()
    ev_buy = eng.submit_order(_intent(side="BUY", coid="b"), mid_price=18_000.0)
    assert ev_buy.metadata is not None
    assert ev_buy.metadata.get("topstepx_side") == SIDE_BUY

    ev_sell = eng.submit_order(
        _intent(side="SELL", coid="s", qty=1), mid_price=18_000.0,
    )
    assert ev_sell.metadata is not None
    assert ev_sell.metadata.get("topstepx_side") == SIDE_SELL


def test_engine_default_hard_flat_time_matches_constant() -> None:
    """Constructor default should match bot.constants.HARD_FLAT_TIME_CT."""
    from bot.constants import HARD_FLAT_TIME_CT
    account = SimAccount.new(start_balance=50_000.0, mll_amount=2_000.0)
    policy = CombineIntradayDrawdown(50_000.0, 2_000.0, max_mini=5)
    eng = TopstepSimEngine(
        account=account,
        combine_policy=policy,
        efa_policy=None,
        now=lambda: datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )
    assert eng.hard_flat_time_ct == HARD_FLAT_TIME_CT


def test_hard_flat_uses_chicago_timezone() -> None:
    """Sanity check that the engine compares in CT, not UTC."""
    chicago = ZoneInfo("America/Chicago")
    ts_ct_1509 = datetime(2026, 5, 22, 15, 9, tzinfo=chicago)
    eng = _engine(now=ts_ct_1509, slippage_ticks=0)
    ev = eng.submit_order(_intent(ts=ts_ct_1509), mid_price=18_000.0)
    assert ev.status == "FILLED"
    # And 15:10 exactly → reject (>= comparison).
    ts_ct_1510 = datetime(2026, 5, 22, 15, 10, tzinfo=chicago)
    eng2 = _engine(now=ts_ct_1510)
    ev2 = eng2.submit_order(_intent(ts=ts_ct_1510, coid="x"), mid_price=18_000.0)
    assert ev2.status == "REJECTED"


def test_set_now_advances_engine_clock() -> None:
    """set_now lets tests jump the engine clock between calls."""
    eng = _engine(now=datetime(2026, 5, 22, 14, 30, tzinfo=UTC))
    assert eng.now().time() == time(14, 30)
    eng.set_now(datetime(2026, 5, 22, 15, 0, tzinfo=UTC))
    assert eng.now().time() == time(15, 0)
