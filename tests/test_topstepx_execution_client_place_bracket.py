"""TopstepXExecutionClient.place_order — BRACKET path (server-attached OCO).

Spec 02 §3.5 bracket-translation. Unlike IB (3 separate placeOrder calls
with OCA group), TopstepX takes the bracket as INLINE fields on a single
place_order body. We send ticks directly; TopstepX converts on the server.

These tests assert on the body dict produced by _translate_bracket so the
wire shape is canonical regardless of SDK refactors.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.execution.topstepx_client import TopstepXExecutionClient
from bot.types import Bracket, OrderIntent
from tests.fakes.fake_projectx import FakeAccount, FakeProjectX


def _bracket_intent(
    side: str = "BUY",
    *,
    sl_ticks: int = 8,
    tp_ticks: int = 16,
    limit_price: float | None = 17_500.0,
) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ",
        side=side,  # type: ignore[arg-type]
        quantity=1,
        order_type="BRACKET",
        client_order_id="br-1",
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
        limit_price=limit_price,
        bracket=Bracket(stop_loss_ticks=sl_ticks, take_profit_ticks=tp_ticks),
    )


async def _connected_client(fake: FakeProjectX) -> TopstepXExecutionClient:
    client = TopstepXExecutionClient(
        username="u", api_key="k", account_name="acct-A",
        env="paper", client_factory=lambda: fake,
    )
    await client.connect(symbol="MNQ")
    return client


# ----- _translate_bracket unit tests --------------------------------------


def test_translate_bracket_buy_side_is_zero() -> None:
    """Same SIDE_BUY=0 footgun guard, this time inside the bracket path."""
    intent = _bracket_intent(side="BUY")
    body = TopstepXExecutionClient._translate_bracket(
        intent, account_id=42, contract_id="c",
    )
    assert body["side"] == 0


def test_translate_bracket_sell_side_is_one() -> None:
    intent = _bracket_intent(side="SELL")
    body = TopstepXExecutionClient._translate_bracket(
        intent, account_id=42, contract_id="c",
    )
    assert body["side"] == 1


def test_translate_bracket_contains_stop_loss_block_with_ticks() -> None:
    """Spec §3.5: TopstepX takes ticks directly; server converts. Block is
    `stopLossBracket: {ticks, type}` on wire. SDK shape uses snake_case
    nested key `stop_loss_bracket` carrying the same data."""
    intent = _bracket_intent(sl_ticks=8)
    body = TopstepXExecutionClient._translate_bracket(
        intent, account_id=42, contract_id="c",
    )
    assert "stop_loss_bracket" in body
    assert body["stop_loss_bracket"]["ticks"] == 8
    # type=4 == STOP order on the bracket child.
    assert body["stop_loss_bracket"]["type"] == 4


def test_translate_bracket_contains_take_profit_block_with_ticks() -> None:
    intent = _bracket_intent(tp_ticks=16)
    body = TopstepXExecutionClient._translate_bracket(
        intent, account_id=42, contract_id="c",
    )
    assert "take_profit_bracket" in body
    assert body["take_profit_bracket"]["ticks"] == 16
    # type=1 == LIMIT order on the bracket child.
    assert body["take_profit_bracket"]["type"] == 1


def test_translate_bracket_carries_custom_tag() -> None:
    intent = _bracket_intent()
    body = TopstepXExecutionClient._translate_bracket(
        intent, account_id=42, contract_id="c",
    )
    assert body["custom_tag"] == "br-1"


def test_translate_bracket_uses_market_entry_when_no_limit_price() -> None:
    """If intent.limit_price is None, the entry leg is MARKET (type=2);
    server still attaches the bracket as soon as the entry fills."""
    intent = _bracket_intent(limit_price=None)
    body = TopstepXExecutionClient._translate_bracket(
        intent, account_id=42, contract_id="c",
    )
    assert body["order_type"] == 2  # MARKET entry
    assert "limit_price" not in body


def test_translate_bracket_uses_limit_entry_when_price_given() -> None:
    intent = _bracket_intent(limit_price=17_500.0)
    body = TopstepXExecutionClient._translate_bracket(
        intent, account_id=42, contract_id="c",
    )
    assert body["order_type"] == 1  # LIMIT entry
    assert body["limit_price"] == 17_500.0


def test_translate_bracket_without_bracket_raises() -> None:
    """A BRACKET order_type without intent.bracket is a misconfiguration."""
    intent = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1, order_type="BRACKET",
        client_order_id="x",
        timestamp=datetime(2026, 5, 22, tzinfo=UTC),
        bracket=None, limit_price=None,
    )
    with pytest.raises(ValueError, match="bracket"):
        TopstepXExecutionClient._translate_bracket(
            intent, account_id=42, contract_id="c",
        )


# ----- async end-to-end ---------------------------------------------------


async def test_place_bracket_makes_single_sdk_call() -> None:
    """spec §3.5: unlike IB's 3 placeOrder calls, TopstepX BRACKET is a
    SINGLE place_order with inline bracket blocks."""
    fake = FakeProjectX(accounts=[FakeAccount(id=42, name="acct-A")])
    client = await _connected_client(fake)

    event = await client.place_order(_bracket_intent())

    assert event.status == "PENDING"
    assert fake.suite is not None
    # Exactly one SDK call — bracket children travel inline.
    assert len(fake.suite.orders.placed_bodies) == 1
    body = fake.suite.orders.placed_bodies[0]
    assert body["side"] == 0
    assert body["stop_loss_bracket"]["ticks"] == 8
    assert body["take_profit_bracket"]["ticks"] == 16


async def test_place_bracket_is_idempotent() -> None:
    fake = FakeProjectX(accounts=[FakeAccount(id=42, name="acct-A")])
    client = await _connected_client(fake)
    intent = _bracket_intent()

    first = await client.place_order(intent)
    second = await client.place_order(intent)

    assert first == second
    assert fake.suite is not None
    assert len(fake.suite.orders.placed_bodies) == 1
