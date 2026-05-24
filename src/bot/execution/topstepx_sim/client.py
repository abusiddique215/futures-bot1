"""TopstepXSimClient — ExecutionClient Protocol over a TopstepSimEngine.

Drop-in replacement for `TopstepXExecutionClient` in tests + scenario runs:
- Same async surface (connect/place_order/cancel_*/get_*).
- Same OrderEvent shape (FILLED / REJECTED).
- Same AccountState projection from `get_account()`.

The client holds an injected async mid-price source so tests can plug in a
synthetic series; production-style usage (scenario runner) wires it to the
SimBarSource's most recent bar close.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from bot.execution.topstepx_sim.engine import TopstepSimEngine
from bot.types import (
    AccountState,
    Order,
    OrderEvent,
    OrderIntent,
    Position,
)

MidPriceSource = Callable[[str], Awaitable[float]]


class TopstepXSimClient:
    """ExecutionClient backed by a TopstepSimEngine. Sim of the live adapter."""

    def __init__(
        self,
        *,
        engine: TopstepSimEngine,
        mid_price_source: MidPriceSource,
    ) -> None:
        self._engine = engine
        self._mid = mid_price_source

    # ---- ExecutionClient protocol --------------------------------------

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def place_order(self, intent: OrderIntent) -> OrderEvent:
        mid = await self._mid(intent.symbol)
        return self._engine.submit_order(intent, mid)

    async def cancel_order(self, client_order_id: str) -> OrderEvent:
        return self._engine.cancel_order(client_order_id)

    async def cancel_all(self, symbol: str) -> list[OrderEvent]:
        # The engine fills instantly; no working orders to cancel.
        return []

    async def get_positions(self) -> list[Position]:
        account = self._engine.account
        ts = self._engine.now()
        out: list[Position] = []
        for symbol, (signed_qty, avg_entry) in account.open_positions.items():
            mark = account.last_mark.get(symbol, avg_entry)
            unrealized = self._unrealized_for(symbol, signed_qty, avg_entry, mark)
            out.append(Position(
                symbol=symbol,
                signed_qty=signed_qty,
                avg_entry_price=avg_entry,
                unrealized_pnl=unrealized,
                opened_at=ts,
            ))
        return out

    async def get_open_orders(self) -> list[Order]:
        return []

    async def get_account(self) -> AccountState:
        return self._engine.as_account_state()

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _unrealized_for(
        symbol: str, signed_qty: int, avg_entry: float, mark: float,
    ) -> float:
        from bot.constants import MIN_TICK, TICK_VALUES

        point_value = TICK_VALUES[symbol] / MIN_TICK[symbol]
        return (mark - avg_entry) * signed_qty * point_value

    # ---- read-only state for tests -------------------------------------

    @property
    def engine(self) -> TopstepSimEngine:
        return self._engine

    @property
    def now(self) -> datetime:
        return self._engine.now()
