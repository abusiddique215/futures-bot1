"""Rule 2: DLL + stop-required sub-check."""
from __future__ import annotations

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


def _gate() -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=_MC(),
        telemetry=_Tel(),
        config=RiskConfig(env="backtest", accounts_managed=1),
    )


def _ts() -> datetime:
    return datetime(2026, 5, 22, 14, 0, tzinfo=UTC)


def _state(realized: float = 0) -> AccountState:
    return AccountState(
        equity=50_000, realized_pnl_today=realized, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=_ts(),
    )


def _intent_with_bracket(stop_ticks: int = 10, qty: int = 1) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=qty,
        order_type="BRACKET", client_order_id="t-1", timestamp=_ts(),
        bracket=Bracket(stop_loss_ticks=stop_ticks, take_profit_ticks=20),
    )


def test_open_without_bracket_denied_STOP_REQUIRED() -> None:
    intent = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="MARKET", client_order_id="t-1", timestamp=_ts(),
    )
    result = _gate().approve_or_deny(intent, _state())
    assert isinstance(result, OrderDenied)
    assert result.rule == "STOP_REQUIRED"


def test_dll_breach_denied() -> None:
    """realized=-900 + worst-case-loss (10 ticks x $0.50/tick x 1 MNQ = $5)
    is -905. NOT a breach. Use larger numbers: realized = -995, stop 10 ticks
    -> -995 - 5 = -1000 -> equality breach."""
    intent = _intent_with_bracket(stop_ticks=10, qty=1)
    state = _state(realized=-995)
    result = _gate().approve_or_deny(intent, state)
    assert isinstance(result, OrderDenied)
    assert result.rule == "DLL"


def test_dll_just_under_limit_allowed() -> None:
    """realized=-994, stop 10 ticks → -994 - 5 = -999 → just OK."""
    intent = _intent_with_bracket(stop_ticks=10, qty=1)
    state = _state(realized=-994)
    result = _gate().approve_or_deny(intent, state)
    # Should NOT be denied by rule 2; rules 3+ might still fire — assert rule != DLL
    if isinstance(result, OrderDenied):
        assert result.rule != "DLL"
