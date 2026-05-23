"""Tests for the ExecutionClient Protocol.

Spec: 02-execution-clients.md §3.1, §4 lines 307-316.

These tests verify the Protocol's method signatures exist and that a dummy
implementation satisfies it structurally. Real adapter conformance lives in
Plan 6 (IB) / Plan 8 (TopstepX) / Plan 4 (Sim) — this just nails down the seam.
"""
from __future__ import annotations

import pytest


def test_execution_client_protocol_importable() -> None:
    from bot.execution.ports import ExecutionClient
    assert ExecutionClient is not None


def test_execution_client_protocol_has_expected_methods() -> None:
    from bot.execution.ports import ExecutionClient
    expected = {
        "connect", "disconnect",
        "place_order", "cancel_order", "cancel_all",
        "get_positions", "get_open_orders", "get_account",
    }
    actual = {n for n in dir(ExecutionClient) if not n.startswith("_")}
    missing = expected - actual
    assert not missing, f"Protocol missing methods: {missing}"


@pytest.mark.asyncio
async def test_dummy_implementation_satisfies_protocol(utc_now) -> None:
    """A dummy class with matching async signatures satisfies the structural
    Protocol. This proves the Protocol is correctly shaped for Plan 4 / 6 / 8."""
    from bot.execution.ports import ExecutionClient
    from bot.types import (
        AccountState,
        Order,
        OrderEvent,
        OrderIntent,
        Position,
    )

    class _DummyClient:
        async def connect(self) -> None: ...
        async def disconnect(self) -> None: ...
        async def place_order(self, intent: OrderIntent) -> OrderEvent:
            return OrderEvent(
                client_order_id=intent.client_order_id,
                broker_order_id="b-x", status="PENDING",
                filled_quantity=0, avg_fill_price=None,
                timestamp=intent.timestamp,
            )
        async def cancel_order(self, client_order_id: str) -> OrderEvent:
            return OrderEvent(
                client_order_id=client_order_id, broker_order_id="b-x",
                status="CANCELED", filled_quantity=0, avg_fill_price=None,
                timestamp=utc_now,
            )
        async def cancel_all(self, symbol: str) -> list[OrderEvent]:
            return []
        async def get_positions(self) -> list[Position]: return []
        async def get_open_orders(self) -> list[Order]: return []
        async def get_account(self) -> AccountState:
            return AccountState(
                equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
                open_positions={}, pending_intent_count=0,
                high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
            )

    client: ExecutionClient = _DummyClient()  # structural conformance check
    assert (await client.get_account()).equity == 50_000.0
