"""LiveTradingLoop — the live counterpart to BacktestEngine.

Per-bar pipeline (mirrors `BacktestEngine._run_collect`):
  0. break if stop_event is set                  — SIGTERM clean shutdown (T4)
  1. await gate.force_flatten_now()              — drain pending flatten from last iter
  2. tracker.mark_to_market(bar)
  3. state = tracker.snapshot(bar.timestamp)
  4. state = gate.on_tick(state)                 — state-machine update; may schedule flatten
  5. intents = strategy.on_bar(bar, state)
  6. for each intent: gate.approve_or_deny → if approved, sim place + record fill +
     journal record. If denied, journal record decision.
  7. journal record_equity_snapshot
  8. heartbeat write (if 30s elapsed since last)
  9. break if max_bars reached

On shutdown (stop_event set), the loop:
  - calls `gate.force_flatten_now("SHUTDOWN")` — cancels open orders, closes
    positions at the broker, permanently disables the strategy
  - returns control to the caller (main.py) which closes broker + journal
    in its finally block
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.strategy import Strategy
from bot.backtest.tracker import AccountStateTracker
from bot.journal.journal import Journal
from bot.risk.gate import TopstepRiskGate
from bot.runtime.bar_source import LiveBarSource
from bot.runtime.fleet.allocator import FleetAllocator
from bot.runtime.fleet.schedule import AlwaysOn, Schedule
from bot.runtime.heartbeat import Heartbeat
from bot.types import AccountState, ApprovedOrder, Bar


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
        schedule: Schedule | None = None,
        allocator: FleetAllocator | None = None,
        bot_name: str | None = None,
        fleet_positions_fn: Callable[[], dict[str, dict[str, int]]] | None = None,
    ) -> None:
        self._strategy = strategy
        self._gate = gate
        self._tracker = tracker
        self._broker = broker
        self._journal = journal
        self._telemetry = telemetry
        self._heartbeat = Heartbeat(heartbeat_path)
        self._symbol = symbol
        # Per-bot trading window. Defaults to AlwaysOn so single-bot callers
        # see no behavior change.
        self._schedule: Schedule = schedule if schedule is not None else AlwaysOn()
        # Plan 21: optional fleet-wide allocator runs AFTER per-bot gate.
        # If allocator is set, bot_name and fleet_positions_fn must also be
        # set so approve_intent has the context it needs.
        self._allocator = allocator
        self._bot_name = bot_name
        self._fleet_positions_fn = fleet_positions_fn
        if allocator is not None and (bot_name is None or fleet_positions_fn is None):
            raise ValueError(
                "LiveTradingLoop: allocator requires bot_name + fleet_positions_fn",
            )

    def _bot_label(self) -> str:
        """Stable identity for telemetry events. Falls back to symbol."""
        return self._bot_name or self._symbol

    def _bot_state(self, state: AccountState) -> str:
        """Derived bot-lifecycle state used in account_update events.

        DISABLED       — gate has permanently disabled the strategy (post-flatten).
        IN_TRADE       — at least one contract open on the bot's symbol.
        ARMED_WAITING  — enabled, no position, ready for entry.
        """
        if getattr(self._gate, "_strategy_disabled", False):
            return "DISABLED"
        # Bot is in a trade if there's any open contract on its symbol.
        for sym, qty in state.open_positions.items():
            if qty != 0 and (sym == self._symbol or sym.startswith(self._symbol)):
                return "IN_TRADE"
        return "ARMED_WAITING"

    def _emit_per_bar_events(self, bar: Bar, state: AccountState) -> None:
        """Publish bar_tick + account_update + bot_intent for this bar.

        Distance fields are computed here so the dashboard never reaches
        into the policy. Errors during emit are intentionally not caught —
        TelemetryBus already isolates sink failures, and a bug in our
        emit path should fail loudly in tests.
        """
        # bar_tick
        self._telemetry.alert(
            "bar_tick",
            bot=self._bot_label(),
            symbol=bar.symbol,
            bar={
                "ts": bar.timestamp,
                "o": bar.open, "h": bar.high, "low": bar.low,
                "c": bar.close, "v": bar.volume,
            },
        )
        # account_update with derived risk-header fields.
        policy = self._gate.policy
        phantom = policy.phantom_mll(state)
        distance_to_mll = state.equity - phantom
        # distance_to_target is Combine-only ($3K pass threshold for $50K).
        if state.is_combine:
            target = state.start_balance + self._gate._PROFIT_TARGET_50K
            distance_to_target: float | None = target - state.equity
        else:
            distance_to_target = None
        contracts_open = sum(abs(q) for q in state.open_positions.values())
        # Topstep DLL = $1000 cap on realized loss in a single day.
        dll_remaining = max(0.0, self._gate._DLL_AMOUNT - max(
            0.0, -state.realized_pnl_today,
        ))
        self._telemetry.alert(
            "account_update",
            bot=self._bot_label(),
            state=self._bot_state(state),
            equity=state.equity,
            balance=state.start_balance,
            realized_pnl_today=state.realized_pnl_today,
            unrealized_pnl=state.unrealized_pnl,
            high_water=state.high_water_equity,
            distance_to_mll=distance_to_mll,
            distance_to_target=distance_to_target,
            contracts_open=contracts_open,
            dll_remaining=dll_remaining,
        )
        # bot_intent — extracted from the strategy + schedule. Imported
        # lazily so live_loop doesn't take a dashboard dependency at import
        # time (keeps the runtime install minimal if dashboard ever splits).
        from bot.dashboard.v2.intent import extract_intent
        try:
            intent_payload = extract_intent(
                self._strategy, bar,
                {
                    "equity": state.equity,
                    "open_positions": dict(state.open_positions),
                    "high_water_equity": state.high_water_equity,
                },
                schedule=self._schedule,
                now=bar.timestamp,
            )
        except Exception:  # pragma: no cover — defensive
            intent_payload = {
                "watching_for": "Watching for entry signal",
                "schedule_open": self._schedule.should_trade(bar.timestamp),
                "next_window_opens_in_seconds": None,
                "max_trades_remaining": None,
            }
        self._telemetry.alert(
            "bot_intent",
            bot=self._bot_label(),
            **intent_payload,
        )

    def _emit_fill_event(
        self,
        intent: object,
        fill_price: float,
        timestamp: object,
    ) -> None:
        # `intent` is an OrderIntent; declared `object` to avoid widening the
        # signature beyond what the caller already has.
        from bot.types import OrderIntent
        if not isinstance(intent, OrderIntent):
            return  # defensive — caller always passes OrderIntent
        self._telemetry.alert(
            "fill",
            bot=self._bot_label(),
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            fill_price=fill_price,
            timestamp=timestamp,
            client_order_id=intent.client_order_id,
        )

    async def run(
        self,
        bar_source: LiveBarSource,
        *,
        max_bars: int | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Consume `bar_source`'s subscribe() stream and run the bot pipeline.

        Returns when the source exhausts itself, when `max_bars` bars have
        been processed, or when `stop_event` is set (SIGTERM shutdown).

        On shutdown a force-flatten is issued so any open position is closed
        before control returns; the strategy is then permanently disabled by
        the gate for the rest of the session.
        """
        bars_seen = 0
        async for bar in bar_source.subscribe():
            # 0. Shutdown check — runs BEFORE we touch the bar so the loop
            #    can't half-process a bar (snapshot one bar, fail to write the
            #    fill, etc.).
            if stop_event is not None and stop_event.is_set():
                await self._gate.force_flatten_now("SHUTDOWN")
                return
            # 1. Drain any pending flatten request scheduled by the previous
            #    iteration's on_tick. No-op if nothing pending.
            await self._gate.force_flatten_now()

            # 2-3. Mark-to-market + snapshot.
            self._tracker.mark_to_market(bar)
            state = self._tracker.snapshot(timestamp=bar.timestamp)

            # 4. State machine tick. May schedule flatten for NEXT iteration.
            state = self._gate.on_tick(state)

            # 5-6. Pump intents through the gate — but only while the
            #     schedule says we're in a trading window. Mark-to-market,
            #     equity snapshots, and heartbeat keep running regardless.
            if not self._schedule.should_trade(bar.timestamp):
                final_state = self._tracker.snapshot(timestamp=bar.timestamp)
                await self._journal.record_equity_snapshot(final_state)
                # Plan 23 T3: dashboards want bar/account/intent events even
                # outside the trading window — operators need to see the bot
                # is alive + see "next window in N seconds".
                self._emit_per_bar_events(bar, final_state)
                if self._heartbeat.should_write_at(bar.timestamp):
                    self._heartbeat.write_now(bar.timestamp)
                bars_seen += 1
                if max_bars is not None and bars_seen >= max_bars:
                    break
                continue
            for intent in self._strategy.on_bar(bar, state):
                decision = self._gate.approve_or_deny(intent, state)
                if isinstance(decision, ApprovedOrder):
                    approved = decision.intent
                    # Plan 21: fleet-wide cap runs AFTER the per-bot gate
                    # approves. If denied, record the decision + skip the
                    # broker call so the order never reaches the wire.
                    if self._allocator is not None:
                        fleet_decision = await self._allocator.approve_intent(
                            self._bot_name or "",  # validated in __init__
                            approved,
                            self._fleet_positions_fn() if self._fleet_positions_fn else {},
                        )
                        if not isinstance(fleet_decision, ApprovedOrder):
                            await self._journal.record_risk_decision(
                                intent=fleet_decision.intent, approved=False,
                                rule=fleet_decision.rule,
                                reason=fleet_decision.reason,
                                timestamp=fleet_decision.timestamp,
                            )
                            continue
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
                    # Plan 23 T3: publish a `fill` event for the dashboard's
                    # live trade-log panel. Always references bar.close to
                    # match the sim fill above; the broker's actual fill
                    # price would be wired here for live mode.
                    self._emit_fill_event(approved, bar.close, bar.timestamp)
                    # Plan 21: settle the allocator pending slot now that the
                    # fill is reflected in the tracker. Next allocator call
                    # will see the settled position via fleet_positions_fn.
                    if self._allocator is not None and self._bot_name is not None:
                        self._allocator.settle_intent(self._bot_name, approved)
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

            # 7b. Plan 23 T3: per-bar telemetry for the v2 dashboard.
            self._emit_per_bar_events(bar, final_state)

            # 8. Heartbeat — first bar always writes; subsequent writes
            #    gated at 30s.
            if self._heartbeat.should_write_at(bar.timestamp):
                self._heartbeat.write_now(bar.timestamp)

            bars_seen += 1
            if max_bars is not None and bars_seen >= max_bars:
                break
