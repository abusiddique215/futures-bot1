"""TopstepRiskGate.on_tick + force_flatten + STRATEGY_DISABLED latch.

Spec 04 §3.4 (state machine) + §3.5 (force-flatten triggers + idempotency).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.types import (
    AccountState,
    Bracket,
    Order,
    OrderDenied,
    OrderEvent,
    OrderIntent,
    Position,
)


class _TrackingClient:
    """Records calls to cancel_all + close_all_positions."""
    def __init__(self) -> None:
        self.cancel_all_calls = 0
        self.close_all_calls = 0
    async def cancel_all(self, symbol: str) -> list[OrderEvent]:
        self.cancel_all_calls += 1
        return []
    async def close_all_positions(self) -> None:
        self.close_all_calls += 1
    async def connect(self) -> None: pass
    async def disconnect(self) -> None: pass
    async def place_order(self, intent: OrderIntent) -> OrderEvent: ...  # type: ignore[empty-body]
    async def cancel_order(self, client_order_id: str) -> OrderEvent: ...  # type: ignore[empty-body]
    async def get_positions(self) -> list[Position]: return []
    async def get_open_orders(self) -> list[Order]: return []
    async def get_account(self) -> AccountState: ...  # type: ignore[empty-body]


class _Tel:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, dict[str, object]]] = []
    def alert(self, kind: str, **kw: object) -> None:
        self.alerts.append((kind, kw))


class _NoNews:
    def in_window(self, now: datetime) -> bool: return False
    def max_position_during_window(self) -> int: return 1


def _gate(client: _TrackingClient | None = None) -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=client if client is not None else _TrackingClient(),
        telemetry=_Tel(),
        config=RiskConfig(env="backtest", accounts_managed=1),
    )


def _ts() -> datetime:
    return datetime(2026, 5, 22, 14, 0, tzinfo=UTC)


def _state(equity: float, hw: float | None = None,
           positions: dict[str, int] | None = None) -> AccountState:
    return AccountState(
        equity=equity, realized_pnl_today=0, unrealized_pnl=0,
        open_positions=positions or {}, pending_intent_count=0,
        high_water_equity=hw if hw is not None else equity, is_combine=True,
        timestamp=_ts(),
    )


# ---- on_tick state-machine tests --------------------------------------------

def test_on_tick_ratchets_high_water_on_up_move() -> None:
    gate = _gate()
    s = _state(equity=51_000, hw=50_000)
    s2 = gate.on_tick(s)
    assert s2.high_water_equity == 51_000


def test_on_tick_high_water_does_not_drop() -> None:
    gate = _gate()
    s = _state(equity=50_500, hw=51_000)
    s2 = gate.on_tick(s)
    assert s2.high_water_equity == 51_000  # one-way ratchet


def test_on_tick_below_phantom_schedules_force_flatten() -> None:
    """equity (47_500) < phantom (48_000 = hw - MLL) -> schedule flatten."""
    client = _TrackingClient()
    gate = _gate(client=client)
    gate.on_tick(_state(equity=47_500, hw=50_000, positions={"MNQ": 1}))
    # Flatten is scheduled; need to drain.
    asyncio.run(gate.force_flatten_now())
    assert client.cancel_all_calls >= 1
    assert client.close_all_calls >= 1


def test_on_tick_above_phantom_does_not_schedule_flatten() -> None:
    client = _TrackingClient()
    gate = _gate(client=client)
    gate.on_tick(_state(equity=51_000, hw=51_000))
    asyncio.run(gate.force_flatten_now())  # no-op
    assert client.cancel_all_calls == 0


# ---- force_flatten idempotency + STRATEGY_DISABLED latch -------------------

def test_force_flatten_idempotent_second_schedule_is_noop() -> None:
    """Two equity-touches in quick succession -> only one flatten executes."""
    client = _TrackingClient()
    gate = _gate(client=client)
    gate.on_tick(_state(equity=47_500, hw=50_000))
    gate.on_tick(_state(equity=47_000, hw=50_000))  # still below; redundant
    asyncio.run(gate.force_flatten_now())
    assert client.cancel_all_calls == 1
    assert client.close_all_calls == 1


def test_strategy_disabled_after_force_flatten() -> None:
    """Subsequent approve_or_deny returns STRATEGY_DISABLED."""
    client = _TrackingClient()
    gate = _gate(client=client)
    gate.on_tick(_state(equity=47_500, hw=50_000))
    asyncio.run(gate.force_flatten_now())

    intent = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="BRACKET", client_order_id="t-1", timestamp=_ts(),
        bracket=Bracket(stop_loss_ticks=10, take_profit_ticks=20),
    )
    result = gate.approve_or_deny(intent, _state(equity=50_000))
    assert isinstance(result, OrderDenied)
    assert result.rule == "STRATEGY_DISABLED"


def test_explicit_force_flatten_disables_strategy() -> None:
    """Direct call (e.g. 15:10 CT clock alert) also latches STRATEGY_DISABLED."""
    client = _TrackingClient()
    gate = _gate(client=client)
    asyncio.run(gate.force_flatten_now("HARD_FLAT_TIME"))
    assert client.cancel_all_calls == 1

    intent = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="BRACKET", client_order_id="t-2", timestamp=_ts(),
        bracket=Bracket(stop_loss_ticks=10, take_profit_ticks=20),
    )
    result = gate.approve_or_deny(intent, _state(equity=50_000))
    assert isinstance(result, OrderDenied)
    assert result.rule == "STRATEGY_DISABLED"
