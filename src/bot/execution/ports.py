"""ExecutionClient port (Protocol).

The single seam between strategy/risk-gate and broker wire formats. Three
concrete implementations live in sibling plans:
  - Plan 4 : SimExecutionClient (deterministic, in-memory)
  - Plan 6 : IBExecutionClient (paper rail via ib_async)
  - Plan 8 : TopstepXExecutionClient (live rail via project-x-py)

Spec: 02-execution-clients.md §3.1, §4 lines 307-316.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bot.types import (
    AccountState,
    Order,
    OrderEvent,
    OrderIntent,
    Position,
)


@runtime_checkable
class ExecutionClient(Protocol):
    """Broker-agnostic execution port. All methods async.

    Idempotency: `place_order` is idempotent on `intent.client_order_id` —
    the adapter dedupes on a recent-submissions cache plus the broker's
    own dedup key (IB orderRef, TopstepX customTag). See spec 02 §3.8.
    """

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def place_order(self, intent: OrderIntent) -> OrderEvent: ...

    async def cancel_order(self, client_order_id: str) -> OrderEvent: ...

    async def cancel_all(self, symbol: str) -> list[OrderEvent]: ...

    async def get_positions(self) -> list[Position]: ...

    async def get_open_orders(self) -> list[Order]: ...

    async def get_account(self) -> AccountState: ...
