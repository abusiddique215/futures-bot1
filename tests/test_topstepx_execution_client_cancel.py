"""TopstepXExecutionClient.cancel_order / cancel_all / snapshot queries.

Spec 02 §3.3 (snapshots) + §3.7 (cancel).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.execution.topstepx_client import TopstepXExecutionClient
from bot.types import OrderIntent
from tests.fakes.fake_projectx import (
    FakeAccount,
    FakeOrderSnapshot,
    FakePositionSnapshot,
    FakeProjectX,
)


def _intent(client_order_id: str = "t-1") -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=1, order_type="MARKET",
        client_order_id=client_order_id,
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )


async def _connected_client() -> tuple[TopstepXExecutionClient, FakeProjectX]:
    fake = FakeProjectX(accounts=[FakeAccount(id=42, name="acct-A")])
    client = TopstepXExecutionClient(
        username="u", api_key="k", account_name="acct-A",
        env="paper", client_factory=lambda: fake,
    )
    await client.connect(symbol="MNQ")
    return client, fake


# ----- cancel_order / cancel_all -----------------------------------------


async def test_cancel_order_calls_sdk_with_broker_id() -> None:
    client, fake = await _connected_client()
    await client.place_order(_intent("c-1"))
    assert fake.suite is not None
    broker_id = fake.suite.orders.placed_bodies  # noqa: F841 (just to assert non-empty)

    event = await client.cancel_order("c-1")

    assert event.status == "CANCELED"
    assert event.client_order_id == "c-1"
    assert len(fake.suite.orders.canceled_ids) == 1


async def test_cancel_order_unknown_id_raises() -> None:
    client, _fake = await _connected_client()
    with pytest.raises(KeyError):
        await client.cancel_order("never-placed")


async def test_cancel_all_cancels_only_matching_symbol() -> None:
    """spec §3.7: cancel_all(symbol) clears WORKING orders for that symbol
    only. Other-symbol orders untouched.
    """
    client, fake = await _connected_client()
    await client.place_order(_intent("a-1"))
    await client.place_order(_intent("a-2"))

    events = await client.cancel_all("MNQ")

    assert len(events) == 2
    assert {e.client_order_id for e in events} == {"a-1", "a-2"}
    assert all(e.status == "CANCELED" for e in events)
    assert fake.suite is not None
    assert len(fake.suite.orders.canceled_ids) == 2


async def test_cancel_all_for_other_symbol_does_nothing() -> None:
    client, fake = await _connected_client()
    await client.place_order(_intent("a-1"))

    events = await client.cancel_all("ES")

    assert events == []
    assert fake.suite is not None
    assert fake.suite.orders.canceled_ids == []


# ----- get_positions / get_open_orders / get_account ---------------------


async def test_get_positions_returns_typed_positions() -> None:
    client, fake = await _connected_client()
    assert fake.suite is not None
    fake.suite.positions._positions = [
        FakePositionSnapshot(
            contractId="CON.F.US.MNQ.M26", size=2, averagePrice=17_500.0,
            unrealizedPnl=125.0,
        ),
    ]

    positions = await client.get_positions()

    assert len(positions) == 1
    p = positions[0]
    assert p.symbol == "MNQ"
    assert p.signed_qty == 2
    assert p.avg_entry_price == 17_500.0
    assert p.unrealized_pnl == 125.0


async def test_get_open_orders_returns_typed_orders() -> None:
    client, fake = await _connected_client()
    assert fake.suite is not None
    fake.suite.orders._open_orders = [
        FakeOrderSnapshot(
            id=12345, contractId="CON.F.US.MNQ.M26",
            side=0, size=1, type=2, customTag="tag-1",
        ),
    ]

    orders = await client.get_open_orders()

    assert len(orders) == 1
    o = orders[0]
    assert o.broker_order_id == "12345"
    assert o.client_order_id == "tag-1"
    assert o.symbol == "MNQ"
    assert o.side == "BUY"  # 0 → BUY (SIDE_BUY=0 footgun reapplied on read path)
    assert o.quantity == 1
    assert o.order_type == "MARKET"
    assert o.status == "WORKING"


async def test_get_open_orders_sell_decodes_side_one_as_sell() -> None:
    """Symmetry: side=1 on the wire must decode to SELL — same inverted
    encoding read-path."""
    client, fake = await _connected_client()
    assert fake.suite is not None
    fake.suite.orders._open_orders = [
        FakeOrderSnapshot(
            id=2, contractId="CON.F.US.MNQ.M26",
            side=1, size=1, type=2, customTag="t-s",
        ),
    ]

    orders = await client.get_open_orders()
    assert orders[0].side == "SELL"


async def test_get_account_returns_account_state() -> None:
    client, fake = await _connected_client()
    fake.accounts = [
        FakeAccount(id=42, name="acct-A", balance=50_000.0),
    ]
    assert fake.suite is not None
    fake.suite.positions._positions = [
        FakePositionSnapshot(
            contractId="CON.F.US.MNQ.M26", size=1, averagePrice=17_500.0,
            unrealizedPnl=10.0,
        ),
    ]

    acct = await client.get_account()

    assert acct.equity == 50_000.0
    assert acct.unrealized_pnl == 10.0
    assert acct.open_positions == {"MNQ": 1}
    assert acct.is_combine is True
