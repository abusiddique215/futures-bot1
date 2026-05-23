"""Tests for OrderIntent and Bracket dataclasses (bare-field tests only here;
helper-method tests live in their own task to keep tasks bite-sized).

Spec: 02-execution-clients.md §4.
"""
from __future__ import annotations

import pytest


def test_bracket_is_frozen_with_two_int_fields() -> None:
    from bot.types import Bracket
    b = Bracket(stop_loss_ticks=20, take_profit_ticks=40)
    assert b.stop_loss_ticks == 20
    assert b.take_profit_ticks == 40


def test_order_intent_minimal_market_buy(utc_now) -> None:
    from bot.types import OrderIntent
    o = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="MARKET",
        client_order_id="t-1",
        timestamp=utc_now,
    )
    assert o.symbol == "MNQ"
    assert o.side == "BUY"
    assert o.quantity == 1
    assert o.order_type == "MARKET"
    assert o.limit_price is None
    assert o.stop_price is None
    assert o.bracket is None


def test_order_intent_with_bracket(utc_now) -> None:
    from bot.types import Bracket, OrderIntent
    o = OrderIntent(
        symbol="MNQ", side="SELL", quantity=2,
        order_type="BRACKET",
        client_order_id="t-2",
        timestamp=utc_now,
        bracket=Bracket(stop_loss_ticks=15, take_profit_ticks=30),
    )
    assert o.bracket is not None
    assert o.bracket.stop_loss_ticks == 15


def test_order_intent_is_frozen(utc_now) -> None:
    from dataclasses import FrozenInstanceError

    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=1,
                    order_type="MARKET", client_order_id="t-3",
                    timestamp=utc_now)
    with pytest.raises(FrozenInstanceError):
        o.quantity = 99  # type: ignore[misc]
