"""BacktestEngine — ties Strategy + TopstepRiskGate + SimExecutionClient
+ AccountStateTracker into a single Bar-driven backtest loop.

Per-bar sequence (spec: Plan 4 architecture line):
  1. tracker.mark_to_market(bar)         — fold bar.close into unrealized P&L
  2. state = tracker.snapshot(bar.ts)    — emit fresh AccountState
  3. gate.on_tick(state)                 — drive the policy state machine
     (Combine MLL ratchet, force-flatten scheduling)
  4. intents = strategy.on_bar(bar, state)
  5. for each intent: gate.approve_or_deny → if approved, tracker.record_fill
     + sim place + sim execute_fill at bar.close

Note on dual high-water bookkeeping: gate.on_tick returns an updated
AccountState (with high_water / is_locked toggled by the phantom-MLL policy).
The tracker keeps its OWN view of high-water for the snapshot it builds next
bar. The gate's returned state is what we feed to approve_or_deny so the gate's
policy state is authoritative for rule checks. The tracker's high-water is
kept for the AccountState fields the gate's policy doesn't write to and for
TradeLog.final_state.

Plan 7 T8: optional `journal` parameter — if provided, every fill, every gate
decision, and a per-bar equity snapshot is persisted. Journal calls are async
(aiosqlite), so the journal path goes through `run_async()`. The legacy sync
`run()` works for journal-less backtests and is preserved unchanged.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.strategy import Strategy
from bot.backtest.tracker import AccountStateTracker
from bot.journal.journal import Journal
from bot.risk.gate import TopstepRiskGate
from bot.types import (
    AccountState,
    ApprovedOrder,
    Bar,
    OrderDenied,
    OrderEvent,
    OrderIntent,
)


@dataclass
class TradeLog:
    """Result of a backtest run.

    `approved_orders` pairs each post-buffer-augmentation intent with the
    resulting fill event in the order they happened. OrderEvent has no side
    field, so downstream consumers (TradeReport, RuleReplayReporter) need the
    intent to reconstruct round-trips and signed quantities.
    """
    final_state: AccountState
    intents_emitted: int = 0
    intents_approved: int = 0
    intents_denied: list[OrderDenied] = field(default_factory=list)
    fills: list[OrderEvent] = field(default_factory=list)
    approved_orders: list[tuple[OrderIntent, OrderEvent]] = field(default_factory=list)


@dataclass
class _BarOutcome:
    """Per-bar pure-Python result, separated from the journal-write side effects.

    The run loop iterates bars and collects these; run/run_async then either
    skip the journal step or persist them.
    """
    state_after_on_tick: AccountState
    final_snapshot: AccountState
    decisions: list[ApprovedOrder | OrderDenied] = field(default_factory=list)
    fills: list[OrderEvent] = field(default_factory=list)
    approved_orders: list[tuple[OrderIntent, OrderEvent]] = field(default_factory=list)


class BacktestEngine:
    """Drives a backtest over an iterable of Bars."""

    def __init__(
        self,
        *,
        strategy: Strategy,
        gate: TopstepRiskGate,
        tracker: AccountStateTracker,
        sim: SimExecutionClient,
        symbol: str,
        journal: Journal | None = None,
    ) -> None:
        self._strategy = strategy
        self._gate = gate
        self._tracker = tracker
        self._sim = sim
        self._symbol = symbol
        self._journal = journal

    # ---- Sync entrypoint (journal-less) ------------------------------------

    def run(self, bars: Iterable[Bar]) -> TradeLog:
        """Synchronous backtest over `bars`. Journal MUST be None.

        For the journal-backed path use `run_async()`. Splitting the surface
        keeps the no-journal call sites (existing Plan 4 tests + CLI) sync.
        """
        if self._journal is not None:
            raise RuntimeError(
                "engine was constructed with journal=...; use run_async() instead"
            )
        return self._run_collect(bars)[0]

    # ---- Async entrypoint (journal-backed) ---------------------------------

    async def run_async(self, bars: Iterable[Bar]) -> TradeLog:
        """Async backtest — required when journal is set.

        Iterates bars synchronously (the simulation itself doesn't need a
        loop) then awaits journal writes between bars. Bars are fully
        materialised first; if you need streaming, file a Plan 9 ticket.
        """
        log, per_bar = self._run_collect(bars)
        if self._journal is not None:
            for outcome in per_bar:
                await self._journal.record_equity_snapshot(outcome.state_after_on_tick)
                for decision in outcome.decisions:
                    if isinstance(decision, ApprovedOrder):
                        await self._journal.record_risk_decision(
                            intent=decision.intent, approved=True,
                            rule=None, reason=None,
                            timestamp=decision.timestamp,
                        )
                    else:
                        await self._journal.record_risk_decision(
                            intent=decision.intent, approved=False,
                            rule=decision.rule, reason=decision.reason,
                            timestamp=decision.timestamp,
                        )
                for event in outcome.fills:
                    await self._journal.record_fill(event)
        return log

    # ---- Shared bar loop ---------------------------------------------------

    def _run_collect(
        self, bars: Iterable[Bar],
    ) -> tuple[TradeLog, list[_BarOutcome]]:
        """Iterate bars; return both the legacy TradeLog and the per-bar
        outcomes the async path needs for journal writes."""
        intents_emitted = 0
        intents_approved = 0
        intents_denied: list[OrderDenied] = []
        fills: list[OrderEvent] = []
        approved_orders: list[tuple[OrderIntent, OrderEvent]] = []
        per_bar: list[_BarOutcome] = []
        last_state: AccountState | None = None

        for bar in bars:
            self._tracker.mark_to_market(bar)
            state = self._tracker.snapshot(timestamp=bar.timestamp)
            state = self._gate.on_tick(state)
            last_state = state

            outcome = _BarOutcome(state_after_on_tick=state, final_snapshot=state)

            intents = list(self._strategy.on_bar(bar, state))
            intents_emitted += len(intents)
            for intent in intents:
                decision = self._gate.approve_or_deny(intent, state)
                outcome.decisions.append(decision)
                if isinstance(decision, ApprovedOrder):
                    approved = decision.intent  # post-buffer-augmentation
                    fill_price = bar.close      # sim fills at current bar close
                    self._tracker.record_fill(
                        symbol=approved.symbol,
                        signed_qty=approved.signed_qty(),
                        fill_price=fill_price,
                        ts=bar.timestamp,
                    )
                    self._sim.register_intent(approved)
                    event = self._sim.execute_fill(approved, fill_price, bar.timestamp)
                    fills.append(event)
                    approved_orders.append((approved, event))
                    outcome.fills.append(event)
                    outcome.approved_orders.append((approved, event))
                    intents_approved += 1
                else:
                    intents_denied.append(decision)

            # Refresh snapshot after any fills so final_state reflects them.
            last_state = self._tracker.snapshot(timestamp=bar.timestamp)
            outcome.final_snapshot = last_state
            per_bar.append(outcome)

        final_state = (
            last_state if last_state is not None
            else self._tracker.snapshot(timestamp=datetime.fromtimestamp(0, tz=UTC))
        )
        log = TradeLog(
            final_state=final_state,
            intents_emitted=intents_emitted,
            intents_approved=intents_approved,
            intents_denied=intents_denied,
            fills=fills,
            approved_orders=approved_orders,
        )
        return log, per_bar
