"""TopstepRiskGate — the single, mandatory choke point between Strategy
decisions and broker order placement.

Spec: 04. A bug here is real-money loss; every rule has property + scenario +
boundary tests.

Tasks 8-15 add the seven rule checks + stop-offset buffer.
Tasks 16-17 add on_tick + force_flatten.
"""
from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from bot.execution.ports import ExecutionClient
from bot.risk.cancel_tracker import RollingRatioTracker
from bot.risk.config import RiskConfig
from bot.risk.news import NewsCalendar
from bot.risk.policies import DrawdownPolicy
from bot.types import (
    AccountState,
    ApprovedOrder,
    OrderDenied,
    OrderIntent,
)


@runtime_checkable
class _Telemetry(Protocol):
    """Minimal Protocol for telemetry; satisfied by Plan 7's full impl."""
    def alert(self, kind: str, **kw: object) -> None: ...


@runtime_checkable
class JournalProvider(Protocol):
    """Read-only journal view for rule 6 (consistency).

    Satisfied by Plan 7's SQLite-backed journal; Plan 3 uses a no-op default
    so existing tests don't need to inject one.
    """
    def best_day_pnl_so_far(self) -> float: ...
    def net_pnl_so_far(self) -> float: ...


class _NoopJournalProvider:
    """Default journal — returns zero, never triggers consistency rule."""
    def best_day_pnl_so_far(self) -> float: return 0.0
    def net_pnl_so_far(self) -> float: return 0.0


