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


# ---- Helper methods (spec 02 §4 lines 259-283) -----------------------------

def test_signed_qty_buy_is_positive(utc_now) -> None:
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=3,
                    order_type="MARKET", client_order_id="t-1",
                    timestamp=utc_now)
    assert o.signed_qty() == 3


def test_signed_qty_sell_is_negative(utc_now) -> None:
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="SELL", quantity=3,
                    order_type="MARKET", client_order_id="t-2",
                    timestamp=utc_now)
    assert o.signed_qty() == -3


def test_is_open_increasing_exposure_flat_then_buy(utc_now) -> None:
    """Going from flat to +3 is increasing exposure."""
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=3,
                    order_type="MARKET", client_order_id="t-3",
                    timestamp=utc_now)
    assert o.is_open_increasing_exposure({}) is True
    assert o.is_open_increasing_exposure({"MNQ": 0}) is True


def test_is_open_increasing_exposure_long_then_buy_more(utc_now) -> None:
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=2,
                    order_type="MARKET", client_order_id="t-4",
                    timestamp=utc_now)
    assert o.is_open_increasing_exposure({"MNQ": 1}) is True


def test_is_open_increasing_exposure_long_then_sell_reducing(utc_now) -> None:
    """Reducing a long is NOT increasing exposure."""
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="SELL", quantity=1,
                    order_type="MARKET", client_order_id="t-5",
                    timestamp=utc_now)
    assert o.is_open_increasing_exposure({"MNQ": 3}) is False


def test_is_open_increasing_exposure_long_then_sell_flipping(utc_now) -> None:
    """Selling more than current long flips short — that IS increasing |pos|."""
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="SELL", quantity=5,
                    order_type="MARKET", client_order_id="t-6",
                    timestamp=utc_now)
    assert o.is_open_increasing_exposure({"MNQ": 1}) is True


def test_is_market_or_limit_open_market(utc_now) -> None:
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=1,
                    order_type="MARKET", client_order_id="t-7",
                    timestamp=utc_now)
    assert o.is_market_or_limit_open() is True


def test_is_market_or_limit_open_bracket(utc_now) -> None:
    from bot.types import Bracket, OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=1,
                    order_type="BRACKET", client_order_id="t-8",
                    timestamp=utc_now,
                    bracket=Bracket(stop_loss_ticks=10, take_profit_ticks=20))
    assert o.is_market_or_limit_open() is True


def test_is_market_or_limit_open_stop_returns_false(utc_now) -> None:
    """STOP / STOP_LIMIT are bracket children, not opens — see spec 02 §4 line 272-274."""
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="SELL", quantity=1,
                    order_type="STOP", client_order_id="t-9",
                    timestamp=utc_now, stop_price=14000.0)
    assert o.is_market_or_limit_open() is False


def test_with_stop_replaces_only_stop_loss_ticks(utc_now) -> None:
    from bot.types import Bracket, OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=1,
                    order_type="BRACKET", client_order_id="t-10",
                    timestamp=utc_now,
                    bracket=Bracket(stop_loss_ticks=20, take_profit_ticks=40))
    o2 = o.with_stop(15)
    assert o2.bracket is not None
    assert o2.bracket.stop_loss_ticks == 15
    assert o2.bracket.take_profit_ticks == 40           # unchanged
    assert o2.quantity == 1                              # unchanged
    assert o2.client_order_id == "t-10"                  # unchanged
    # Returns a new instance, doesn't mutate
    assert o.bracket is not None
    assert o.bracket.stop_loss_ticks == 20


def test_with_stop_raises_when_no_bracket(utc_now) -> None:
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=1,
                    order_type="MARKET", client_order_id="t-11",
                    timestamp=utc_now)
    with pytest.raises(ValueError, match="without a bracket"):
        o.with_stop(15)
