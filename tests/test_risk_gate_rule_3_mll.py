"""Rule 3: MLL phantom check (the load-bearing one)."""
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


def _state(equity: float, hw: float | None = None) -> AccountState:
    return AccountState(
        equity=equity, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=hw if hw is not None else equity,
        is_combine=True,
        timestamp=datetime(2026, 5, 22, 14, 0, tzinfo=UTC),
    )


def _intent(stop_ticks: int = 10, qty: int = 1) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=qty,
        order_type="BRACKET", client_order_id="t-1",
        timestamp=datetime(2026, 5, 22, 14, 0, tzinfo=UTC),
        bracket=Bracket(stop_loss_ticks=stop_ticks, take_profit_ticks=20),
    )


def test_mll_breach_when_worst_case_loss_below_phantom() -> None:
    """equity=48_004, hw=50_000 -> phantom=48_000. Worst-case loss 10 ticks x 0.50
    x 1 MNQ = $5 -> projected_floor 47_999 < phantom 48_000 -> denied."""
    result = _gate().approve_or_deny(
        _intent(stop_ticks=10, qty=1),
        _state(equity=48_004, hw=50_000),
    )
    assert isinstance(result, OrderDenied)
    assert result.rule == "MLL"


def test_mll_no_breach_when_far_from_phantom() -> None:
    """equity=51_000, phantom=49_000 (hw=51_000). Worst-case loss $5 →
    projected 50_995 > phantom 49_000 → allowed (rule 3 doesn't fire)."""
    result = _gate().approve_or_deny(_intent(), _state(equity=51_000, hw=51_000))
    if isinstance(result, OrderDenied):
        assert result.rule != "MLL"
