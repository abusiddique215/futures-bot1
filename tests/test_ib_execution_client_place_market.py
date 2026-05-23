"""IBExecutionClient.place_order — MARKET + idempotency."""
from __future__ import annotations

from datetime import UTC, datetime

from bot.execution.ib_client import IBExecutionClient
from bot.types import OrderIntent
from tests.fakes.fake_ib import FakeIB


def _intent(client_order_id: str = "ord-1", side: str = "BUY", qty: int = 1) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ",
        side=side,  # type: ignore[arg-type]
        quantity=qty,
        order_type="MARKET",
        client_order_id=client_order_id,
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )


async def test_place_market_order_calls_ib_placeorder() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    event = await c.place_order(_intent("ord-1"))

    assert event.status == "PENDING"
    assert event.client_order_id == "ord-1"
    # broker_order_id is a stringified IB orderId
    assert event.broker_order_id == str(fake.placed_orders[0].order.orderId)
    # One order placed on the MNQ contract
    assert len(fake.placed_orders) == 1
    placed = fake.placed_orders[0]
    assert placed.contract.symbol == "MNQ"
    assert placed.order.action == "BUY"
    assert placed.order.totalQuantity == 1
    # orderRef set for IB-side dedup
    assert placed.order.orderRef == "ord-1"


async def test_place_market_order_sell_side() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    await c.place_order(_intent("ord-2", side="SELL", qty=3))
    placed = fake.placed_orders[0]
    assert placed.order.action == "SELL"
    assert placed.order.totalQuantity == 3


async def test_place_order_idempotent_on_client_order_id() -> None:
    """Re-submitting the same client_order_id returns the cached event;
    ib.placeOrder is NOT called twice."""
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    e1 = await c.place_order(_intent("ord-3"))
    e2 = await c.place_order(_intent("ord-3"))

    assert e1 == e2
    assert len(fake.placed_orders) == 1


async def test_distinct_intents_get_distinct_broker_ids() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    e1 = await c.place_order(_intent("a"))
    e2 = await c.place_order(_intent("b"))
    assert e1.broker_order_id != e2.broker_order_id
    assert len(fake.placed_orders) == 2
