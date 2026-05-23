"""Rule 1: hard-flat clock check. Spec 04 §3.2."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.types import (
    AccountState,
    Order,
    OrderEvent,
    OrderIntent,
    Position,
)

CT = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")


class _MockClient:
    async def cancel_all(self, symbol: str) -> list[OrderEvent]: return []
    async def close_all_positions(self) -> None: return None
    async def connect(self) -> None: pass
    async def disconnect(self) -> None: pass
    async def place_order(self, intent: OrderIntent) -> OrderEvent: ...  # type: ignore[empty-body]
    async def cancel_order(self, client_order_id: str) -> OrderEvent: ...  # type: ignore[empty-body]
    async def get_positions(self) -> list[Position]: return []
    async def get_open_orders(self) -> list[Order]: return []
    async def get_account(self) -> AccountState: ...  # type: ignore[empty-body]


class _MockTel:
    def alert(self, kind: str, **kw: object) -> None: pass


class _NoNews:
    def in_window(self, now: datetime) -> bool: return False
    def max_position_during_window(self) -> int: return 1


def _make_gate() -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=_MockClient(),
        telemetry=_MockTel(),
        config=RiskConfig(env="backtest", accounts_managed=1),
    )


def _at_ct(hh: int, mm: int) -> datetime:
    return datetime(2026, 5, 22, hh, mm, tzinfo=CT).astimezone(UTC)


def _intent(side: str = "BUY", qty: int = 1) -> OrderIntent:
    return OrderIntent(symbol="MNQ", side=side, quantity=qty,  # type: ignore[arg-type]
                       order_type="MARKET", client_order_id="t-1",
                       timestamp=_at_ct(15, 5))


def _state(ts_ct_hh: int, ts_ct_mm: int, positions: dict[str, int] | None = None) -> AccountState:
    return AccountState(
        equity=50_000, realized_pnl_today=0, unrealized_pnl=0,
        open_positions=positions or {}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=True,
        timestamp=_at_ct(ts_ct_hh, ts_ct_mm),
    )


def test_open_at_15_11_ct_denied_HARD_FLAT_CLOCK() -> None:
    gate = _make_gate()
    result = gate.approve_or_deny(_intent(), _state(15, 11))
    from bot.types import OrderDenied
    assert isinstance(result, OrderDenied)
    assert result.rule == "HARD_FLAT_CLOCK"


def test_open_at_15_05_ct_denied_HARD_FLAT_PREEMPT() -> None:
    gate = _make_gate()
    result = gate.approve_or_deny(_intent(), _state(15, 5))
    from bot.types import OrderDenied
    assert isinstance(result, OrderDenied)
    assert result.rule == "HARD_FLAT_PREEMPT"


def test_open_at_14_59_ct_allowed() -> None:
    gate = _make_gate()
    result = gate.approve_or_deny(_intent(), _state(14, 59))
    from bot.types import OrderDenied
    # NOT denied by rule 1 (may be denied by rule 2 due to no stop — accept that
    # for now; rule 2 is task 9).
    if isinstance(result, OrderDenied):
        assert result.rule != "HARD_FLAT_CLOCK"
        assert result.rule != "HARD_FLAT_PREEMPT"


def test_close_at_15_11_ct_allowed() -> None:
    """A REDUCING order (closes existing long) is allowed even at 15:11."""
    gate = _make_gate()
    # Long 2 MNQ; SELL 1 MNQ → reducing
    state = _state(15, 11, positions={"MNQ": 2})
    intent_close = OrderIntent(
        symbol="MNQ", side="SELL", quantity=1,
        order_type="MARKET", client_order_id="close-1",
        timestamp=_at_ct(15, 11),
    )
    result = gate.approve_or_deny(intent_close, state)
    from bot.types import OrderDenied
    # Rule 1 doesn't deny closes. Rule 2 might (no bracket stop on a market close
    # — but spec says reducers don't need stops). For now: assert rule 1 didn't fire.
    if isinstance(result, OrderDenied):
        assert result.rule not in ("HARD_FLAT_CLOCK", "HARD_FLAT_PREEMPT")
