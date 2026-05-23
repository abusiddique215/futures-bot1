"""SimExecutionClient — deterministic in-memory broker for backtest."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.execution.ports import ExecutionClient
from bot.types import OrderIntent


def _intent(client_order_id: str = "t-1") -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="MARKET", client_order_id=client_order_id,
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )


def test_sim_client_satisfies_execution_client_protocol() -> None:
    from bot.backtest.sim_client import SimExecutionClient
    sim = SimExecutionClient()
    assert isinstance(sim, ExecutionClient)


async def test_place_order_returns_pending_event() -> None:
    from bot.backtest.sim_client import SimExecutionClient
    sim = SimExecutionClient()
    event = await sim.place_order(_intent())
    assert event.status == "PENDING"
    assert event.client_order_id == "t-1"
    assert event.broker_order_id.startswith("sim-")
    assert event.filled_quantity == 0
    assert event.avg_fill_price is None


async def test_execute_fill_returns_filled_event_with_price() -> None:
    from bot.backtest.sim_client import SimExecutionClient
    sim = SimExecutionClient()
    intent = _intent()
    await sim.place_order(intent)
    fill_ts = datetime(2026, 5, 22, 14, 31, tzinfo=UTC)
    event = sim.execute_fill(intent, fill_price=16_500.25, ts=fill_ts)
    assert event.status == "FILLED"
    assert event.avg_fill_price == 16_500.25
    assert event.filled_quantity == intent.quantity
    assert event.timestamp == fill_ts


async def test_sequential_place_orders_get_unique_broker_ids() -> None:
    from bot.backtest.sim_client import SimExecutionClient
    sim = SimExecutionClient()
    e1 = await sim.place_order(_intent("t-1"))
    e2 = await sim.place_order(_intent("t-2"))
    e3 = await sim.place_order(_intent("t-3"))
    ids = {e1.broker_order_id, e2.broker_order_id, e3.broker_order_id}
    assert len(ids) == 3


async def test_execute_fill_unknown_intent_raises() -> None:
    """Fill must reference an intent that was previously placed."""
    from bot.backtest.sim_client import SimExecutionClient
    sim = SimExecutionClient()
    with pytest.raises(KeyError):
        sim.execute_fill(_intent("never-placed"),
                         fill_price=16_500.0,
                         ts=datetime(2026, 5, 22, 14, 31, tzinfo=UTC))
