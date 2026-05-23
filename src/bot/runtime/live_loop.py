"""LiveTradingLoop — the live counterpart to BacktestEngine.

Per-bar pipeline (mirrors `BacktestEngine._run_collect`):
  1. await gate.force_flatten_now()       — drain pending flatten from last iter
  2. tracker.mark_to_market(bar)
  3. state = tracker.snapshot(bar.timestamp)
  4. state = gate.on_tick(state)          — state-machine update; may schedule flatten
  5. intents = strategy.on_bar(bar, state)
  6. for each intent: gate.approve_or_deny → if approved, sim place + record fill +
     journal record. If denied, journal record decision.
  7. journal record_equity_snapshot
  8. heartbeat write (if 30s elapsed since last)  — wired in T3
  9. break if max_bars reached

T2 ships the core loop. T3 wires the heartbeat writer; T4 wires SIGTERM shutdown.
Until those land, `heartbeat_path` is accepted by the ctor (forward-compat) but
not written, and `stop_event` is absent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.strategy import Strategy
from bot.backtest.tracker import AccountStateTracker
from bot.journal.journal import Journal
from bot.risk.gate import TopstepRiskGate
from bot.runtime.bar_source import LiveBarSource
from bot.runtime.heartbeat import Heartbeat
from bot.types import ApprovedOrder


class _Telemetry(Protocol):
    def alert(self, kind: str, **kw: object) -> None: ...


class LiveTradingLoop:
    """Async bar-stream driver. Construct once; call `run()` once per session."""

    def __init__(
        self,
        *,
        strategy: Strategy,
        gate: TopstepRiskGate,
        tracker: AccountStateTracker,
        broker: Any,
        journal: Journal,
        telemetry: _Telemetry,
        heartbeat_path: Path,
        symbol: str,
    ) -> None:
        self._strategy = strategy
        self._gate = gate
        self._tracker = tracker
        self._broker = broker
        self._journal = journal
        self._telemetry = telemetry
        self._heartbeat = Heartbeat(heartbeat_path)
        self._symbol = symbol

    async def run(
        self, bar_source: LiveBarSource, *, max_bars: int | None = None,
    ) -> None:
        """Consume `bar_source`'s subscribe() stream and run the bot pipeline.

        Returns when the source exhausts itself, when `max_bars` bars have
        been processed, or when shutdown is signalled (T4).
        """
        bars_seen = 0
        async for bar in bar_source.subscribe():
            # 1. Drain any pending flatten request scheduled by the previous
            #    iteration's on_tick. No-op if nothing pending.
            await self._gate.force_flatten_now()

            # 2-3. Mark-to-market + snapshot.
            self._tracker.mark_to_market(bar)
            state = self._tracker.snapshot(timestamp=bar.timestamp)

            # 4. State machine tick. May schedule flatten for NEXT iteration.
            state = self._gate.on_tick(state)

            # 5-6. Pump intents through the gate.
            for intent in self._strategy.on_bar(bar, state):
                decision = self._gate.approve_or_deny(intent, state)
                if isinstance(decision, ApprovedOrder):
                    approved = decision.intent
                    # Place at broker. SimExecutionClient registers + returns
                    # a PENDING event; we then materialize a FILLED at bar.close.
                    event = await self._broker.place_order(approved)
                    if isinstance(self._broker, SimExecutionClient):
                        event = self._broker.execute_fill(
                            approved, bar.close, bar.timestamp,
                        )
                    self._tracker.record_fill(
                        symbol=approved.symbol,
                        signed_qty=approved.signed_qty(),
                        fill_price=bar.close,
                        ts=bar.timestamp,
                    )
                    await self._journal.record_risk_decision(
                        intent=approved, approved=True,
                        rule=None, reason=None,
                        timestamp=decision.timestamp,
                    )
                    await self._journal.record_fill(event)
                else:
                    await self._journal.record_risk_decision(
                        intent=decision.intent, approved=False,
                        rule=decision.rule, reason=decision.reason,
                        timestamp=decision.timestamp,
                    )

            # 7. Equity snapshot at the end of the bar.
            final_state = self._tracker.snapshot(timestamp=bar.timestamp)
            await self._journal.record_equity_snapshot(final_state)

            # 8. Heartbeat — first bar always writes; subsequent writes
            #    gated at 30s.
            if self._heartbeat.should_write_at(bar.timestamp):
                self._heartbeat.write_now(bar.timestamp)

            bars_seen += 1
            if max_bars is not None and bars_seen >= max_bars:
                break
