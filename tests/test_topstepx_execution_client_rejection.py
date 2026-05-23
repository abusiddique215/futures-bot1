"""TopstepXExecutionClient server-side rejection translation.

Spec 02 §3.3 server-side rule enforcement:

  > TopstepX enforces trailing MLL, DLL, position cap, 3:10 PM flat on
  > the server. The adapter MUST treat a rejection (errorCode != 0) as
  > informational, not fatal — it means our client-side TopstepRiskGate
  > failed to predict the server's decision, which is a bug worth
  > logging loudly but not a reason to crash.

The adapter translates server rejections into OrderEvent(status="REJECTED")
with the error code in a metadata field. The wire-format response shape:
OrderPlaceResponse(orderId, success, errorCode, errorMessage).
"""
from __future__ import annotations

from datetime import UTC, datetime

from bot.execution.topstepx_client import TopstepXExecutionClient
from bot.types import OrderIntent
from tests.fakes.fake_projectx import (
    FakeAccount,
    FakeOrderPlaceResponse,
    FakeProjectX,
)


def _intent(client_order_id: str = "rej-1") -> OrderIntent:
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


async def test_rejected_response_yields_rejected_order_event() -> None:
    """errorCode != 0 → OrderEvent(status='REJECTED'). NOT an exception."""
    client, fake = await _connected_client()
    fake.next_place_response = FakeOrderPlaceResponse(
        orderId=0, success=False, errorCode=11,
        errorMessage="Trailing MLL exceeded",
    )

    event = await client.place_order(_intent())

    assert event.status == "REJECTED"
    assert event.client_order_id == "rej-1"
    assert event.filled_quantity == 0
    assert event.avg_fill_price is None


async def test_rejected_event_metadata_carries_error_code_and_message() -> None:
    """The metadata field exposes errorCode + errorMessage so downstream
    observability / journal can log the exact server reason."""
    client, fake = await _connected_client()
    fake.next_place_response = FakeOrderPlaceResponse(
        orderId=0, success=False, errorCode=42,
        errorMessage="Position cap exceeded",
    )

    event = await client.place_order(_intent())

    assert event.metadata is not None
    assert event.metadata["errorCode"] == 42
    assert event.metadata["errorMessage"] == "Position cap exceeded"


async def test_rejected_order_is_still_cached_for_idempotency() -> None:
    """A REJECTED event is cached the same way a PENDING event is:
    re-posting the same client_order_id returns the same REJECTED
    event rather than retrying.

    Rationale: if the server already rejected this client_order_id, a
    naive retry would do nothing different — the spec §3.3 rule about
    server-side enforcement means the strategy needs new state before
    placing a different order.
    """
    client, fake = await _connected_client()
    fake.next_place_response = FakeOrderPlaceResponse(
        orderId=0, success=False, errorCode=11, errorMessage="MLL",
    )

    first = await client.place_order(_intent("dup-1"))
    second = await client.place_order(_intent("dup-1"))

    assert first == second
    assert first.status == "REJECTED"
    assert fake.suite is not None
    assert len(fake.suite.orders.placed_bodies) == 1  # only one SDK call


async def test_successful_response_yields_pending_event() -> None:
    """Sanity: the happy path is still PENDING, not REJECTED."""
    client, fake = await _connected_client()
    fake.next_place_response = FakeOrderPlaceResponse(
        orderId=999, success=True, errorCode=0, errorMessage=None,
    )

    event = await client.place_order(_intent())

    assert event.status == "PENDING"
    assert event.broker_order_id == "999"
    # metadata may be None on the happy path — no error fields to carry.
