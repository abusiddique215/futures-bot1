"""Rule 4: max position cap. Spec 04 §3.2 rule 4."""
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


def _state(positions: dict[str, int]) -> AccountState:
    return AccountState(
        equity=50_000, realized_pnl_today=0, unrealized_pnl=0,
        open_positions=positions, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=_ts(),
    )


def _intent(qty: int = 1, side: str = "BUY") -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side=side, quantity=qty,  # type: ignore[arg-type]
        order_type="BRACKET", client_order_id="t-1", timestamp=_ts(),
        bracket=Bracket(stop_loss_ticks=10, take_profit_ticks=20),
    )


def test_buy_above_cap_denied_MAX_POSITION() -> None:
    """Long 50 MNQ + BUY 1 -> projected 51 > cap 50 -> deny."""
    result = _gate().approve_or_deny(_intent(qty=1), _state({"MNQ": 50}))
    assert isinstance(result, OrderDenied)
    assert result.rule == "MAX_POSITION"


def test_buy_at_cap_allowed() -> None:
    """Long 49 MNQ + BUY 1 -> projected 50 == cap -> NOT denied by rule 4."""
    result = _gate().approve_or_deny(_intent(qty=1), _state({"MNQ": 49}))
    if isinstance(result, OrderDenied):
        assert result.rule != "MAX_POSITION"


def test_buy_below_cap_allowed() -> None:
    """Flat + BUY 1 MNQ -> projected 1 < cap 50 -> NOT denied by rule 4."""
    result = _gate().approve_or_deny(_intent(qty=1), _state({}))
    assert isinstance(result, ApprovedOrder) or (
        isinstance(result, OrderDenied) and result.rule != "MAX_POSITION"
    )
