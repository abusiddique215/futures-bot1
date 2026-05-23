"""IBExecutionClient.place_order — BRACKET (3-leg OCO)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.execution.ib_client import IBExecutionClient
from bot.types import Bracket, OrderIntent
from tests.fakes.fake_ib import FakeIB


def _bracket_intent(
    *,
    client_order_id: str = "br-1",
    side: str = "BUY",
    qty: int = 1,
    limit_price: float = 16_500.00,
    stop_ticks: int = 8,
    tp_ticks: int = 16,
) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ",
        side=side,  # type: ignore[arg-type]
        quantity=qty,
        order_type="BRACKET",
        client_order_id=client_order_id,
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
        limit_price=limit_price,
        bracket=Bracket(stop_loss_ticks=stop_ticks, take_profit_ticks=tp_ticks),
    )


async def test_bracket_buy_places_three_orders() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    await c.place_order(_bracket_intent())

    assert len(fake.placed_orders) == 3
    parent, tp, sl = (t.order for t in fake.placed_orders)

    # Transmit flags: parent + tp deferred, stop-loss (last) transmits all 3.
    assert parent.transmit is False
    assert tp.transmit is False
    assert sl.transmit is True


async def test_bracket_buy_computes_stop_and_take_profit_prices() -> None:
    """MNQ MIN_TICK=0.25. BUY entry@16500, stop=8 ticks, tp=16 ticks:
    stop = 16500 - 8*0.25 = 16498.0
    tp   = 16500 + 16*0.25 = 16504.0
    """
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    await c.place_order(_bracket_intent(
        side="BUY", limit_price=16_500.00, stop_ticks=8, tp_ticks=16,
    ))
    _parent, tp, sl = (t.order for t in fake.placed_orders)
    assert tp.lmtPrice == pytest.approx(16_504.0)
    assert sl.auxPrice == pytest.approx(16_498.0)


async def test_bracket_sell_inverts_stop_and_take_profit() -> None:
    """SELL entry@16500, stop=8 ticks, tp=16 ticks:
    stop = 16500 + 8*0.25 = 16502.0
    tp   = 16500 - 16*0.25 = 16496.0
    """
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    await c.place_order(_bracket_intent(
        side="SELL", limit_price=16_500.00, stop_ticks=8, tp_ticks=16,
    ))
    _parent, tp, sl = (t.order for t in fake.placed_orders)
    assert tp.lmtPrice == pytest.approx(16_496.0)
    assert sl.auxPrice == pytest.approx(16_502.0)


async def test_bracket_sets_order_refs_on_all_three_legs() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    await c.place_order(_bracket_intent(client_order_id="br-7"))
    parent, tp, sl = (t.order for t in fake.placed_orders)
    assert parent.orderRef == "br-7"
    assert tp.orderRef == "br-7-tp"
    assert sl.orderRef == "br-7-sl"


async def test_bracket_returns_pending_with_parent_broker_id() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    event = await c.place_order(_bracket_intent())
    parent = fake.placed_orders[0].order
    assert event.status == "PENDING"
    assert event.broker_order_id == str(parent.orderId)


async def test_bracket_missing_limit_price_raises() -> None:
    """Without a limit_price reference we can't compute absolute stop/TP — raise."""
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    intent = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1, order_type="BRACKET",
        client_order_id="br-no-lim",
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
        bracket=Bracket(stop_loss_ticks=8, take_profit_ticks=16),
    )
    with pytest.raises(ValueError, match="limit_price"):
        await c.place_order(intent)


async def test_bracket_missing_bracket_raises() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    intent = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1, order_type="BRACKET",
        client_order_id="br-no-br",
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
        limit_price=16_500.0,
    )
    with pytest.raises(ValueError, match="bracket"):
        await c.place_order(intent)
