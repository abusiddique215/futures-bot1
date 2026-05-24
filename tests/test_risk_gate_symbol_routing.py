"""Verify TopstepRiskGate force_flatten_now routes cancel_all to its bound symbol.

Pre-Plan-12 the gate hardcoded symbol="MNQ" — a Gold Bot (GC) or ES Scalper (ES)
would have silently failed to cancel its own working orders. This regression test
locks in the fix.
"""
from __future__ import annotations

from typing import Any

import pytest

from bot.execution.ports import ExecutionClient
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.types import Order, OrderEvent, Position


class _NoopNews:
    def in_window(self, now: Any) -> bool:
        return False

    def max_position_during_window(self) -> int:
        return 0


class _RecordingClient:
    def __init__(self) -> None:
        self.cancel_all_calls: list[str] = []

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def place_order(self, intent: Any) -> OrderEvent: raise NotImplementedError
    async def cancel_order(self, client_order_id: str) -> OrderEvent: raise NotImplementedError
    async def cancel_all(self, symbol: str) -> list[OrderEvent]:
        self.cancel_all_calls.append(symbol)
        return []
    async def get_positions(self) -> list[Position]: return []
    async def get_open_orders(self) -> list[Order]: return []


def _gate(symbol: str, client: ExecutionClient) -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5),
        news_calendar=_NoopNews(),
        execution_client=client,
        config=RiskConfig(env="backtest", accounts_managed=1),
        symbol=symbol,
    )


@pytest.mark.asyncio
async def test_force_flatten_uses_bound_symbol_mnq() -> None:
    client = _RecordingClient()
    gate = _gate("MNQ", client)
    await gate.force_flatten_now(reason="TEST")
    assert client.cancel_all_calls == ["MNQ"]


@pytest.mark.asyncio
async def test_force_flatten_uses_bound_symbol_mgc() -> None:
    client = _RecordingClient()
    gate = _gate("MGC", client)
    await gate.force_flatten_now(reason="TEST")
    assert client.cancel_all_calls == ["MGC"]


@pytest.mark.asyncio
async def test_force_flatten_uses_bound_symbol_es() -> None:
    client = _RecordingClient()
    gate = _gate("ES", client)
    await gate.force_flatten_now(reason="TEST")
    assert client.cancel_all_calls == ["ES"]


def test_default_symbol_is_mnq() -> None:
    client = _RecordingClient()
    gate = TopstepRiskGate(
        policy=CombineIntradayDrawdown(start_balance=50_000, mll_amount=2_000, max_mini=5),
        news_calendar=_NoopNews(),
        execution_client=client,
        config=RiskConfig(env="backtest", accounts_managed=1),
    )
    assert gate.symbol == "MNQ"
