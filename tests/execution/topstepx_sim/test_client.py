"""TopstepXSimClient — ExecutionClient Protocol implementation tests (Plan 11 T3)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.execution.ports import ExecutionClient
from bot.execution.topstepx_sim.account import SimAccount
from bot.execution.topstepx_sim.client import TopstepXSimClient
from bot.execution.topstepx_sim.engine import TopstepSimEngine
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.types import OrderIntent


def _make_engine() -> TopstepSimEngine:
    return TopstepSimEngine(
        account=SimAccount.new(start_balance=50_000.0, mll_amount=2_000.0),
        combine_policy=CombineIntradayDrawdown(50_000.0, 2_000.0, max_mini=5),
        efa_policy=None,
        now=lambda: datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )


def _make_client(
    engine: TopstepSimEngine,
    mid: float = 18_000.0,
) -> TopstepXSimClient:
    async def mid_source(symbol: str) -> float:
        return mid
    return TopstepXSimClient(engine=engine, mid_price_source=mid_source)


def _intent(side: str = "BUY", qty: int = 1, coid: str = "o-1") -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side=side, quantity=qty,  # type: ignore[arg-type]
        order_type="MARKET", client_order_id=coid,
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )


async def test_connect_and_disconnect_are_no_ops() -> None:
    client = _make_client(_make_engine())
    await client.connect()
    await client.disconnect()


async def test_place_order_round_trips_filled_event() -> None:
    client = _make_client(_make_engine())
    await client.connect()
    ev = await client.place_order(_intent())
    assert ev.status == "FILLED"
    assert ev.avg_fill_price == pytest.approx(18_000.0)
    assert ev.filled_quantity == 1
    assert ev.client_order_id == "o-1"


async def test_get_positions_reflects_post_fill_state() -> None:
    client = _make_client(_make_engine())
    await client.connect()
    await client.place_order(_intent())
    positions = await client.get_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.symbol == "MNQ"
    assert pos.signed_qty == 1
    assert pos.avg_entry_price == pytest.approx(18_000.0)


async def test_get_open_orders_is_empty_for_immediate_fill_engine() -> None:
    client = _make_client(_make_engine())
    await client.connect()
    await client.place_order(_intent())
    open_orders = await client.get_open_orders()
    assert open_orders == []


async def test_cancel_order_returns_rejected_too_late() -> None:
    client = _make_client(_make_engine())
    await client.connect()
    ev = await client.cancel_order("o-1")
    assert ev.status == "REJECTED"


async def test_cancel_all_returns_empty_when_no_orders() -> None:
    client = _make_client(_make_engine())
    await client.connect()
    out = await client.cancel_all("MNQ")
    assert out == []


async def test_get_account_returns_account_state_with_correct_equity() -> None:
    engine = _make_engine()
    client = _make_client(engine, mid=18_000.0)
    await client.connect()
    await client.place_order(_intent())
    # Tick the engine forward with a new mid → unrealized P&L appears.
    engine.tick(mid_price=18_005.0, symbol="MNQ")
    state = await client.get_account()
    # 5 pts * $2/pt = $10 unrealized → equity = 50_010
    assert state.equity == pytest.approx(50_010.0)
    assert state.open_positions == {"MNQ": 1}
    assert state.is_combine is True
    assert state.start_balance == 50_000.0


def test_client_satisfies_execution_client_protocol() -> None:
    client = _make_client(_make_engine())
    # Runtime isinstance check; assignment to a typed var exercises mypy too.
    assert isinstance(client, ExecutionClient)
    typed: ExecutionClient = client
    assert typed is client
