"""TopstepXExecutionClient.place_order — MARKET path + idempotency.

Spec 02 §3.3 order-placement + §3.4 side-encoding + §3.8 idempotency.

The required test `test_translate_buy_emits_side_zero` is the
SIDE_BUY=0 footgun guard at the wire-translation layer. T2 covered the
constants; this test verifies the constants flow through the OrderIntent
→ body translation correctly.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.execution.topstepx_client import TopstepXExecutionClient
from bot.types import OrderIntent
from tests.fakes.fake_projectx import (
    FakeAccount,
    FakeOrderPlaceResponse,
    FakeProjectX,
)


def _intent(
    side: str = "BUY",
    *,
    quantity: int = 1,
    client_order_id: str = "t-1",
    order_type: str = "MARKET",
) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ",
        side=side,  # type: ignore[arg-type]
        quantity=quantity,
        order_type=order_type,  # type: ignore[arg-type]
        client_order_id=client_order_id,
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )


async def _connected_client(fake: FakeProjectX) -> TopstepXExecutionClient:
    client = TopstepXExecutionClient(
        username="u",
        api_key="k",
        account_name="acct-A",
        env="paper",
        client_factory=lambda: fake,
    )
    await client.connect(symbol="MNQ")
    return client


# ----- the required defensive test ---------------------------------------


def test_translate_buy_emits_side_zero() -> None:
    """REQUIRED — spec 02 §3.4 line 158.

    Calls TopstepXExecutionClient._translate directly with a BUY intent
    and asserts body["side"] == 0. This is the canonical SIDE_BUY=0
    footgun assertion at the translation layer. Wrong value here means
    every live BUY silently sells.
    """
    intent = _intent(side="BUY")
    body = TopstepXExecutionClient._translate(
        intent, account_id=42, contract_id="CON.F.US.MNQ.M26",
    )
    assert body["side"] == 0  # NOT 1.


def test_translate_sell_emits_side_one() -> None:
    intent = _intent(side="SELL")
    body = TopstepXExecutionClient._translate(
        intent, account_id=42, contract_id="CON.F.US.MNQ.M26",
    )
    assert body["side"] == 1


def test_translate_market_emits_type_two() -> None:
    """spec §3.3 type-mapping: MARKET == 2."""
    intent = _intent(order_type="MARKET")
    body = TopstepXExecutionClient._translate(
        intent, account_id=42, contract_id="c",
    )
    assert body["order_type"] == 2


def test_translate_carries_client_order_id_as_custom_tag() -> None:
    """spec §3.8: client_order_id flows to TopstepX `customTag` for
    server-side idempotency."""
    intent = _intent(client_order_id="abc-123")
    body = TopstepXExecutionClient._translate(
        intent, account_id=42, contract_id="c",
    )
    assert body["custom_tag"] == "abc-123"


def test_translate_carries_account_and_contract() -> None:
    intent = _intent()
    body = TopstepXExecutionClient._translate(
        intent, account_id=42, contract_id="CON.F.US.MNQ.M26",
    )
    assert body["account_id"] == 42
    assert body["contract_id"] == "CON.F.US.MNQ.M26"


def test_translate_carries_size() -> None:
    intent = _intent(quantity=3)
    body = TopstepXExecutionClient._translate(
        intent, account_id=42, contract_id="c",
    )
    assert body["size"] == 3


# ----- async tests against the FakeProjectX -------------------------------


async def test_place_market_buy_calls_sdk_with_side_zero() -> None:
    """End-to-end: place_order(BUY) reaches the SDK with side=0."""
    fake = FakeProjectX(accounts=[FakeAccount(id=42, name="acct-A")])
    client = await _connected_client(fake)
    intent = _intent(side="BUY")

    event = await client.place_order(intent)

    assert event.status == "PENDING"
    assert event.client_order_id == "t-1"
    assert fake.suite is not None
    assert len(fake.suite.orders.placed_bodies) == 1
    body = fake.suite.orders.placed_bodies[0]
    assert body["side"] == 0  # SIDE_BUY=0 footgun
    assert body["order_type"] == 2
    assert body["size"] == 1


async def test_place_market_returns_broker_order_id() -> None:
    fake = FakeProjectX(accounts=[FakeAccount(id=42, name="acct-A")])
    fake.next_place_response = FakeOrderPlaceResponse(orderId=12345)
    client = await _connected_client(fake)

    event = await client.place_order(_intent())

    assert event.broker_order_id == "12345"


async def test_place_market_is_idempotent_on_client_order_id() -> None:
    """spec §3.8: re-posting the same client_order_id returns the cached
    OrderEvent rather than placing a second order."""
    fake = FakeProjectX(accounts=[FakeAccount(id=42, name="acct-A")])
    client = await _connected_client(fake)
    intent = _intent(client_order_id="cf-7")

    first = await client.place_order(intent)
    second = await client.place_order(intent)

    assert first == second
    assert fake.suite is not None
    assert len(fake.suite.orders.placed_bodies) == 1  # only one SDK call


async def test_place_order_before_connect_raises() -> None:
    fake = FakeProjectX()
    client = TopstepXExecutionClient(
        username="u", api_key="k", account_name="acct-A",
        env="paper", client_factory=lambda: fake,
    )
    with pytest.raises(RuntimeError, match="connect"):
        await client.place_order(_intent())
