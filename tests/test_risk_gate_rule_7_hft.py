"""Rule 7: HFT defensive cap (cancel-to-fill ratio over rolling 60 min)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


def _gate(threshold: float = 5.0) -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=_MC(),
        telemetry=_Tel(),
        config=RiskConfig(env="backtest", accounts_managed=1,
                          hft_cancel_to_fill_threshold=threshold),
    )


def _ts() -> datetime:
    return datetime(2026, 5, 22, 14, 0, tzinfo=UTC)


def _state() -> AccountState:
    return AccountState(
        equity=50_000, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=_ts(),
    )


def _intent() -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="BRACKET", client_order_id="t-1", timestamp=_ts(),
        bracket=Bracket(stop_loss_ticks=10, take_profit_ticks=20),
    )


def test_ratio_at_4_under_threshold_5_allowed() -> None:
    gate = _gate(threshold=5.0)
    # Record 4 cancels + 1 fill -> ratio = 4.0
    now = _ts()
    for _ in range(4):
        gate.cancel_to_fill_tracker.record_cancel(now)
    gate.cancel_to_fill_tracker.record_fill(now)
    result = gate.approve_or_deny(_intent(), _state())
    if isinstance(result, OrderDenied):
        assert result.rule != "HFT_DEFENSIVE"


def test_ratio_at_6_above_threshold_5_denies() -> None:
    gate = _gate(threshold=5.0)
    now = _ts()
    for _ in range(6):
        gate.cancel_to_fill_tracker.record_cancel(now)
    gate.cancel_to_fill_tracker.record_fill(now)
    result = gate.approve_or_deny(_intent(), _state())
    assert isinstance(result, OrderDenied)
    assert result.rule == "HFT_DEFENSIVE"


def test_old_events_outside_window_dont_count() -> None:
    """Cancels from 2 hours ago are outside the 60-min window."""
    gate = _gate(threshold=5.0)
    now = _ts()
    old = now - timedelta(hours=2)
    for _ in range(10):
        gate.cancel_to_fill_tracker.record_cancel(old)  # too old
    gate.cancel_to_fill_tracker.record_fill(now)
    result = gate.approve_or_deny(_intent(), _state())
    if isinstance(result, OrderDenied):
        assert result.rule != "HFT_DEFENSIVE"
