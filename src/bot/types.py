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

from dataclasses import dataclass
from datetime import datetime

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
