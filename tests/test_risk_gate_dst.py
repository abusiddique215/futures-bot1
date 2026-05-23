"""DST timezone tests for the 15:10 CT hard-flat check. Spec 04 §5.4.

US Central observes DST. The hard-flat time is "15:10 America/Chicago" which
maps to different UTC instants on standard vs daylight time:
- DST (Mar-Nov): 15:10 CDT = 20:10 UTC
- Standard (Nov-Mar): 15:10 CST = 21:10 UTC

The gate uses zoneinfo (DST-aware) so both cases must work.
"""
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


def _state_at_utc(ts: datetime) -> AccountState:
    return AccountState(
        equity=50_000, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=ts,
    )


def _intent(ts: datetime) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="BRACKET", client_order_id="t-1", timestamp=ts,
        bracket=Bracket(stop_loss_ticks=10, take_profit_ticks=20),
    )


def test_dst_summer_15_11_cdt_equals_20_11_utc_denied() -> None:
    """During CDT (UTC-5), 15:11 CT = 20:11 UTC.
    A test date in July 2026 is unambiguously CDT."""
    ts = datetime(2026, 7, 15, 20, 11, tzinfo=UTC)
    result = _gate().approve_or_deny(_intent(ts), _state_at_utc(ts))
    assert isinstance(result, OrderDenied)
    assert result.rule == "HARD_FLAT_CLOCK"


def test_dst_winter_15_11_cst_equals_21_11_utc_denied() -> None:
    """During CST (UTC-6), 15:11 CT = 21:11 UTC.
    A test date in January 2026 is unambiguously CST."""
    ts = datetime(2026, 1, 15, 21, 11, tzinfo=UTC)
    result = _gate().approve_or_deny(_intent(ts), _state_at_utc(ts))
    assert isinstance(result, OrderDenied)
    assert result.rule == "HARD_FLAT_CLOCK"


def test_dst_summer_14_59_cdt_allowed() -> None:
    """14:59 CDT = 19:59 UTC in July -> not yet hard-flat."""
    ts = datetime(2026, 7, 15, 19, 59, tzinfo=UTC)
    result = _gate().approve_or_deny(_intent(ts), _state_at_utc(ts))
    if isinstance(result, OrderDenied):
        assert result.rule not in ("HARD_FLAT_CLOCK", "HARD_FLAT_PREEMPT")


def test_dst_winter_14_59_cst_allowed() -> None:
    """14:59 CST = 20:59 UTC in January -> not yet hard-flat."""
    ts = datetime(2026, 1, 15, 20, 59, tzinfo=UTC)
    result = _gate().approve_or_deny(_intent(ts), _state_at_utc(ts))
    if isinstance(result, OrderDenied):
        assert result.rule not in ("HARD_FLAT_CLOCK", "HARD_FLAT_PREEMPT")
