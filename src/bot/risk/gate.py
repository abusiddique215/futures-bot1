"""TopstepRiskGate — the single, mandatory choke point between Strategy
decisions and broker order placement.

Spec: 04. A bug here is real-money loss; every rule has property + scenario +
boundary tests.

Tasks 8-15 add the seven rule checks + stop-offset buffer.
Tasks 16-17 add on_tick + force_flatten.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bot.execution.ports import ExecutionClient
from bot.risk.cancel_tracker import RollingRatioTracker
from bot.risk.config import RiskConfig
from bot.risk.news import NewsCalendar
from bot.risk.policies import DrawdownPolicy


@runtime_checkable
class _Telemetry(Protocol):
    """Minimal Protocol for telemetry; satisfied by Plan 7's full impl."""
    def alert(self, kind: str, **kw: object) -> None: ...


class TopstepRiskGate:
    """Pre-trade rule check + tick-driven state updates + force-flatten triggers."""

    def __init__(
        self,
        *,
        policy: DrawdownPolicy,
        news_calendar: NewsCalendar,
        execution_client: ExecutionClient,
        telemetry: _Telemetry,
        config: RiskConfig,
    ) -> None:
        assert config.accounts_managed == 1, (
            "Multi-account orchestration is out of scope for v1. "
            "Cross-account hedging is a Topstep ToS violation."
        )
        if config.env in ("paper", "live"):
            assert config.tick_cadence_seconds <= 1.0, (
                "tick cadence must be <= 1.0s in paper/live mode. "
                "Combine MLL is monitored on unrealized P&L in real time; "
                "the gate must receive tick updates at least once per second. "
                "Backtest mode is exempt."
            )
        self.policy = policy
        self.news_calendar = news_calendar
        self.execution_client = execution_client
        self.telemetry = telemetry
        self.config = config
        self.cancel_to_fill_tracker = RollingRatioTracker(window_minutes=60)
        self._flattening = False
