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

import os
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
from bot.runtime.fleet.live_only_guard import validate_schedule_x_policy
from bot.runtime.fleet.schedule import AlwaysOn, CustomWindows, MarketHours, Schedule
from bot.runtime.fleet.spec import BotSpec
from bot.signals.source import SignalSource
from bot.strategy.mean_reversion import MeanReversionStrategy
from bot.strategy.orb import OpeningRangeBreakoutStrategy, ORBProfile
from bot.strategy.profiles.propbot import PROPBOT_DEFAULTS
from bot.strategy.signal_strategy import SignalStrategy
from bot.strategy.tiered_sizing import TieredSizingDecorator
from bot.strategy.trend_following import TrendFollowingStrategy

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


def _build_trend_ema_pullback(params: dict[str, Any]) -> Strategy:
    """Apply PROPBOT defaults, then YAML overrides. session_end_ct accepts
    either a `datetime.time` (Python dict) or an ISO string (YAML round-trip)."""
    merged: dict[str, Any] = {**PROPBOT_DEFAULTS, **params}
    raw_cutoff = merged.get("session_end_ct")
    if raw_cutoff is not None:
        merged["session_end_ct"] = _parse_time(raw_cutoff)
    return TrendFollowingStrategy(**merged)


def _build_mean_reversion(params: dict[str, Any]) -> Strategy:
    # MeanReversionStrategy takes kwargs directly — no Pydantic profile.
    # ConfigError-shaped TypeErrors here surface a bad strategy_params block.
    return MeanReversionStrategy(**params)


def _build_orb_5m_tiered(params: dict[str, Any]) -> Strategy:
    """Compose `OpeningRangeBreakoutStrategy` + `TieredSizingDecorator`.

    Params shape:
      {
        "strategy": <ORBProfile fields>,
        "tiered":   {"tier_breakpoints": [...], "symbol": "..."},
      }
    """
    inner = OpeningRangeBreakoutStrategy(ORBProfile.model_validate(params["strategy"]))
    tiered = dict(params.get("tiered") or {})
    return TieredSizingDecorator(inner=inner, **tiered)


# Synthetic params key injected by BotRegistry.build() so the
# signal_strategy factory knows the bot's contract symbol (spec.symbol).
# Strategies whose params already carry a symbol (ORB) ignore it; the
# signal_strategy reads it here.
_BOT_SYMBOL_KEY = "_bot_symbol"


def _build_signal_source(params: dict[str, Any], symbol: str) -> SignalSource:
    """Build a SignalSource from env-driven config.

    Resolution order:
      1. LUX_BOT_FIXTURE_PATH set → FixtureSignalSource (JSON replay)
      2. DISCORD_BOT_TOKEN set + discord_channel_ids in params →
         DiscordSignalSource (production)
      3. Neither → RuntimeError (loud, not silent — the bot is opt-in)

    The split keeps the registry side-effect-free: no Discord network
    connection is opened at build time; that happens later when the
    strategy's pump task calls source.iter_signals().
    """
    import json
    from datetime import datetime
    from pathlib import Path

    from bot.signals.fixture_source import FixtureSignalSource
    from bot.signals.source import SignalEvent

    fixture_path = os.environ.get("LUX_BOT_FIXTURE_PATH")
    if fixture_path:
        raw_events = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        events = [
            SignalEvent(
                received_at=datetime.fromisoformat(r["received_at"]),
                symbol=r["symbol"], side=r["side"], qty=int(r["qty"]),
                limit_price=r.get("limit_price"),
                stop_loss=r.get("stop_loss"),
                take_profit=r.get("take_profit"),
                raw_text=r.get("raw_text", ""),
                source_id=r.get("source_id", ""),
            )
            for r in raw_events
        ]
        return FixtureSignalSource(events)

    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        from bot.signals.discord_source import DiscordSignalSource

        channel_ids = list(params.get("discord_channel_ids", []))
        default_symbol = str(params.get("default_symbol", symbol))
        return DiscordSignalSource(
            token=token,
            channel_ids=[int(c) for c in channel_ids],
            default_symbol=default_symbol,
        )

    raise RuntimeError(
        "signal_strategy requires LUX_BOT_FIXTURE_PATH (replay) or "
        "DISCORD_BOT_TOKEN (production). Neither was set.",
    )


def _build_signal_strategy(params: dict[str, Any]) -> Strategy:
    """Factory for the `signal_strategy` registry id.

    The bot's symbol is injected into params under `_BOT_SYMBOL_KEY` by
    `BotRegistry.build` — see the comment on that constant.
    """
    symbol = str(params.get(_BOT_SYMBOL_KEY))
    if not symbol or symbol == "None":
        raise KeyError(
            f"signal_strategy requires {_BOT_SYMBOL_KEY!r} in params "
            "(normally injected by BotRegistry.build).",
        )
    source = _build_signal_source(params, symbol)
    return SignalStrategy(
        symbol=symbol,
        source=source,
        max_signals_per_bar=int(params.get("max_signals_per_bar", 1)),
    )


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
        self.register_strategy("orb_5m_tiered", _build_orb_5m_tiered)
        self.register_strategy("trend_ema_pullback", _build_trend_ema_pullback)
        self.register_strategy("mean_reversion_bb", _build_mean_reversion)
        self.register_strategy("signal_strategy", _build_signal_strategy)
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

    def build(
        self,
        spec: BotSpec,
        *,
        broker: ExecutionClient,
        profile_overlay: dict[str, Any] | None = None,
    ) -> ResolvedBot:
        """Resolve the spec into live components wired to the shared broker.

        `profile_overlay` (Plan 23): when set, deep-merged into
        `strategy_params/risk_params/schedule_params` before factory lookup
        so per-user customization takes effect without touching the YAML.
        """
        if profile_overlay:
            # Lazy import — bot.dashboard.v2 has no other runtime imports and
            # we want to keep BotRegistry's module-level import graph minimal.
            from bot.dashboard.v2.profiles import ProfileOverlay
            spec = ProfileOverlay.apply(spec, profile_overlay)
        if spec.strategy_id not in self._strategies:
            raise KeyError(f"unknown strategy_id: {spec.strategy_id!r}")
        if spec.risk_policy not in self._policies:
            raise KeyError(f"unknown risk_policy: {spec.risk_policy!r}")
        if spec.schedule_type not in self._schedules:
            raise KeyError(f"unknown schedule_type: {spec.schedule_type!r}")

        # Plan 20: reject 24/7 schedules on Combine accounts at boot time.
        # Runs after the registration checks so users see "unknown strategy_id"
        # before "incompatible schedule x policy" if both apply.
        validate_schedule_x_policy(spec.schedule_type, spec.risk_policy)

        # signal_strategy needs the bot's contract symbol but the registry
        # API only forwards strategy_params. Inject the symbol via a
        # synthetic params key for this id only — other factories see their
        # params unchanged. Keeps the registration API at (params)->Strategy
        # without leaking spec details into every factory.
        if spec.strategy_id == "signal_strategy":
            strategy_params = {
                **spec.strategy_params,
                _BOT_SYMBOL_KEY: spec.symbol,
            }
        else:
            strategy_params = dict(spec.strategy_params)
        strategy = self._strategies[spec.strategy_id](strategy_params)
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
