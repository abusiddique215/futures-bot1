"""Cross-adapter conformance: identical OrderEvent sequence for the
`place_market_buy_then_fill` scenario across SimExecutionClient,
IBExecutionClient (mocked), and TopstepXExecutionClient (mocked).
Spec 02 §3.9.

What is asserted:
- All adapters return a PENDING OrderEvent on place_order with the same
  client_order_id, filled_quantity=0, avg_fill_price=None.
- broker_order_id values are NOT compared — by design they're
  adapter-specific (`sim-1` vs an IB orderId vs a TopstepX orderId).

A full FILLED-event comparison is deferred to a future plan that runs
the IB adapter against the IB Gateway's simulated executions; the sim
client emits FILLED via execute_fill which the IB adapter doesn't expose
(the broker reports fills via OrderEvent listeners).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.execution.ib_client import IBExecutionClient
from bot.execution.ports import ExecutionClient
from bot.execution.topstepx_client import TopstepXExecutionClient
from bot.types import OrderIntent
from tests.fakes.fake_ib import FakeIB
from tests.fakes.fake_projectx import FakeAccount, FakeProjectX


class _ConnectableExecutionClient(Protocol):
    async def connect(self) -> None: ...
    async def place_order(self, intent: OrderIntent) -> Any: ...


def _make_intent() -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=1, order_type="MARKET",
        client_order_id="cf-1",
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )


def _make_sim() -> _ConnectableExecutionClient:
    return SimExecutionClient()


def _make_ib() -> _ConnectableExecutionClient:
    fake = FakeIB()
    return IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                             ib_factory=lambda: fake)


def _make_topstepx() -> _ConnectableExecutionClient:
    """env='paper' skips the hostname guard; FakeProjectX skips the network."""
    fake = FakeProjectX(accounts=[FakeAccount(id=1, name="acct-A")])
    return TopstepXExecutionClient(
        username="u", api_key="k", account_name="acct-A",
        env="paper", client_factory=lambda: fake,
    )


@pytest.mark.parametrize(
    ("name", "factory"),
    [
        ("sim", _make_sim),
        ("ib_paper_mock", _make_ib),
        ("topstepx_mock", _make_topstepx),
    ],
)
async def test_place_market_buy_emits_consistent_pending_event(
    name: str,
    factory: Any,
) -> None:
    """Conformance: all three adapters emit a PENDING OrderEvent on
    place_order of a 1-lot MNQ MARKET BUY, with matching status /
    client_order_id / filled_quantity / avg_fill_price.
    """
    client = factory()
    await client.connect()
    intent = _make_intent()

    event = await client.place_order(intent)

    assert event.status == "PENDING", name
    assert event.client_order_id == intent.client_order_id, name
    assert event.filled_quantity == 0, name
    assert event.avg_fill_price is None, name
    assert event.broker_order_id  # not empty


def test_all_three_adapters_satisfy_execution_client_protocol() -> None:
    sim = SimExecutionClient()
    ib = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1)
    topstepx = TopstepXExecutionClient(
        username="u", api_key="k", account_name="acct",
        env="paper", client_factory=lambda: FakeProjectX(),
    )
    assert isinstance(sim, ExecutionClient)
    assert isinstance(ib, ExecutionClient)
    assert isinstance(topstepx, ExecutionClient)
