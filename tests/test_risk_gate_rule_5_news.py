"""Rule 5: news throttle. Spec 04 §3.2 rule 5."""
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


class _NewsAlwaysOpen:
    """News calendar that says we're ALWAYS in a window, cap=1."""
    def in_window(self, now: datetime) -> bool: return True
    def max_position_during_window(self) -> int: return 1


class _NewsAlwaysClosed:
    def in_window(self, now: datetime) -> bool: return False
    def max_position_during_window(self) -> int: return 1


def _gate(news: object) -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=news,  # type: ignore[arg-type]
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


def test_buy_during_news_window_above_cap_denied_NEWS_THROTTLE() -> None:
    """In news window with cap=1, flat + BUY 2 -> projected 2 > 1 -> deny."""
    result = _gate(_NewsAlwaysOpen()).approve_or_deny(_intent(qty=2), _state({}))
    assert isinstance(result, OrderDenied)
    assert result.rule == "NEWS_THROTTLE"


def test_buy_outside_news_window_not_denied_by_news() -> None:
    """Flat + BUY 2 outside news window -> may be denied for OTHER reasons,
    but NOT NEWS_THROTTLE."""
    result = _gate(_NewsAlwaysClosed()).approve_or_deny(_intent(qty=2), _state({}))
    if isinstance(result, OrderDenied):
        assert result.rule != "NEWS_THROTTLE"


def test_reducing_during_news_window_allowed() -> None:
    """Long 3 MNQ in news window. SELL 1 (reducer, |proj|=2 > cap=1) is NOT denied
    by news. Spec §3.2 rule 5: window only caps OPENING + sizing orders."""
    intent = OrderIntent(
        symbol="MNQ", side="SELL", quantity=1,
        order_type="MARKET", client_order_id="close-1", timestamp=_ts(),
    )
    result = _gate(_NewsAlwaysOpen()).approve_or_deny(intent, _state({"MNQ": 3}))
    if isinstance(result, OrderDenied):
        assert result.rule != "NEWS_THROTTLE"
