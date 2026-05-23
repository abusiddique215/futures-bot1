"""FakeIB — in-memory stand-in for ib_async.IB used across Plan 6 tests.

Implements the subset of the ib_async surface IBExecutionClient touches:
- connectAsync(host, port, clientId)
- disconnect()
- qualifyContractsAsync(contract) → returns the contract with conId set
- placeOrder(contract, order) → returns a Trade-shaped object
- cancelOrder(order) → marks order canceled
- bracketOrder(action, quantity, limitPrice, takeProfitPrice, stopLossPrice)
  — delegated to ib_async's real helper (no network) once client.getReqId works
- positions(), openOrders(), accountSummary() — return configurable lists
- disconnectedEvent — simple subscribe/emit hook
- reqRealTimeBars(contract, barSize, whatToShow, useRTH) — returns a list
  the test can push to via .append() while a consumer iterates.

Tests construct one of these and pass `ib_factory=lambda: my_fake` to the
adapter under test.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import count
from typing import Any


class _FakeClient:
    """ib.client.getReqId — used by ib.bracketOrder() to assign orderIds."""

    def __init__(self) -> None:
        self._counter = count(1000)

    def getReqId(self) -> int:
        return next(self._counter)


@dataclass
class _OrderStatus:
    status: str = "PendingSubmit"
    filled: float = 0.0
    avgFillPrice: float = 0.0


@dataclass
class _TradeShim:
    """Trade-shaped object returned by placeOrder; matches ib_async.order.Trade
    in the fields IBExecutionClient reads (contract, order, orderStatus)."""
    contract: Any
    order: Any
    orderStatus: _OrderStatus = field(default_factory=_OrderStatus)


class _Event:
    """Mimics ib_async.util.Event — supports += handler subscription + emit()."""

    def __init__(self) -> None:
        self._handlers: list[Callable[..., Any]] = []

    def __iadd__(self, handler: Callable[..., Any]) -> _Event:
        self._handlers.append(handler)
        return self

    def __isub__(self, handler: Callable[..., Any]) -> _Event:
        if handler in self._handlers:
            self._handlers.remove(handler)
        return self

    def emit(self, *args: Any, **kwargs: Any) -> None:
        for h in list(self._handlers):
            h(*args, **kwargs)


class FakeIB:
    """In-memory IB substitute. See module docstring."""

    def __init__(self) -> None:
        self.client = _FakeClient()
        self.connected = False
        self.connect_calls: list[tuple[str, int, int]] = []
        self.placed_orders: list[_TradeShim] = []
        self.canceled_order_ids: list[int] = []
        # Test-tunable fixture data:
        self._positions: list[Any] = []
        self._open_orders: list[Any] = []
        self._account_summary: list[Any] = []
        # Conduit for real-time bars produced by reqRealTimeBars.
        self.realtime_bars: list[Any] = []
        self._next_order_id = count(5000)
        self.disconnectedEvent = _Event()
        self.barUpdateEvent = _Event()

    # ---- connection -----------------------------------------------------

    async def connectAsync(
        self, host: str, port: int, clientId: int
    ) -> None:
        self.connect_calls.append((host, port, clientId))
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def isConnected(self) -> bool:
        return self.connected

    # ---- contract resolution --------------------------------------------

    async def qualifyContractsAsync(
        self, *contracts: Any
    ) -> list[Any]:
        # In ib_async this mutates conId on each contract; mimic that.
        for c in contracts:
            c.conId = 12345
        return list(contracts)

    # ---- orders ---------------------------------------------------------

    def placeOrder(self, contract: Any, order: Any) -> _TradeShim:
        if not hasattr(order, "orderId") or order.orderId == 0:
            order.orderId = next(self._next_order_id)
        trade = _TradeShim(contract=contract, order=order)
        self.placed_orders.append(trade)
        return trade

    def cancelOrder(self, order: Any) -> None:
        self.canceled_order_ids.append(order.orderId)

    def bracketOrder(
        self,
        action: str,
        quantity: float,
        limitPrice: float,
        takeProfitPrice: float,
        stopLossPrice: float,
    ) -> Any:
        # Delegate to ib_async's real implementation — it needs only
        # self.client.getReqId() (we provide).
        from ib_async import IB
        real_bracket: Callable[..., Any] = IB.bracketOrder
        return real_bracket(
            self, action, quantity, limitPrice, takeProfitPrice, stopLossPrice
        )

    # ---- snapshot queries ------------------------------------------------

    def positions(self, account: str = "") -> list[Any]:
        return list(self._positions)

    def openOrders(self) -> list[Any]:
        return list(self._open_orders)

    def accountSummary(self, account: str = "") -> list[Any]:
        return list(self._account_summary)

    # ---- real-time bars --------------------------------------------------

    def reqRealTimeBars(
        self,
        contract: Any,
        barSize: int,
        whatToShow: str,
        useRTH: bool,
    ) -> list[Any]:
        return self.realtime_bars
