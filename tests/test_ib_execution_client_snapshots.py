"""IBExecutionClient — get_positions / get_open_orders / get_account snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bot.execution.ib_client import IBExecutionClient
from tests.fakes.fake_ib import FakeIB


@dataclass
class _FakeContract:
    symbol: str


@dataclass
class _FakePos:
    account: str
    contract: Any
    position: float
    avgCost: float


@dataclass
class _FakeOrder:
    orderId: int
    action: str
    totalQuantity: float
    orderType: str
    orderRef: str
    lmtPrice: float = 0.0
    auxPrice: float = 0.0


@dataclass
class _FakeAccountVal:
    account: str
    tag: str
    value: str
    currency: str = "USD"
    modelCode: str = ""


# ---------- positions ---------------------------------------------------------

async def test_get_positions_converts_ib_positions_to_bot_positions() -> None:
    fake = FakeIB()
    fake._positions = [
        _FakePos(account="DU1", contract=_FakeContract(symbol="MNQ"),
                 position=2.0, avgCost=16_400.5),
        _FakePos(account="DU1", contract=_FakeContract(symbol="NQ"),
                 position=-1.0, avgCost=16_410.0),
    ]
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    positions = await c.get_positions()

    assert len(positions) == 2
    p_mnq = next(p for p in positions if p.symbol == "MNQ")
    assert p_mnq.signed_qty == 2
    assert p_mnq.avg_entry_price == 16_400.5
    p_nq = next(p for p in positions if p.symbol == "NQ")
    assert p_nq.signed_qty == -1


async def test_get_positions_empty_when_no_positions() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    assert await c.get_positions() == []


# ---------- open orders -------------------------------------------------------

async def test_get_open_orders_converts_ib_orders() -> None:
    fake = FakeIB()
    fake._open_orders = [
        _FakeOrder(orderId=5001, action="BUY", totalQuantity=1,
                   orderType="MKT", orderRef="ord-1"),
        _FakeOrder(orderId=5002, action="SELL", totalQuantity=2,
                   orderType="LMT", orderRef="ord-2", lmtPrice=16_510.0),
    ]
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    orders = await c.get_open_orders()

    assert len(orders) == 2
    o1 = next(o for o in orders if o.client_order_id == "ord-1")
    assert o1.broker_order_id == "5001"
    assert o1.side == "BUY"
    assert o1.quantity == 1
    assert o1.order_type == "MARKET"  # converted from IB "MKT"
    o2 = next(o for o in orders if o.client_order_id == "ord-2")
    assert o2.side == "SELL"
    assert o2.quantity == 2
    assert o2.order_type == "LIMIT"  # converted from IB "LMT"
    assert o2.limit_price == 16_510.0


# ---------- account ----------------------------------------------------------

async def test_get_account_aggregates_summary_tags() -> None:
    fake = FakeIB()
    fake._account_summary = [
        _FakeAccountVal(account="DU1", tag="NetLiquidation", value="52341.56"),
        _FakeAccountVal(account="DU1", tag="RealizedPnL", value="120.00"),
        _FakeAccountVal(account="DU1", tag="UnrealizedPnL", value="-45.50"),
    ]
    fake._positions = [
        _FakePos(account="DU1", contract=_FakeContract(symbol="MNQ"),
                 position=1.0, avgCost=16_400.0),
    ]
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    state = await c.get_account()

    assert state.equity == 52_341.56
    assert state.realized_pnl_today == 120.00
    assert state.unrealized_pnl == -45.50
    assert state.open_positions == {"MNQ": 1}
    assert state.timestamp.tzinfo is not None  # UTC tz-aware
    # high_water_equity defaults to current equity until the engine tracks it.
    assert state.high_water_equity == 52_341.56


async def test_get_account_defaults_to_zero_when_tag_missing() -> None:
    fake = FakeIB()
    fake._account_summary = []  # gateway returned nothing — first connect
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    state = await c.get_account()

    assert state.equity == 0.0
    assert state.realized_pnl_today == 0.0
    assert state.unrealized_pnl == 0.0
    assert state.open_positions == {}
    assert state.timestamp.tzinfo == UTC
    # sanity: timestamp is reasonable (within a minute of now)
    delta = abs((state.timestamp - datetime.now(UTC)).total_seconds())
    assert delta < 60
