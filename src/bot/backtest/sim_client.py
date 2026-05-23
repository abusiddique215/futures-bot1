"""SimExecutionClient — deterministic in-memory ExecutionClient for backtests.

Implements bot.execution.ports.ExecutionClient. `place_order` records the
intent and returns a PENDING OrderEvent; the engine subsequently calls the
sim-specific `execute_fill(intent, fill_price, ts)` to materialize a FILLED
event. This split is on purpose — the engine drives the bar clock and chooses
the fill price (bar.close in v1), so the sim only needs to be a deterministic
ledger of what was placed and what was filled.

Non-fill methods (connect, disconnect, cancel_*, get_*) are minimal stubs so
the protocol is satisfied for harness use; backtest doesn't exercise them.
"""
from __future__ import annotations

from datetime import UTC, datetime
from itertools import count

from bot.types import (
    AccountState,
    Order,
    OrderEvent,
    OrderIntent,
    Position,
)


class SimExecutionClient:
    """In-memory ExecutionClient backing the backtest engine."""

    def __init__(self) -> None:
        self._broker_id_counter = count(1)
        # client_order_id -> (intent, broker_order_id)
        self._placed: dict[str, tuple[OrderIntent, str]] = {}
        self._fills: list[OrderEvent] = []

    # ---- ExecutionClient protocol ----------------------------------------

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def place_order(self, intent: OrderIntent) -> OrderEvent:
        return self.register_intent(intent)

    def register_intent(self, intent: OrderIntent) -> OrderEvent:
        """Sync ledger registration. Called by async place_order AND by the
        sync BacktestEngine — same operation, different driver. Returns the
        PENDING OrderEvent (the async place_order awaits and returns the same)."""
        broker_order_id = f"sim-{next(self._broker_id_counter)}"
        self._placed[intent.client_order_id] = (intent, broker_order_id)
        return OrderEvent(
            client_order_id=intent.client_order_id,
            broker_order_id=broker_order_id,
            status="PENDING",
            filled_quantity=0,
            avg_fill_price=None,
            timestamp=intent.timestamp,
        )

    async def cancel_order(self, client_order_id: str) -> OrderEvent:
        intent, broker_order_id = self._placed[client_order_id]
        return OrderEvent(
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            status="CANCELED",
            filled_quantity=0,
            avg_fill_price=None,
            timestamp=intent.timestamp,
        )

    async def cancel_all(self, symbol: str) -> list[OrderEvent]:
        events: list[OrderEvent] = []
        for client_order_id, (intent, broker_order_id) in list(self._placed.items()):
            if intent.symbol != symbol:
                continue
            events.append(OrderEvent(
                client_order_id=client_order_id,
                broker_order_id=broker_order_id,
                status="CANCELED",
                filled_quantity=0,
                avg_fill_price=None,
                timestamp=intent.timestamp,
            ))
        return events

    async def get_positions(self) -> list[Position]:
        return []

    async def get_open_orders(self) -> list[Order]:
        return []

    async def get_account(self) -> AccountState:
        return AccountState(
            equity=0.0,
            realized_pnl_today=0.0,
            unrealized_pnl=0.0,
            open_positions={},
            pending_intent_count=len(self._placed),
            high_water_equity=0.0,
            is_combine=True,
            timestamp=datetime.fromtimestamp(0, tz=UTC),
        )

    # ---- Sim-specific (engine-driven) ------------------------------------

    def execute_fill(
        self, intent: OrderIntent, fill_price: float, ts: datetime,
    ) -> OrderEvent:
        """Materialize a fill for a previously-placed intent.

        Raises KeyError if the intent was not placed via place_order.
        Returns the FILLED OrderEvent for the engine to record.
        """
        _, broker_order_id = self._placed[intent.client_order_id]
        event = OrderEvent(
            client_order_id=intent.client_order_id,
            broker_order_id=broker_order_id,
            status="FILLED",
            filled_quantity=intent.quantity,
            avg_fill_price=fill_price,
            timestamp=ts,
        )
        self._fills.append(event)
        return event
