"""Property-based tests for TopstepRiskGate. Spec 04 §5.1.

Verifies:
1. Determinism: same (intent, state) -> same decision, twice.
2. No state mutation: AccountState is byte-identical after a call.
3. Monotone in equity (for non-time-driven rules): higher equity is at least
   as permissive as lower equity for the same intent.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.types import (
    AccountState,
    ApprovedOrder,
    Bracket,
    Order,
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


def _new_gate() -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=_MC(),
        telemetry=_Tel(),
        config=RiskConfig(env="backtest", accounts_managed=1),
    )


_TS = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)  # well before 15:00 CT cutoffs


def _build_state(equity: float) -> AccountState:
    return AccountState(
        equity=equity, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=_TS,
    )


def _build_intent(stop_ticks: int, qty: int) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=qty,
        order_type="BRACKET", client_order_id="t-prop", timestamp=_TS,
        bracket=Bracket(stop_loss_ticks=stop_ticks, take_profit_ticks=20),
    )


# Hypothesis strategies — keep ranges sensible to avoid covering trivially
# denied space (e.g. equity in the millions where everything passes).
_EQUITY = st.floats(min_value=46_000, max_value=55_000,
                    allow_nan=False, allow_infinity=False)
_STOP_TICKS = st.integers(min_value=1, max_value=200)
_QTY = st.integers(min_value=1, max_value=5)


@given(equity=_EQUITY, stop_ticks=_STOP_TICKS, qty=_QTY)
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_determinism(equity: float, stop_ticks: int, qty: int) -> None:
    """Same (intent, state) twice -> same result (rule + kind)."""
    gate = _new_gate()
    intent = _build_intent(stop_ticks, qty)
    state = _build_state(equity)
    r1 = gate.approve_or_deny(intent, state)
    r2 = gate.approve_or_deny(intent, state)
    assert type(r1) is type(r2)
    from bot.types import OrderDenied
    if isinstance(r1, OrderDenied) and isinstance(r2, OrderDenied):
        assert r1.rule == r2.rule


@given(equity=_EQUITY, stop_ticks=_STOP_TICKS, qty=_QTY)
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_no_state_mutation(equity: float, stop_ticks: int, qty: int) -> None:
    """approve_or_deny is pure: state is byte-identical after."""
    gate = _new_gate()
    intent = _build_intent(stop_ticks, qty)
    state = _build_state(equity)
    state_before = replace(state)  # snapshot
    gate.approve_or_deny(intent, state)
    assert state == state_before


@given(stop_ticks=_STOP_TICKS, qty=_QTY,
       low_eq=st.floats(min_value=46_000, max_value=49_000,
                        allow_nan=False, allow_infinity=False),
       delta=st.floats(min_value=100, max_value=5_000,
                       allow_nan=False, allow_infinity=False))
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_monotone_in_equity(stop_ticks: int, qty: int,
                            low_eq: float, delta: float) -> None:
    """Higher equity is AT LEAST as permissive as lower equity.

    If lower passes, higher passes too. (The reverse isn't required:
    higher might still be denied for other reasons.)
    """
    intent = _build_intent(stop_ticks, qty)
    low_result = _new_gate().approve_or_deny(intent, _build_state(low_eq))
    high_result = _new_gate().approve_or_deny(intent, _build_state(low_eq + delta))
    if isinstance(low_result, ApprovedOrder):
        # Higher equity should also approve (same time, fresh cancel-tracker).
        assert isinstance(high_result, ApprovedOrder)
