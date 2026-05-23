"""§3.6 stop-offset safety buffer augmentation."""
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


class _MC:
    async def cancel_all(self, symbol: str) -> list[OrderEvent]: return []
    async def close_all_positions(self) -> None: pass
    async def connect(self) -> None: pass
    async def disconnect(self) -> None: pass
    async def place_order(self, intent: OrderIntent) -> OrderEvent: ...  # type: ignore[empty-body]
    async def cancel_order(self, client_order_id: str) -> OrderEvent: ...  # type: ignore[empty-body]
    async def get_positions(self) -> list[Position]: return []
    async def get_open_orders(self) -> list[Order]: return []
    async def get_account(self) -> AccountState: ...  # type: ignore[empty-body]


class _Tel:
    def alert(self, kind: str, **kw: object) -> None: pass


class _NoNews:
    def in_window(self, now: datetime) -> bool: return False
    def max_position_during_window(self) -> int: return 1


def _gate(safety_buffer: int = 5) -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=_MC(),
        telemetry=_Tel(),
        config=RiskConfig(env="backtest", accounts_managed=1,
                          safety_buffer_ticks=safety_buffer),
    )


def _ts() -> datetime:
    return datetime(2026, 5, 22, 14, 0, tzinfo=UTC)


def _state(equity: float, hw: float | None = None) -> AccountState:
    return AccountState(
        equity=equity, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=hw if hw is not None else equity, is_combine=True,
        timestamp=_ts(),
    )


def _intent(stop_ticks: int) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="BRACKET", client_order_id="t-1", timestamp=_ts(),
        bracket=Bracket(stop_loss_ticks=stop_ticks, take_profit_ticks=20),
    )


def test_strategy_stop_tighter_than_buffer_floor_unchanged() -> None:
    """phantom_distance=30 ticks (equity=$50_015, phantom=$50_000, MNQ tick=$0.50).
    Strategy stop=20, safety=5 -> floor=25. min(20, 25)=20 -> unchanged."""
    gate = _gate(safety_buffer=5)
    # equity needs to give phantom_distance >= 30 ticks. phantom_mll at hw=50_000 = 48_000.
    # phantom_distance_dollars = 50_015 - 48_000 = 2_015. ticks = 2_015 / 0.50 = 4_030.
    # That's way more than 30. Strategy stop=20 is tightest -> approved with 20.
    result = gate.approve_or_deny(_intent(stop_ticks=20), _state(equity=50_015))
    assert isinstance(result, ApprovedOrder)
    assert result.intent.bracket is not None
    assert result.intent.bracket.stop_loss_ticks == 20


def test_strategy_stop_wider_than_buffer_floor_capped() -> None:
    """hw=$50_000 (initial phantom=$48_000), equity=$48_015.
    phantom_distance_dollars = $15, ticks = 30, floor = 30 - 5 = 25.
    Strategy stop=28 -> min(28, 25) = 25."""
    gate = _gate(safety_buffer=5)
    result = gate.approve_or_deny(
        _intent(stop_ticks=28),
        _state(equity=48_015, hw=50_000),
    )
    # worst_case_loss = 28 * 0.50 = $14, projected_floor = 48_015 - 14 = 48_001
    # > phantom 48_000. Passes rule 3. Buffer caps stop to 25.
    assert isinstance(result, ApprovedOrder)
    assert result.intent.bracket is not None
    assert result.intent.bracket.stop_loss_ticks == 25


def test_proximity_to_phantom_denies_MLL_PROXIMITY() -> None:
    """hw=$50_000, equity=$48_002. phantom=$48_000, distance=$2=4 ticks.
    floor_after_buffer = 4 - 5 = -1 -> denies MLL_PROXIMITY.
    Use 1-tick stop so worst-case-loss = $0.50 < $2 distance -> passes rule 3."""
    gate = _gate(safety_buffer=5)
    intent = _intent(stop_ticks=1)
    result = gate.approve_or_deny(intent, _state(equity=48_002, hw=50_000))
    assert isinstance(result, OrderDenied)
    assert result.rule == "MLL_PROXIMITY"


def test_reducing_close_without_bracket_skips_buffer() -> None:
    """A reducing order (MARKET, no bracket) is approved without buffer logic."""
    gate = _gate(safety_buffer=5)
    state = AccountState(
        equity=50_015, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={"MNQ": 3}, pending_intent_count=0,
        high_water_equity=50_015, is_combine=True,
        timestamp=_ts(),
    )
    close_intent = OrderIntent(
        symbol="MNQ", side="SELL", quantity=1,
        order_type="MARKET", client_order_id="close-1", timestamp=_ts(),
    )
    result = gate.approve_or_deny(close_intent, state)
    assert isinstance(result, ApprovedOrder)
    assert result.intent.bracket is None  # unchanged
