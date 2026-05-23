"""IBExecutionClient.cancel_order + cancel_all."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.execution.ib_client import IBExecutionClient
from bot.types import OrderIntent
from tests.fakes.fake_ib import FakeIB


def _intent(client_order_id: str, symbol: str = "MNQ", side: str = "BUY") -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=1,
        order_type="MARKET",
        client_order_id=client_order_id,
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )


async def test_cancel_order_calls_ib_cancelorder_and_emits_canceled() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    placed_event = await c.place_order(_intent("ord-9"))

    event = await c.cancel_order("ord-9")
    assert event.status == "CANCELED"
    assert event.client_order_id == "ord-9"
    assert event.broker_order_id == placed_event.broker_order_id
    assert int(placed_event.broker_order_id) in fake.canceled_order_ids


async def test_cancel_unknown_order_raises_keyerror() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    with pytest.raises(KeyError):
        await c.cancel_order("never-placed")


async def test_cancel_all_cancels_only_matching_symbol() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    # Need a second contract for the "other-symbol" intent to be placed.
    # Use direct cache manipulation since qualifyContractsAsync sets MNQ only.
    from ib_async import Future
    other = Future(symbol="NQ", exchange="CME")
    other.conId = 99999
    c._contracts["NQ"] = other

    await c.place_order(_intent("a", symbol="MNQ"))
    await c.place_order(_intent("b", symbol="MNQ"))
    await c.place_order(_intent("c", symbol="NQ"))

    events = await c.cancel_all("MNQ")
    assert len(events) == 2
    ids = {e.client_order_id for e in events}
    assert ids == {"a", "b"}
    assert all(e.status == "CANCELED" for e in events)
    # NQ order untouched.
    assert len(fake.canceled_order_ids) == 2
