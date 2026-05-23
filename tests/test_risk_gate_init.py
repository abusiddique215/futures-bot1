"""TopstepRiskGate init + cross-account assertion."""
from __future__ import annotations

import pytest

from bot.types import (
    AccountState,
    Order,
    OrderEvent,
    OrderIntent,
    Position,
)


class _MockClient:
    async def cancel_all(self, symbol: str) -> list[OrderEvent]: return []
    async def close_all_positions(self) -> None: return None
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def place_order(self, intent: OrderIntent) -> OrderEvent: ...  # type: ignore[empty-body]
    async def cancel_order(self, client_order_id: str) -> OrderEvent: ...  # type: ignore[empty-body]
    async def get_positions(self) -> list[Position]: return []
    async def get_open_orders(self) -> list[Order]: return []
    async def get_account(self) -> AccountState: ...  # type: ignore[empty-body]


class _MockTelemetry:
    def alert(self, kind: str, **kw) -> None: pass


class _MockNewsCal:
    def in_window(self, now) -> bool: return False
    def max_position_during_window(self) -> int: return 1


def test_gate_constructs_with_combine_policy() -> None:
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    from bot.risk.config import RiskConfig
    from bot.risk.gate import TopstepRiskGate
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    gate = TopstepRiskGate(
        policy=policy, news_calendar=_MockNewsCal(),
        execution_client=_MockClient(),
        telemetry=_MockTelemetry(),
        config=cfg,
    )
    assert gate is not None


def test_gate_rejects_multi_account_via_config() -> None:
    """Single-account assertion enforced via RiskConfig validation."""
    from pydantic import ValidationError

    from bot.risk.config import RiskConfig
    with pytest.raises(ValidationError):
        RiskConfig(env="backtest", accounts_managed=3)


def test_gate_tick_cadence_assertion_paper_live_only() -> None:
    """Backtest exempt from tick-cadence assertion; paper/live enforce it."""
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    from bot.risk.config import RiskConfig
    from bot.risk.gate import TopstepRiskGate

    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    # backtest: high cadence is FINE
    cfg_bt = RiskConfig(env="backtest", accounts_managed=1, tick_cadence_seconds=60.0)
    TopstepRiskGate(policy=policy, news_calendar=_MockNewsCal(),
                    execution_client=_MockClient(), telemetry=_MockTelemetry(),
                    config=cfg_bt)  # no exception

    # paper: cadence > 1.0s SHOULD fail
    cfg_paper = RiskConfig(env="paper", accounts_managed=1, tick_cadence_seconds=2.0)
    with pytest.raises(AssertionError, match="tick cadence"):
        TopstepRiskGate(policy=policy, news_calendar=_MockNewsCal(),
                        execution_client=_MockClient(), telemetry=_MockTelemetry(),
                        config=cfg_paper)
