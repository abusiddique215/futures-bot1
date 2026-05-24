"""Plan 22 T1 — policy-aware hard-flat.

Rule 1 (hard-flat clock) consults `policy.enforces_hard_flat`:
  - Combine policies (enforces_hard_flat=True) deny open intents past 15:10 CT
    AND emit a HARD_FLAT_PREEMPT warning between 15:00 and 15:10 CT.
  - EFA policies (Standard / Consistency, enforces_hard_flat=False) skip the
    clock check entirely — 24/7 bots on funded accounts can trade through the
    15:10-17:00 CT window.

The Combine regression case is SAFETY-CRITICAL: a future refactor must never
silently re-allow Combine bots to open new positions past 15:10 CT.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.efa_drawdown import EFAConsistencyDrawdown, EFAStandardEoDDrawdown
from bot.risk.gate import TopstepRiskGate
from bot.risk.policies import DrawdownPolicy
from bot.types import (
    AccountState,
    Order,
    OrderDenied,
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


def _make_gate(policy: DrawdownPolicy) -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=policy,
        news_calendar=_NoNews(),
        execution_client=_MockClient(),
        telemetry=_MockTel(),
        config=RiskConfig(env="backtest", accounts_managed=1),
    )


def _at_ct(hh: int, mm: int) -> datetime:
    return datetime(2026, 5, 22, hh, mm, tzinfo=CT).astimezone(UTC)


def _intent() -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,  # type: ignore[arg-type]
        order_type="MARKET", client_order_id="t-1",
        timestamp=_at_ct(15, 30),
    )


def _state(hh: int, mm: int, *, is_combine: bool) -> AccountState:
    return AccountState(
        equity=50_000, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=is_combine,
        timestamp=_at_ct(hh, mm),
    )


# ---- Combine: REGRESSION — must still hard-flat ----------------------------

def test_combine_policy_still_denies_at_15_11_ct() -> None:
    """SAFETY-CRITICAL regression: Combine bots MUST hard-flat past 15:10."""
    gate = _make_gate(CombineIntradayDrawdown(50_000, 2_000, 5))
    result = gate.approve_or_deny(_intent(), _state(15, 11, is_combine=True))
    assert isinstance(result, OrderDenied)
    assert result.rule == "HARD_FLAT_CLOCK"


def test_combine_policy_still_preempts_at_15_05_ct() -> None:
    gate = _make_gate(CombineIntradayDrawdown(50_000, 2_000, 5))
    result = gate.approve_or_deny(_intent(), _state(15, 5, is_combine=True))
    assert isinstance(result, OrderDenied)
    assert result.rule == "HARD_FLAT_PREEMPT"


def test_combine_policy_exposes_enforces_hard_flat_true() -> None:
    """Class-level attribute, not per-instance."""
    assert CombineIntradayDrawdown.enforces_hard_flat is True


# ---- EFA Standard: no hard-flat past 15:10 ---------------------------------

def test_efa_standard_does_not_deny_at_15_30_ct() -> None:
    """24/7 EFA bots open past 15:10 — no HARD_FLAT_CLOCK denial."""
    gate = _make_gate(EFAStandardEoDDrawdown(2_000))
    result = gate.approve_or_deny(_intent(), _state(15, 30, is_combine=False))
    # NOT denied by rule 1. May be denied later (no bracket → STOP_REQUIRED is
    # rule 2 territory — accept that as long as rule 1 didn't fire).
    if isinstance(result, OrderDenied):
        assert result.rule not in ("HARD_FLAT_CLOCK", "HARD_FLAT_PREEMPT")


def test_efa_standard_does_not_preempt_at_15_05_ct() -> None:
    gate = _make_gate(EFAStandardEoDDrawdown(2_000))
    result = gate.approve_or_deny(_intent(), _state(15, 5, is_combine=False))
    if isinstance(result, OrderDenied):
        assert result.rule not in ("HARD_FLAT_CLOCK", "HARD_FLAT_PREEMPT")


def test_efa_standard_exposes_enforces_hard_flat_false() -> None:
    assert EFAStandardEoDDrawdown.enforces_hard_flat is False


# ---- EFA Consistency: same as Standard -------------------------------------

def test_efa_consistency_does_not_deny_at_15_30_ct() -> None:
    gate = _make_gate(EFAConsistencyDrawdown(2_000))
    result = gate.approve_or_deny(_intent(), _state(15, 30, is_combine=False))
    if isinstance(result, OrderDenied):
        assert result.rule not in ("HARD_FLAT_CLOCK", "HARD_FLAT_PREEMPT")


def test_efa_consistency_exposes_enforces_hard_flat_false() -> None:
    """Subclass restates the attribute — explicit > inherited for safety."""
    assert EFAConsistencyDrawdown.enforces_hard_flat is False
