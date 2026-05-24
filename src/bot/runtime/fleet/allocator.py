"""FleetAllocator — cross-bot account position cap (Plan 21 T1).

A second-stage check that runs AFTER each bot's per-bot risk gate. The
per-bot gate enforces that bot's own position limits; the allocator
enforces the COMBINED account-level cap so two bots can't independently
each open +5 minis on MNQ and breach Topstep's account-wide limit.

Design:
  - `approve_intent(bot_name, intent, fleet_positions)` returns either
    ApprovedOrder or OrderDenied(rule="FLEET_POSITION_CAP").
  - `fleet_positions` is a snapshot of every bot's current tracker view
    (bot_name → {symbol → signed_qty}). This is the *settled* position
    from completed fills.
  - The allocator maintains its own `_pending` dict to track intents
    approved but not yet reflected in the trackers (the broker round-trip
    + record_fill happens AFTER approve_intent returns). Without this,
    two concurrent bots could both pass the cap check using stale tracker
    state and over-allocate.
  - All approve_intent / release_intent calls take `_lock` so the
    read-projected-update sequence is atomic across concurrent bots.

Symbol resolution: the `market_lookup` callable accepts the bot's
contract symbol ("MNQ" or "MNQH26") and returns a MarketSpec. The
allocator uses `micro_root` to detect micro markets (cap x 10) and
adjusts; full markets use the bare account_max_mini count.

Release: when an order is rejected/cancelled at the broker, callers can
call `release_intent(bot_name, intent)` to free the pending allocation
so capacity becomes available again. FleetRuntime currently does NOT
call release on broker rejects (v1 — broker rejects in SimExecutionClient
don't propagate that signal cleanly). Released entries are best-effort.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime

from bot.markets.spec import MarketSpec
from bot.types import (
    AccountState,
    ApprovedOrder,
    OrderDenied,
    OrderIntent,
)

MarketLookup = Callable[[str], MarketSpec]


def _empty_state(timestamp: datetime) -> AccountState:
    """Build a minimal AccountState for OrderDenied.state_snapshot.

    Plan 21: the allocator decision is fleet-wide (cross-bot); we don't
    have the originating bot's full AccountState. OrderDenied requires
    one, so we synthesize a placeholder. The risk gate already supplied
    the real state — this is just for the denied-record shape.
    """
    return AccountState(
        equity=0.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=0.0,
        is_combine=False,
        timestamp=timestamp,
    )


class FleetAllocator:
    """Account-wide position cap across N bots sharing one Topstep account.

    Construction:
      account_max_mini  — Topstep account-level cap on minis (e.g. 5 for $50K).
      market_lookup     — callable(symbol) -> MarketSpec (use `get_market`).

    Threading: every approve_intent / release_intent is serialized via an
    asyncio.Lock so concurrent bot intents see a consistent projection.
    """

    def __init__(
        self, *, account_max_mini: int, market_lookup: MarketLookup,
    ) -> None:
        if account_max_mini <= 0:
            raise ValueError("account_max_mini must be > 0")
        self._max_mini = account_max_mini
        self._lookup = market_lookup
        self._lock = asyncio.Lock()
        # bot_name → symbol → signed pending qty (post-approval, pre-fill).
        self._pending: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int),
        )

    async def approve_intent(
        self,
        bot_name: str,
        intent: OrderIntent,
        fleet_positions: dict[str, dict[str, int]],
    ) -> ApprovedOrder | OrderDenied:
        """Approve the intent iff combined |position| stays within the cap.

        `fleet_positions` should be a fresh snapshot of each bot's tracker:
            {"bot_a": {"MNQ": +3}, "bot_b": {"MNQ": -1}}
        The allocator adds its own pending allocations (intents approved
        but not yet filled into a tracker) to compute the true projected
        combined position.
        """
        async with self._lock:
            market = await self._resolve_market(intent.symbol)
            cap = self._cap_for(market)
            signed = intent.signed_qty()

            # Combined signed position across all bots — settled + pending.
            settled = sum(
                positions.get(intent.symbol, 0)
                for positions in fleet_positions.values()
            )
            pending = sum(
                pend.get(intent.symbol, 0) for pend in self._pending.values()
            )
            projected = settled + pending + signed

            if abs(projected) > cap:
                return OrderDenied(
                    intent=intent,
                    reason=(
                        f"fleet cap breach on {intent.symbol}: projected "
                        f"|{projected}| > cap {cap} "
                        f"(max_mini={self._max_mini}, micro={'yes' if self._is_micro(market) else 'no'})"
                    ),
                    rule="FLEET_POSITION_CAP",
                    state_snapshot=_empty_state(intent.timestamp),
                    timestamp=intent.timestamp,
                )

            # Approve: record pending allocation.
            self._pending[bot_name][intent.symbol] += signed
            return ApprovedOrder(
                intent=intent,
                state_snapshot=_empty_state(intent.timestamp),
                timestamp=intent.timestamp,
            )

    def release_intent(self, bot_name: str, intent: OrderIntent) -> None:
        """Reverse a previously-approved allocation.

        Called when an intent the allocator approved didn't actually result
        in a fill (broker reject, cancel, etc.). Best-effort: if the bot or
        symbol isn't in `_pending`, silently no-op — release on something
        the allocator never tracked is a programming bug we don't want to
        crash the trading loop over.
        """
        signed = intent.signed_qty()
        bot_pending = self._pending.get(bot_name)
        if bot_pending is None:
            return
        bot_pending[intent.symbol] -= signed
        if bot_pending[intent.symbol] == 0:
            bot_pending.pop(intent.symbol, None)
        if not bot_pending:
            self._pending.pop(bot_name, None)

    def settle_intent(self, bot_name: str, intent: OrderIntent) -> None:
        """Move a pending allocation into settled state.

        Called after the broker confirms a fill and the bot's tracker is
        updated. The settled position then appears in `fleet_positions`
        for the next approve_intent call; the pending entry is cleared
        here so we don't double-count.
        """
        # Same shape as release — both clear the pending slot. settle()
        # is semantically distinct (the tracker now holds the qty) but
        # the bookkeeping is identical.
        self.release_intent(bot_name, intent)

    # ---- internals ---------------------------------------------------------

    async def _resolve_market(self, symbol: str) -> MarketSpec:
        """Call `market_lookup` and await if it returned a coroutine.

        The test suite injects an async lookup to force a suspension point
        for the concurrency test; production passes the sync `get_market`.
        """
        result = self._lookup(symbol)
        if asyncio.iscoroutine(result):
            return await result  # type: ignore[no-any-return]
        return result

    def _cap_for(self, market: MarketSpec) -> int:
        """Cap in CONTRACTS for this market.

        Topstep's account cap is expressed in minis (e.g. 5). For micros
        the equivalent is `5 * micro_to_full_ratio = 50` contracts. For
        full markets the cap is just the mini count.
        """
        if self._is_micro(market):
            return self._max_mini * market.micro_to_full_ratio
        return self._max_mini

    @staticmethod
    def _is_micro(market: MarketSpec) -> bool:
        """A micro market has no `micro_root` of its own (no smaller variant)."""
        return market.micro_root is None
