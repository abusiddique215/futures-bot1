"""SignalStrategy — consumes a SignalSource → emits OrderIntents.

This is the bridge between async signal ingestion (Discord, fixture, future
webhook sources) and the synchronous Strategy.on_bar protocol consumed by
LiveTradingLoop.

Lifecycle:
  1. Caller constructs SignalStrategy(symbol=..., source=...).
  2. Caller calls `start()` to spawn the background pump task that reads
     `source.iter_signals()` and pushes events to an internal deque.
  3. Each LiveTradingLoop tick drives `on_bar(bar, state)`, which drains
     up to `max_signals_per_bar` matching events from the deque and emits
     OrderIntents.
  4. Caller calls `stop()` at shutdown to cancel the pump.

The deque-based seam decouples async ingestion from synchronous per-bar
draining: the gate + journal write paths stay synchronous, and tests can
inject events directly via `inject()` without exercising the pump.

Symbol matching: the signal's `symbol` matches the bot's `symbol` if either
is a prefix of the other (case-sensitive). This handles the common case where
a signal channel posts root symbols ("NQ", "MNQ") and the bot is configured
for a contract-month code ("MNQH26"). Strict mismatches (e.g. "ES" → "MNQ"
bot) are dropped.

Qty: passed through to the OrderIntent verbatim. TopstepRiskGate's
MAX_POSITION check is the single chokepoint that caps oversize signals
— there is no second cap here by design.

Provenance: the OrderIntent's `client_order_id` embeds the signal's
`source_id` so the journal + dashboard can trace any broker order back
to the originating Discord message.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Iterable

from bot.markets.registry import get_market
from bot.signals.source import SignalEvent, SignalSource
from bot.types import AccountState, Bar, Bracket, OrderIntent

log = logging.getLogger(__name__)


class SignalStrategy:
    """Strategy that emits OrderIntents driven by an external SignalSource.

    Implements the `bot.backtest.strategy.Strategy` Protocol (sync `on_bar`).
    The async signal source is read by a background pump task; tests can
    bypass the pump via `inject(event)` and exercise on_bar directly.
    """

    def __init__(
        self,
        *,
        symbol: str,
        source: SignalSource | None = None,
        max_signals_per_bar: int = 1,
        max_queue_size: int = 1000,
    ) -> None:
        if max_signals_per_bar < 1:
            raise ValueError("max_signals_per_bar must be >= 1")
        self._symbol = symbol
        self._source = source
        self._max_per_bar = max_signals_per_bar
        self._queue: deque[SignalEvent] = deque(maxlen=max_queue_size)
        self._pump_task: asyncio.Task[None] | None = None
        self._intent_counter = 0
        # Tick size resolved up front so the price → ticks conversion in
        # on_bar fails loud at init if the symbol isn't in the registry.
        self._tick_size = get_market(symbol).tick_size

    # ---- Lifecycle ---------------------------------------------------------

    def start(self) -> asyncio.Task[None]:
        """Spawn the background pump task. Idempotent: returns existing task
        if already started. Raises RuntimeError if no source was provided.
        """
        if self._source is None:
            raise RuntimeError(
                "SignalStrategy.start() requires a SignalSource — "
                "construct with source=... or use inject() in tests.",
            )
        if self._pump_task is not None and not self._pump_task.done():
            return self._pump_task
        self._pump_task = asyncio.create_task(
            self._pump(), name=f"signal_pump:{self._symbol}",
        )
        return self._pump_task

    async def stop(self) -> None:
        """Cancel the pump task and await its exit."""
        if self._pump_task is None:
            return
        self._pump_task.cancel()
        try:
            await self._pump_task
        except (asyncio.CancelledError, Exception) as e:
            log.debug("signal pump exited: %s", e)
        finally:
            self._pump_task = None

    async def _pump(self) -> None:
        """Background task: copy events from the async source into the deque."""
        assert self._source is not None
        async for event in self._source.iter_signals():
            if len(self._queue) >= (self._queue.maxlen or 0):
                log.warning(
                    "signal queue full (max=%d), dropping event %s",
                    self._queue.maxlen, event.source_id,
                )
                continue
            self._queue.append(event)

    # ---- Test seams --------------------------------------------------------

    def inject(self, event: SignalEvent) -> None:
        """Push an event directly to the queue — bypasses the pump.

        Used by tests and by the FixtureSignalSource integration path
        when we want deterministic per-bar timing.
        """
        self._queue.append(event)

    def pending_count(self) -> int:
        """Number of events buffered, awaiting an on_bar drain."""
        return len(self._queue)

    # ---- Strategy protocol -------------------------------------------------

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        """Drain up to `max_signals_per_bar` matching events; emit intents.

        Non-matching events (wrong symbol) are dropped without affecting
        the per-bar quota — they were already in the queue when on_bar
        was called, so spending a quota slot on them would starve real
        signals.
        """
        _ = state  # account state unused — gate enforces all risk policy
        out: list[OrderIntent] = []
        # Scan from the front; drop mismatches, keep matches up to the cap.
        # Anything still in the queue after the cap is hit is retained for
        # the next bar.
        remaining: deque[SignalEvent] = deque()
        emitted = 0
        while self._queue:
            event = self._queue.popleft()
            if not self._symbols_match(event.symbol, self._symbol):
                log.info(
                    "signal: dropping wrong-symbol event %s "
                    "(signal=%s, bot=%s)",
                    event.source_id, event.symbol, self._symbol,
                )
                continue
            if emitted >= self._max_per_bar:
                remaining.append(event)
                continue
            out.append(self._build_intent(event, bar))
            emitted += 1
        # Restore retained events (and anything we never visited because
        # the while drained the queue).
        self._queue.extendleft(reversed(remaining))
        return out

    # ---- Internals ---------------------------------------------------------

    @staticmethod
    def _symbols_match(signal_symbol: str, bot_symbol: str) -> bool:
        """True iff either symbol is a prefix of the other.

        Handles "NQ" or "MNQ" signal → "MNQH26" bot, and exact matches.
        Rejects unrelated roots ("ES" vs "MNQ").
        """
        return (
            signal_symbol == bot_symbol
            or signal_symbol.startswith(bot_symbol)
            or bot_symbol.startswith(signal_symbol)
        )

    def _build_intent(self, event: SignalEvent, bar: Bar) -> OrderIntent:
        self._intent_counter += 1
        cid = f"signal-{event.source_id}-{self._intent_counter}"
        order_type = "LIMIT" if event.limit_price is not None else "MARKET"
        bracket = self._build_bracket(event)
        # Use the bot's configured symbol downstream (not the signal's) —
        # the bot is wired to one specific contract month; the signal
        # might use the root.
        return OrderIntent(
            symbol=self._symbol,
            side=event.side,
            quantity=event.qty,
            order_type=order_type,  # type: ignore[arg-type]
            client_order_id=cid,
            timestamp=bar.timestamp,
            limit_price=event.limit_price,
            bracket=bracket,
        )

    def _build_bracket(self, event: SignalEvent) -> Bracket | None:
        """Convert absolute SL/TP prices into tick offsets.

        Both legs use the same reference price. For BUY: SL is below entry,
        TP above. For SELL: reversed. We take absolute distance so the
        bracket fields are always positive — direction is encoded in the
        intent's side.

        If no stop_loss given → no bracket. If stop_loss given without
        take_profit → TP defaults to the same distance as SL (1:1).
        """
        if event.stop_loss is None:
            return None
        # Need a reference price. Use limit_price if available, else SL itself
        # can't anchor — fall back to no bracket (we'd need a market entry
        # price to anchor, which we don't know at signal time).
        if event.limit_price is None:
            return None
        sl_distance = abs(event.limit_price - event.stop_loss)
        sl_ticks = max(1, round(sl_distance / self._tick_size))
        if event.take_profit is not None:
            tp_distance = abs(event.take_profit - event.limit_price)
            tp_ticks = max(1, round(tp_distance / self._tick_size))
        else:
            tp_ticks = sl_ticks  # 1:1 default
        return Bracket(stop_loss_ticks=sl_ticks, take_profit_ticks=tp_ticks)
