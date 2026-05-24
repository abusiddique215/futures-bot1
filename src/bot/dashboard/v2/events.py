"""Pydantic v2 event models for the WebSocket bridge.

Canonical telemetry kinds (documented here, consistent across emitters):

  bar_tick          — per-bar OHLCV + bot identity
  account_update    — per-bar account state including derived distance fields
  bot_intent        — per-bar "what is the bot watching for now" summary
  fill              — broker order event (FILLED only by convention)
  risk_decision     — risk gate approve / deny
  bot_state_change  — bot lifecycle transition (DISABLED / ARMED_WAITING / IN_TRADE)

Every emitter on the TelemetryBus is expected to publish one of these
kinds with a payload shaped to the corresponding model. WebSocketBroadcaster
serializes the wrapped envelope (kind + payload) as JSON.

These models are intentionally lenient (extra = allow) so the engine can
evolve emit payloads without breaking the broadcaster contract; the
dashboard renders unknown extra fields verbatim or ignores them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

EventKind = Literal[
    "bar_tick",
    "account_update",
    "bot_intent",
    "fill",
    "risk_decision",
    "bot_state_change",
]

BotState = Literal["DISABLED", "ARMED_WAITING", "IN_TRADE", "LOCKED"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class BarPayload(_Base):
    ts: datetime
    o: float
    h: float
    low: float
    c: float
    v: int


class BarTickEvent(_Base):
    """Per-bar OHLCV emitted on every bar across every bot."""
    bot: str
    symbol: str
    bar: BarPayload


class AccountUpdateEvent(_Base):
    """Per-bar account snapshot with derived distance fields.

    `distance_to_target` is None for non-Combine policies (no fixed target).
    `dll_remaining` is the DLL headroom = $1000 - max(0, -realized_pnl_today).
    """
    bot: str
    state: BotState
    equity: float
    balance: float
    realized_pnl_today: float
    unrealized_pnl: float
    high_water: float
    distance_to_mll: float
    distance_to_target: float | None
    contracts_open: int
    dll_remaining: float


class BotIntentEvent(_Base):
    """Trader-facing 'what is the bot watching for' summary."""
    bot: str
    watching_for: str
    schedule_open: bool
    next_window_opens_in_seconds: int | None
    max_trades_remaining: int | None


class FillEvent(_Base):
    bot: str
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: int
    fill_price: float
    timestamp: datetime
    client_order_id: str


class RiskDecisionEvent(_Base):
    bot: str
    approved: bool
    rule: str | None
    reason: str | None
    timestamp: datetime


class BotStateChangeEvent(_Base):
    bot: str
    from_state: BotState
    to_state: BotState
    reason: str
    timestamp: datetime
