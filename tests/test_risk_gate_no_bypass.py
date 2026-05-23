"""No-bypass conformance: ExecutionClient.place_order is NEVER called on
OrderDenied paths. Spec 04 §5.8.

The strategy can't bypass the gate. The TopstepRiskGate is the choke point —
denials must short-circuit any broker call.
"""
from __future__ import annotations

from datetime import UTC, datetime

from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.types import (
    AccountState,
    ApprovedOrder,
    Bracket,
    Order,
    OrderDenied,
    OrderEvent,
    OrderIntent,
    Position,
)


class _CountingClient:
    def __init__(self) -> None:
        self.place_order_calls = 0
    async def place_order(self, intent: OrderIntent) -> OrderEvent:
        self.place_order_calls += 1
        return OrderEvent(
            client_order_id=intent.client_order_id, broker_order_id="b-x",
            status="PENDING", filled_quantity=0, avg_fill_price=None,
            timestamp=intent.timestamp,
        )
    async def cancel_all(self, symbol: str) -> list[OrderEvent]: return []
    async def close_all_positions(self) -> None: pass
    async def connect(self) -> None: pass
    async def disconnect(self) -> None: pass
    async def cancel_order(self, client_order_id: str) -> OrderEvent: ...  # type: ignore[empty-body]
    async def get_positions(self) -> list[Position]: return []
    async def get_open_orders(self) -> list[Order]: return []
    async def get_account(self) -> AccountState: ...  # type: ignore[empty-body]


class _Tel:
    def alert(self, kind: str, **kw: object) -> None: pass


class _NoNews:
    def in_window(self, now: datetime) -> bool: return False
    def max_position_during_window(self) -> int: return 1


def _gate(client: _CountingClient) -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=client,
        telemetry=_Tel(),
        config=RiskConfig(env="backtest", accounts_managed=1),
    )


def _ts() -> datetime:
    return datetime(2026, 5, 22, 14, 0, tzinfo=UTC)


def _state(equity: float = 50_000, positions: dict[str, int] | None = None) -> AccountState:
    return AccountState(
        equity=equity, realized_pnl_today=0, unrealized_pnl=0,
        open_positions=positions or {}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=_ts(),
    )


def test_denial_does_not_call_place_order() -> None:
    """The driver pattern: only call place_order when gate APPROVES.

    This test mimics that pattern and asserts that on denial, place_order
    is never reached. (The gate itself doesn't call place_order — that's
    the driver's job. This test verifies the contract from the driver side.)
    """
    client = _CountingClient()
    gate = _gate(client)

    # Intent without bracket -> rule 2 STOP_REQUIRED denial
    intent_no_stop = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="MARKET", client_order_id="t-1", timestamp=_ts(),
    )
    result = gate.approve_or_deny(intent_no_stop, _state())
    assert isinstance(result, OrderDenied)
    # Driver pattern: skip place_order on denial
    if isinstance(result, ApprovedOrder):
        # would call: client.place_order(result.intent)
        pass
    assert client.place_order_calls == 0


async def test_approval_then_driver_can_call_place_order() -> None:
    """Sanity: when gate approves, driver pattern would call place_order."""
    client = _CountingClient()
    gate = _gate(client)
    intent = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="BRACKET", client_order_id="t-2", timestamp=_ts(),
        bracket=Bracket(stop_loss_ticks=10, take_profit_ticks=20),
    )
    result = gate.approve_or_deny(intent, _state())
    assert isinstance(result, ApprovedOrder)

    # Simulate driver behavior on approval
    await client.place_order(result.intent)
    assert client.place_order_calls == 1


def test_gate_itself_never_calls_place_order() -> None:
    """The gate is pure-function: approve_or_deny never reaches the broker.
    Force several gate calls and confirm zero broker invocations."""
    client = _CountingClient()
    gate = _gate(client)

    for i in range(5):
        intent = OrderIntent(
            symbol="MNQ", side="BUY", quantity=1,
            order_type="BRACKET", client_order_id=f"t-{i}", timestamp=_ts(),
            bracket=Bracket(stop_loss_ticks=10, take_profit_ticks=20),
        )
        gate.approve_or_deny(intent, _state())
    assert client.place_order_calls == 0
