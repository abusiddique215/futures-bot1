"""Tests for Position, Order, and OrderEvent dataclasses.

Spec: 02-execution-clients.md §4.
"""
from __future__ import annotations

import pytest


def test_position_basic_fields(utc_now) -> None:
    from bot.types import Position
    p = Position(
        symbol="MNQ", signed_qty=2, avg_entry_price=15000.0,
        unrealized_pnl=50.0, opened_at=utc_now,
    )
    assert p.symbol == "MNQ"
    assert p.signed_qty == 2


def test_position_short_has_negative_signed_qty(utc_now) -> None:
    from bot.types import Position
    p = Position(symbol="MNQ", signed_qty=-3, avg_entry_price=15000.0,
                 unrealized_pnl=0.0, opened_at=utc_now)
    assert p.signed_qty == -3


def test_order_minimal(utc_now) -> None:
    from bot.types import Order
    o = Order(
        client_order_id="c-1",
        broker_order_id="b-1",
        symbol="MNQ",
        side="BUY",
        quantity=1,
        order_type="MARKET",
        status="WORKING",
        timestamp=utc_now,
    )
    assert o.client_order_id == "c-1"
    assert o.status == "WORKING"


def test_order_event_pending_fields(utc_now) -> None:
    from bot.types import OrderEvent
    ev = OrderEvent(
        client_order_id="c-1",
        broker_order_id="b-1",
        status="PENDING",
        filled_quantity=0,
        avg_fill_price=None,
        timestamp=utc_now,
    )
    assert ev.status == "PENDING"
    assert ev.metadata is None


def test_order_event_filled_with_metadata(utc_now) -> None:
    from bot.types import OrderEvent
    ev = OrderEvent(
        client_order_id="c-1",
        broker_order_id="b-1",
        status="FILLED",
        filled_quantity=1,
        avg_fill_price=15010.25,
        timestamp=utc_now,
        metadata={"venue": "GLOBEX"},
    )
    assert ev.filled_quantity == 1
    assert ev.metadata == {"venue": "GLOBEX"}


def test_order_event_rejected_status_allowed(utc_now) -> None:
    from bot.types import OrderEvent
    ev = OrderEvent(client_order_id="c-1", broker_order_id="",
                    status="REJECTED", filled_quantity=0,
                    avg_fill_price=None, timestamp=utc_now,
                    metadata={"errorCode": 17})
    assert ev.status == "REJECTED"


def test_position_is_frozen(utc_now) -> None:
    from dataclasses import FrozenInstanceError

    from bot.types import Position

    p = Position(symbol="MNQ", signed_qty=1, avg_entry_price=1.0,
                 unrealized_pnl=0.0, opened_at=utc_now)
    with pytest.raises(FrozenInstanceError):
        p.signed_qty = 99  # type: ignore[misc]
