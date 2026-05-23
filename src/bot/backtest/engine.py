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
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.strategy import Strategy
from bot.backtest.tracker import AccountStateTracker
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
    ) -> None:
        self._strategy = strategy
        self._gate = gate
        self._tracker = tracker
        self._sim = sim
        self._symbol = symbol

    def run(self, bars: Iterable[Bar]) -> TradeLog:
        intents_emitted = 0
        intents_approved = 0
        intents_denied: list[OrderDenied] = []
        fills: list[OrderEvent] = []
        approved_orders: list[tuple[OrderIntent, OrderEvent]] = []
        last_state: AccountState | None = None
        for bar in bars:
            self._tracker.mark_to_market(bar)
            state = self._tracker.snapshot(timestamp=bar.timestamp)
            state = self._gate.on_tick(state)
            last_state = state

            intents = list(self._strategy.on_bar(bar, state))
            intents_emitted += len(intents)
            for intent in intents:
                decision = self._gate.approve_or_deny(intent, state)
                if isinstance(decision, ApprovedOrder):
                    approved = decision.intent  # post-buffer-augmentation
                    fill_price = bar.close      # sim fills at current bar close
                    self._tracker.record_fill(
                        symbol=approved.symbol,
                        signed_qty=approved.signed_qty(),
                        fill_price=fill_price,
                        ts=bar.timestamp,
                    )
                    # Sync place + fill in the sim ledger.
                    self._sim.register_intent(approved)
                    event = self._sim.execute_fill(approved, fill_price, bar.timestamp)
                    fills.append(event)
                    approved_orders.append((approved, event))
                    intents_approved += 1
                else:
                    intents_denied.append(decision)

            # Refresh snapshot after any fills so final_state reflects them.
            last_state = self._tracker.snapshot(timestamp=bar.timestamp)

        final_state = (
            last_state if last_state is not None
            else self._tracker.snapshot(timestamp=datetime.fromtimestamp(0, tz=UTC))
        )
        return TradeLog(
            final_state=final_state,
            intents_emitted=intents_emitted,
            intents_approved=intents_approved,
            intents_denied=intents_denied,
            fills=fills,
            approved_orders=approved_orders,
        )
