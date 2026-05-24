"""BotRegistry — spec → live components.

Maps `BotSpec.strategy_id / risk_policy / schedule_type` to factory
callables that build the concrete object from `*_params`. The registry
ships with the v1 built-ins (ORB strategy, three Topstep risk policies,
three schedule types) pre-registered; downstream code can register new
ids without subclassing.

`build(spec, broker)` returns a fully-wired `ResolvedBot` — the broker
is shared across the fleet, so it's passed in rather than discovered
from the spec.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

from bot.backtest.strategy import Strategy
from bot.execution.ports import ExecutionClient
from bot.observability.bus import NoopTelemetryBus
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.efa_drawdown import EFAConsistencyDrawdown, EFAStandardEoDDrawdown
from bot.risk.gate import TopstepRiskGate
from bot.risk.policies import DrawdownPolicy
from bot.runtime.fleet.schedule import AlwaysOn, CustomWindows, MarketHours, Schedule
from bot.runtime.fleet.spec import BotSpec
from bot.strategy.mean_reversion import MeanReversionStrategy
from bot.strategy.orb import OpeningRangeBreakoutStrategy, ORBProfile

_CT: Final[ZoneInfo] = ZoneInfo("America/Chicago")

StrategyFactory = Callable[[dict[str, Any]], Strategy]
PolicyFactory = Callable[[dict[str, Any]], DrawdownPolicy]
ScheduleFactory = Callable[[dict[str, Any]], Schedule]


@dataclass(frozen=True)
class ResolvedBot:
    """One bot's live components, ready for FleetRuntime to wrap in a LiveTradingLoop."""

    name: str
    spec: BotSpec
    strategy: Strategy
    risk_gate: TopstepRiskGate
    schedule: Schedule
    journal_path: Path


class _NoopNews:
    """Default news calendar — never blocks. Per-bot news config arrives in a later plan."""

    def in_window(self, now: Any) -> bool:
        _ = now
        return False

    def max_position_during_window(self) -> int:
        return 1


def _parse_time(value: str | time) -> time:
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def _build_orb(params: dict[str, Any]) -> Strategy:
    return OpeningRangeBreakoutStrategy(ORBProfile.model_validate(params))


def _build_mean_reversion(params: dict[str, Any]) -> Strategy:
    # MeanReversionStrategy takes kwargs directly — no Pydantic profile.
    # ConfigError-shaped TypeErrors here surface a bad strategy_params block.
    return MeanReversionStrategy(**params)


def _build_market_hours(params: dict[str, Any]) -> Schedule:
    open_ct = _parse_time(params.get("open_ct", time(8, 30)))
    close_ct = _parse_time(params.get("close_ct", time(15, 10)))
    return MarketHours(open_ct=open_ct, close_ct=close_ct)


def _build_custom_windows(params: dict[str, Any]) -> Schedule:
    raw_windows = params.get("windows", [])
    windows: list[tuple[time, time]] = [
        (_parse_time(start), _parse_time(end)) for start, end in raw_windows
    ]
    tz_name = params.get("tz")
    tz = ZoneInfo(str(tz_name)) if tz_name is not None else _CT
    return CustomWindows(windows=windows, tz=tz)


class BotRegistry:
    """Registry of strategy / risk-policy / schedule factories.

    Built-ins are pre-registered at construction. Callers can override
    or extend via `register_strategy / register_risk_policy / register_schedule`.
    """

    def __init__(self) -> None:
        self._strategies: dict[str, StrategyFactory] = {}
        self._policies: dict[str, PolicyFactory] = {}
        self._schedules: dict[str, ScheduleFactory] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        self.register_strategy("orb_5m", _build_orb)
        self.register_strategy("mean_reversion_bb", _build_mean_reversion)
        self.register_risk_policy(
            "combine_intraday",
            lambda p: CombineIntradayDrawdown(**p),
        )
        self.register_risk_policy(
            "efa_standard",
            lambda p: EFAStandardEoDDrawdown(**p),
        )
        self.register_risk_policy(
            "efa_consistency",
            lambda p: EFAConsistencyDrawdown(**p),
        )
        self.register_schedule("always", lambda p: AlwaysOn())
        self.register_schedule("market_hours", _build_market_hours)
        self.register_schedule("custom_windows", _build_custom_windows)

    def register_strategy(self, sid: str, factory: StrategyFactory) -> None:
        self._strategies[sid] = factory

    def register_risk_policy(self, pid: str, factory: PolicyFactory) -> None:
        self._policies[pid] = factory

    def register_schedule(self, sid: str, factory: ScheduleFactory) -> None:
        self._schedules[sid] = factory

    def build(self, spec: BotSpec, *, broker: ExecutionClient) -> ResolvedBot:
        """Resolve the spec into live components wired to the shared broker."""
        if spec.strategy_id not in self._strategies:
            raise KeyError(f"unknown strategy_id: {spec.strategy_id!r}")
        if spec.risk_policy not in self._policies:
            raise KeyError(f"unknown risk_policy: {spec.risk_policy!r}")
        if spec.schedule_type not in self._schedules:
            raise KeyError(f"unknown schedule_type: {spec.schedule_type!r}")

        strategy = self._strategies[spec.strategy_id](spec.strategy_params)
        policy = self._policies[spec.risk_policy](spec.risk_params)
        schedule = self._schedules[spec.schedule_type](spec.schedule_params)
        gate = TopstepRiskGate(
            policy=policy,
            news_calendar=_NoopNews(),
            execution_client=broker,
            telemetry=NoopTelemetryBus(),
            config=RiskConfig(env="backtest", accounts_managed=1),
            symbol=spec.symbol,
        )
        return ResolvedBot(
            name=spec.name,
            spec=spec,
            strategy=strategy,
            risk_gate=gate,
            schedule=schedule,
            journal_path=spec.journal_path,
        )
