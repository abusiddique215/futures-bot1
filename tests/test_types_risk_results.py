"""Tests for OrderDenied and ApprovedOrder (TopstepRiskGate return types).

Spec: 04-risk-engine.md §4.1 lines 406-419.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from bot.types import AccountState, OrderIntent


def _make_intent_and_state(utc_now: datetime) -> tuple[OrderIntent, AccountState]:
    intent = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="MARKET", client_order_id="t-1", timestamp=utc_now,
    )
    state = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
    )
    return intent, state


def test_order_denied_fields(utc_now: datetime) -> None:
    from bot.types import OrderDenied
    intent, state = _make_intent_and_state(utc_now)
    d = OrderDenied(
        intent=intent, reason="DLL near limit",
        rule="DLL_NEAR_LIMIT", state_snapshot=state, timestamp=utc_now,
    )
    assert d.rule == "DLL_NEAR_LIMIT"
    assert d.state_snapshot is state


def test_approved_order_fields(utc_now: datetime) -> None:
    from bot.types import ApprovedOrder
    intent, state = _make_intent_and_state(utc_now)
    a = ApprovedOrder(intent=intent, state_snapshot=state, timestamp=utc_now)
    assert a.intent is intent


def test_order_denied_is_frozen(utc_now: datetime) -> None:
    from dataclasses import FrozenInstanceError

    from bot.types import OrderDenied
    intent, state = _make_intent_and_state(utc_now)
    d = OrderDenied(intent=intent, reason="r", rule="R",
                    state_snapshot=state, timestamp=utc_now)
    with pytest.raises(FrozenInstanceError):
        d.reason = "x"  # type: ignore[misc]


def test_approved_order_is_frozen(utc_now: datetime) -> None:
    from dataclasses import FrozenInstanceError

    from bot.types import ApprovedOrder
    intent, state = _make_intent_and_state(utc_now)
    a = ApprovedOrder(intent=intent, state_snapshot=state, timestamp=utc_now)
    with pytest.raises(FrozenInstanceError):
        a.timestamp = utc_now  # type: ignore[misc]