class TopstepRiskGate:
    """Pre-trade rule check + tick-driven state updates + force-flatten triggers."""

    _TICK_VALUES: ClassVar[dict[str, float]] = {"MNQ": 0.50, "NQ": 5.00}
    _DLL_AMOUNT: ClassVar[float] = 1_000.0
    _PROFIT_TARGET_50K: ClassVar[float] = 3_000.0  # Combine $50K pass threshold

    def __init__(
        self,
        *,
        policy: DrawdownPolicy,
        news_calendar: NewsCalendar,
        execution_client: ExecutionClient,
        telemetry: _Telemetry,
        config: RiskConfig,
        journal_provider: JournalProvider | None = None,
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
        self.journal_provider: JournalProvider = journal_provider or _NoopJournalProvider()
        self.cancel_to_fill_tracker = RollingRatioTracker(window_minutes=60)
        self._flattening = False

    def approve_or_deny(
        self, intent: OrderIntent, state: AccountState,
    ) -> ApprovedOrder | OrderDenied:
        """Pre-trade gate. Spec 04 §3.2."""
        decision = self._check_hard_flat(intent, state)
        if decision is not None:
            return decision

        decision = self._check_dll(intent, state)
        if decision is not None:
            return decision

        decision = self._check_mll(intent, state)
        if decision is not None:
            return decision

        decision = self._check_max_position(intent, state)
        if decision is not None:
            return decision

        decision = self._check_news_throttle(intent, state)
        if decision is not None:
            return decision

        decision = self._check_consistency(intent, state)
        if decision is not None:
            return decision

        decision = self._check_hft_ratio(intent, state)
        if decision is not None:
            return decision

        return ApprovedOrder(
            intent=intent, state_snapshot=state, timestamp=state.timestamp,
        )

    def _check_hard_flat(
        self, intent: OrderIntent, state: AccountState,
    ) -> OrderDenied | None:
        """Rule 1: hard-flat clock check. Spec 04 §3.2."""
        from datetime import time
        from zoneinfo import ZoneInfo

        now_ct = state.timestamp.astimezone(ZoneInfo("America/Chicago"))
        now_t = now_ct.time()

        is_open = intent.is_open_increasing_exposure(state.open_positions)
        if now_t >= time(15, 10):
            if is_open:
                return OrderDenied(
                    intent=intent, reason="hard-flat 15:10 CT passed",
                    rule="HARD_FLAT_CLOCK",
                    state_snapshot=state, timestamp=state.timestamp,
                )
        elif now_t >= time(15, 0):
            if is_open:
                return OrderDenied(
                    intent=intent, reason="approaching hard-flat 15:10 CT",
                    rule="HARD_FLAT_PREEMPT",
                    state_snapshot=state, timestamp=state.timestamp,
                )
        return None

    def _worst_case_loss(self, intent: OrderIntent) -> float:
        """stop_distance_ticks * tick_value * qty."""
        if intent.bracket is None:
            return 0.0
        return (intent.bracket.stop_loss_ticks
                * self._TICK_VALUES[intent.symbol]
                * abs(intent.quantity))

    def _check_dll(
        self, intent: OrderIntent, state: AccountState,
    ) -> OrderDenied | None:
        """Rule 2: Daily Loss Limit + stop-required sub-check."""
        # Sub-check 2a: open-exposure orders REQUIRE a bracket stop
        if intent.is_market_or_limit_open() and (
            intent.bracket is None or intent.bracket.stop_loss_ticks is None
        ):
            # Closes (reducing orders) don't need stops
            if intent.is_open_increasing_exposure(state.open_positions):
                return OrderDenied(
                    intent=intent, reason="open-exposure order missing bracket stop",
                    rule="STOP_REQUIRED",
                    state_snapshot=state, timestamp=state.timestamp,
                )

        worst = self._worst_case_loss(intent)
        projected_realized = state.realized_pnl_today - worst
        if projected_realized <= -self._DLL_AMOUNT:
            return OrderDenied(
                intent=intent, reason="DLL would be breached",
                rule="DLL",
                state_snapshot=state, timestamp=state.timestamp,
            )
        return None

    def _check_mll(
        self, intent: OrderIntent, state: AccountState,
    ) -> OrderDenied | None:
        """Rule 3: MLL phantom check."""
        phantom = self.policy.phantom_mll(state)
        projected_floor = state.equity - self._worst_case_loss(intent)
        if projected_floor < phantom:
            return OrderDenied(
                intent=intent, reason="MLL phantom would be breached",
                rule="MLL",
                state_snapshot=state, timestamp=state.timestamp,
            )
        return None

    def _check_max_position(
        self, intent: OrderIntent, state: AccountState,
    ) -> OrderDenied | None:
        """Rule 4: per-symbol position cap. Spec 04 §3.2 rule 4.

        Cap comes from the active DrawdownPolicy (Combine: fixed 5 NQ / 50 MNQ
        at $50K; EFA: profit-gated 2/3/5 minis verified 2026-05-22).
        """
        current = state.open_positions.get(intent.symbol, 0)
        projected = current + intent.signed_qty()
        cap = self.policy.max_position(intent.symbol, state)
        if abs(projected) > cap:
            return OrderDenied(
                intent=intent,
                reason=f"projected |{projected}| > cap {cap} for {intent.symbol}",
                rule="MAX_POSITION",
                state_snapshot=state, timestamp=state.timestamp,
            )
        return None

    def _check_news_throttle(
        self, intent: OrderIntent, state: AccountState,
    ) -> OrderDenied | None:
        """Rule 5: news-window position cap. Spec 04 §3.2 rule 5.

        Only applies to OPEN-INCREASING orders during a high-impact news window.
        Reducers and orders outside windows are allowed regardless of size.
        """
        if not self.news_calendar.in_window(state.timestamp):
            return None
        # Spec §3.2 rule 5: window only caps OPENING + sizing orders.
        if not intent.is_open_increasing_exposure(state.open_positions):
            return None
        current = state.open_positions.get(intent.symbol, 0)
        projected = abs(current + intent.signed_qty())
        news_cap = self.news_calendar.max_position_during_window()
        if projected > news_cap:
            return OrderDenied(
                intent=intent,
                reason=f"news window: |{projected}| > cap {news_cap}",
                rule="NEWS_THROTTLE",
                state_snapshot=state, timestamp=state.timestamp,
            )
        return None

    def _check_consistency(
        self, intent: OrderIntent, state: AccountState,
    ) -> OrderDenied | None:
        """Rule 6: Combine consistency (best-day/target <= 50%).

        Default mode = soft (warn-only). Hard mode denies. EFA accounts skip
        this rule (their analogous 40% rule applies at payout time, not per
        trade — see EFAConsistencyDrawdown.gate_payout).
        """
        if not state.is_combine:
            return None
        best_day = self.journal_provider.best_day_pnl_so_far()
        net_pnl = self.journal_provider.net_pnl_so_far()
        target_remaining = self._PROFIT_TARGET_50K - net_pnl
        if target_remaining <= 0:
            return None
        if (best_day / target_remaining) <= 0.50:
            return None
        if self.config.consistency_mode == "hard":
            return OrderDenied(
                intent=intent,
                reason=f"consistency 50% breach: best_day={best_day} target_remaining={target_remaining}",
                rule="CONSISTENCY_HARD",
                state_snapshot=state, timestamp=state.timestamp,
            )
        self.telemetry.alert(
            "CONSISTENCY_50PCT_EXCEEDED",
            best_day=best_day, target_remaining=target_remaining,
        )
        return None

    def _check_hft_ratio(
        self, intent: OrderIntent, state: AccountState,
    ) -> OrderDenied | None:
        """Rule 7: HFT defensive cap (cancel-to-fill ratio over rolling 60 min)."""
        ratio = self.cancel_to_fill_tracker.ratio(now=state.timestamp)
        if ratio > self.config.hft_cancel_to_fill_threshold:
            return OrderDenied(
                intent=intent,
                reason=f"cancel/fill ratio {ratio:.2f} > threshold {self.config.hft_cancel_to_fill_threshold}",
                rule="HFT_DEFENSIVE",
                state_snapshot=state, timestamp=state.timestamp,
            )
        return None
