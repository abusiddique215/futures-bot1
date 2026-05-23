"""FakeProjectX — in-memory stand-in for project_x_py used across Plan 8 tests.

Mirrors the subset of the project_x_py surface that TopstepXExecutionClient
touches:
  - async authenticate()
  - async list_accounts() -> list of accounts with .id and .name
  - async create_suite-equivalent: a fake TradingSuite with
      .orders.place_order(...)
      .orders.cancel_order(...)
      .orders.cancel_all_orders(...)
      .positions / .orders snapshot helpers
      .on(event, handler) / .events.on(...)
      .disconnect()
  - JWT pre-refresh hook: re-authenticate() can be triggered manually.

Tests instantiate FakeProjectX(), configure list_accounts() return + place_order
return, and pass `client_factory=lambda: fake` to TopstepXExecutionClient.

The fake captures every call into typed lists so tests can assert on
the exact wire-body dict the adapter would have sent.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeAccount:
    """Mirrors project_x_py.Account in the fields we read."""
    id: int
    name: str
    balance: float = 50_000.0


@dataclass
class FakeOrderPlaceResponse:
    """Mirrors project_x_py.OrderPlaceResponse."""
    orderId: int
    success: bool = True
    errorCode: int = 0
    errorMessage: str | None = None


@dataclass
class FakeOrderSnapshot:
    """Mirrors a row in suite.orders.search_open_orders / similar."""
    id: int
    contractId: str
    side: int
    size: int
    type: int
    status: int = 1  # 1 == WORKING
    limitPrice: float | None = None
    stopPrice: float | None = None
    customTag: str = ""


@dataclass
class FakePositionSnapshot:
    contractId: str
    size: int       # signed
    averagePrice: float
    unrealizedPnl: float = 0.0


class FakeOrders:
    """The .orders attribute on a fake TradingSuite."""

    def __init__(self, parent: FakeProjectX) -> None:
        self._parent = parent
        # Each placed_bodies entry is the exact kwargs dict the adapter passed.
        self.placed_bodies: list[dict[str, Any]] = []
        self.canceled_ids: list[int] = []
        self.cancel_all_calls: list[str | None] = []
        self._next_order_id = 9000
        self._open_orders: list[FakeOrderSnapshot] = []

    async def place_order(self, **kwargs: Any) -> FakeOrderPlaceResponse:
        self.placed_bodies.append(dict(kwargs))
        if self._parent.next_place_response is not None:
            resp = self._parent.next_place_response
            # Don't reuse; reset to default for the next call.
            self._parent.next_place_response = None
            return resp
        self._next_order_id += 1
        return FakeOrderPlaceResponse(orderId=self._next_order_id)

    async def cancel_order(self, order_id: int, account_id: int | None = None) -> bool:
        self.canceled_ids.append(order_id)
        return True

    async def cancel_all_orders(
        self,
        contract_id: str | None = None,
        account_id: int | None = None,
    ) -> dict[str, Any]:
        self.cancel_all_calls.append(contract_id)
        return {"canceled": len(self._open_orders)}

    async def search_open_orders(self) -> list[FakeOrderSnapshot]:
        return list(self._open_orders)


class FakePositions:
    def __init__(self) -> None:
        self._positions: list[FakePositionSnapshot] = []

    async def get_all_positions(self) -> list[FakePositionSnapshot]:
        return list(self._positions)


class FakeSuite:
    """The TradingSuite-shaped object."""

    def __init__(self, parent: FakeProjectX, symbol: str) -> None:
        self._parent = parent
        self.symbol = symbol
        self.instrument_id = f"CON.F.US.{symbol}.M26"
        self.orders = FakeOrders(parent)
        self.positions = FakePositions()
        self.event_handlers: dict[str, list[Callable[..., Any]]] = {}
        self.disconnect_calls = 0
        self._connected = True

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        self.event_handlers.setdefault(event, []).append(handler)

    async def emit(self, event: str, *args: Any, **kwargs: Any) -> None:
        for h in list(self.event_handlers.get(event, [])):
            await h(*args, **kwargs)

    def is_connected(self) -> bool:
        return self._connected

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False


@dataclass
class FakeProjectX:
    """The ProjectX-shaped client. Pass as client_factory=lambda: fake."""

    # Configurable: list_accounts() returns this.
    accounts: list[FakeAccount] = field(default_factory=lambda: [
        FakeAccount(id=1, name="default"),
    ])
    # If non-None, next place_order returns this then resets to None.
    next_place_response: FakeOrderPlaceResponse | None = None
    # If non-None, authenticate() raises this.
    authenticate_error: Exception | None = None
    # If non-None, TradingSuite.create raises this.
    create_suite_error: Exception | None = None

    # Captured state:
    authenticate_calls: int = 0
    suite: FakeSuite | None = None

    async def authenticate(self) -> None:
        self.authenticate_calls += 1
        if self.authenticate_error is not None:
            raise self.authenticate_error

    async def list_accounts(self) -> list[FakeAccount]:
        return list(self.accounts)

    # The real SDK exposes this as a classmethod on TradingSuite; for the fake
    # we put it on the client so client_factory can hand back a single object
    # whose .create_suite() method the adapter calls. The adapter is free to
    # bridge from the real classmethod surface to this shape.
    async def create_suite(
        self, symbol: str, account_id: int | None = None,
    ) -> FakeSuite:
        if self.create_suite_error is not None:
            raise self.create_suite_error
        self.suite = FakeSuite(self, symbol)
        return self.suite
