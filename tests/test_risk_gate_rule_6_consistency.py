"""Rule 6: Combine consistency (best-day / target_remaining <= 50%).

Default is soft-warn (telemetry only); operator can set consistency_mode="hard"
in RiskConfig to deny per-trade. EFA accounts skip this rule (their 40% cap
runs at payout time via EFAConsistencyDrawdown.gate_payout).
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
    def __init__(self) -> None:
        self.alerts: list[tuple[str, dict[str, object]]] = []
    def alert(self, kind: str, **kw: object) -> None:
        self.alerts.append((kind, kw))


class _NoNews:
    def in_window(self, now: datetime) -> bool: return False
    def max_position_during_window(self) -> int: return 1


class _Journal:
    def __init__(self, best_day: float, net_pnl: float) -> None:
        self._b = best_day
        self._n = net_pnl
    def best_day_pnl_so_far(self) -> float: return self._b
    def net_pnl_so_far(self) -> float: return self._n


def _gate(
    consistency_mode: str = "soft",
    journal: _Journal | None = None,
    telemetry: _Tel | None = None,
) -> TopstepRiskGate:
    tel = telemetry if telemetry is not None else _Tel()
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoNews(),
        execution_client=_MC(),
        telemetry=tel,
        config=RiskConfig(env="backtest", accounts_managed=1, consistency_mode=consistency_mode),
        journal_provider=journal,
    )


def _ts() -> datetime:
    return datetime(2026, 5, 22, 14, 0, tzinfo=UTC)


def _state(is_combine: bool = True) -> AccountState:
    return AccountState(
        equity=50_000, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=is_combine,
        timestamp=_ts(),
    )


def _intent() -> OrderIntent:
    return OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="BRACKET", client_order_id="t-1", timestamp=_ts(),
        bracket=Bracket(stop_loss_ticks=10, take_profit_ticks=20),
    )


def test_hard_mode_60pct_best_day_denies() -> None:
    """best_day=1200, target_remaining=2000 (net=1000), ratio=60% > 50%."""
    journal = _Journal(best_day=1200, net_pnl=1000)
    gate = _gate(consistency_mode="hard", journal=journal)
    result = gate.approve_or_deny(_intent(), _state())
    assert isinstance(result, OrderDenied)
    assert result.rule == "CONSISTENCY_HARD"


def test_soft_mode_60pct_best_day_allows_with_telemetry() -> None:
    """Soft mode allows but emits CONSISTENCY_50PCT_EXCEEDED alert."""
    journal = _Journal(best_day=1200, net_pnl=1000)
    tel = _Tel()
    gate = _gate(consistency_mode="soft", journal=journal, telemetry=tel)
    result = gate.approve_or_deny(_intent(), _state())
    if isinstance(result, OrderDenied):
        assert result.rule != "CONSISTENCY_HARD"
    assert any(kind == "CONSISTENCY_50PCT_EXCEEDED" for kind, _ in tel.alerts)


def test_efa_account_skips_consistency_rule() -> None:
    """EFA accounts don't trigger rule 6 even in hard mode."""
    journal = _Journal(best_day=5000, net_pnl=1000)
    gate = _gate(consistency_mode="hard", journal=journal)
    result = gate.approve_or_deny(_intent(), _state(is_combine=False))
    if isinstance(result, OrderDenied):
        assert result.rule != "CONSISTENCY_HARD"


def test_no_journal_provider_defaults_to_noop() -> None:
    """Default JournalProvider returns 0 PnL; rule 6 never trips."""
    gate = _gate(consistency_mode="hard", journal=None)
    result = gate.approve_or_deny(_intent(), _state())
    if isinstance(result, OrderDenied):
        assert result.rule != "CONSISTENCY_HARD"
