"""Canonical cross-cutting dataclasses for the futures bot.

This module is intentionally a single file: the dataclasses below are referenced
by both bot.execution and bot.risk subpackages, and splitting them by domain
would create circular imports. Keep it under ~500 lines; split later if it grows.

Spec sources:
- 00-architecture-overview.md  : locked decisions, rule constants references
- 01-data-pipeline.md §3.5, §4 : Bar / Tick
- 02-execution-clients.md §4   : Bracket, OrderIntent (+ helpers), OrderEvent, Position
- 04-risk-engine.md §4.1       : AccountState, OrderDenied, ApprovedOrder
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

# ---- Data pipeline (spec 01) -------------------------------------------------

@dataclass(frozen=True)
class Bar:
    """Closed OHLCV bar. timestamp is the bar's OPEN time, tz-aware UTC.

    See spec 01 §3.4 (closed-bar semantics) and §3.5 (timezone discipline).
    """
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: datetime
    interval: str  # "1m", "5m"

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise TypeError("Bar.timestamp must be timezone-aware")


@dataclass(frozen=True)
class Tick:
    """Single trade or quote tick. timestamp must be tz-aware."""
    symbol: str
    price: float
    size: int
    timestamp: datetime

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise TypeError("Tick.timestamp must be timezone-aware")



# ---- Execution (spec 02) -----------------------------------------------------

Side = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "BRACKET"]


@dataclass(frozen=True)
class Bracket:
    """Tick-offset stop and take-profit attached to a parent order.

    Tick offsets are broker-agnostic. The ExecutionClient adapter converts
    ticks to absolute prices (IB) or sends ticks directly (TopstepX).
    See spec 02 §3.5 bracket-translation table.
    """
    stop_loss_ticks: int
    take_profit_ticks: int


@dataclass(frozen=True)
class OrderIntent:
    """Broker-agnostic order request emitted by Strategy → RiskGate → ExecutionClient.

    The Strategy never holds a broker reference; the only path to a broker order
    is by emitting an OrderIntent. Helper methods (signed_qty, etc.) are added
    in the next task.
    """
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    client_order_id: str
    timestamp: datetime
    limit_price: float | None = None
    stop_price: float | None = None
    bracket: Bracket | None = None

    # ---- Helper methods called by 04-risk-engine (spec 02 §4 lines 259-283) ----

    def signed_qty(self) -> int:
        """+quantity for BUY, -quantity for SELL. Used by rule 4 (max position)."""
        return self.quantity if self.side == "BUY" else -self.quantity

    def is_open_increasing_exposure(self, open_positions: dict[str, int]) -> bool:
        """True iff applying this intent would grow |position| on this symbol.

        A pure reducing/flattening order returns False. A flip (sell more than
        long) returns True — the resulting |short| is larger than original |long|.
        Used by rule 1 (hard-flat) — closes are always allowed after 15:00 CT.
        """
        current = open_positions.get(self.symbol, 0)
        projected = current + self.signed_qty()
        return abs(projected) > abs(current)

    def is_market_or_limit_open(self) -> bool:
        """True iff this intent opens (or modifies) exposure.

        Strategies emit only MARKET / LIMIT / BRACKET intents; STOP / STOP_LIMIT
        arrive only as bracket children submitted by the adapter. Used by
        rule 2 sub-check (STOP_REQUIRED).
        """
        return self.order_type in ("MARKET", "LIMIT", "BRACKET")

    def with_stop(self, ticks: int) -> OrderIntent:
        """Return a NEW OrderIntent with bracket.stop_loss_ticks replaced.

        Used by rule 3 + §3.6 stop-offset safety buffer augmentation in 04.
        Raises ValueError if called on an intent that has no bracket.
        """
        if self.bracket is None:
            raise ValueError("with_stop() called on intent without a bracket")
        new_bracket = replace(self.bracket, stop_loss_ticks=ticks)
        return replace(self, bracket=new_bracket)


OrderStatus = Literal[
    "PENDING", "WORKING", "PARTIAL_FILL", "FILLED", "CANCELED", "REJECTED",
]


@dataclass(frozen=True)
class Position:
    """Broker-reported position snapshot. See spec 02 §4 line 285."""
    symbol: str
    signed_qty: int              # +long, -short
    avg_entry_price: float
    unrealized_pnl: float
    opened_at: datetime


@dataclass(frozen=True)
class Order:
    """Broker-reported open-order snapshot. Returned by ExecutionClient.get_open_orders()."""
    client_order_id: str
    broker_order_id: str
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    status: OrderStatus
    timestamp: datetime
    limit_price: float | None = None
    stop_price: float | None = None


@dataclass(frozen=True)
class OrderEvent:
    """State transition emitted by ExecutionClient on every order update.

    The Strategy / RiskGate consume these via the engine's event bus; metadata
    holds broker-specific error codes (e.g. TopstepX errorCode on REJECTED).
    """
    client_order_id: str
    broker_order_id: str
    status: OrderStatus
    filled_quantity: int
    avg_fill_price: float | None
    timestamp: datetime
    metadata: dict[str, object] | None = None
