"""FleetRuntime — run N ResolvedBots concurrently with per-bot isolation.

Each bot gets its own LiveTradingLoop + Journal file; the broker and
telemetry bus are shared. `asyncio.gather(..., return_exceptions=True)`
keeps one bot's exception from crashing the rest of the fleet — we
collect per-bot `BotResult` rows describing completion / error /
bars-processed.

The heartbeat path is shared: launchd cares whether the fleet is alive,
not which bot last wrote.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bot.backtest.tracker import AccountStateTracker
from bot.execution.ports import ExecutionClient
from bot.journal.journal import Journal
from bot.runtime.bar_source import LiveBarSource
from bot.runtime.fleet.allocator import FleetAllocator
from bot.runtime.fleet.registry import ResolvedBot
from bot.runtime.fleet.spec import BotSpec
from bot.runtime.live_loop import LiveTradingLoop
from bot.types import Bar


class _Telemetry(Protocol):
    def alert(self, kind: str, **kw: object) -> None: ...


BarSourceFactory = Callable[[BotSpec], LiveBarSource]


@dataclass(frozen=True)
class BotResult:
    """Per-bot outcome of a fleet run."""

    name: str
    bars_processed: int
    error: BaseException | None


class _CountingBarSource:
    """Wraps a LiveBarSource and counts how many bars passed through."""

    def __init__(self, inner: LiveBarSource) -> None:
        self._inner = inner
        self.count = 0

    async def subscribe(self) -> AsyncIterator[Bar]:
        async for bar in self._inner.subscribe():
            self.count += 1
            yield bar


class FleetRuntime:
    """Orchestrate N ResolvedBots over a shared broker + telemetry."""

    def __init__(
        self,
        *,
        bots: list[ResolvedBot],
        broker: ExecutionClient,
        bar_source_factory: BarSourceFactory,
        telemetry: _Telemetry,
        heartbeat_path: Path,
        allocator: FleetAllocator | None = None,
    ) -> None:
        self._bots = bots
        self._broker = broker
        self._bar_source_factory = bar_source_factory
        self._telemetry = telemetry
        self._heartbeat_path = heartbeat_path
        self._allocator = allocator

    async def run(self) -> dict[str, BotResult]:
        """Run every bot concurrently. Failures stay local — caller still
        receives a BotResult for every bot, with `.error` set on failures.
        """
        if not self._bots:
            return {}

        journals: list[Journal] = []
        sources: list[_CountingBarSource] = []
        trackers: dict[str, AccountStateTracker] = {}
        try:
            tasks: list[asyncio.Task[None]] = []
            # Build all trackers first so the fleet_positions_fn (read by
            # the allocator) has every bot's tracker available even on the
            # first bar of any bot.
            for bot in self._bots:
                start_balance = float(
                    bot.spec.risk_params.get("start_balance", 50_000.0)
                )
                trackers[bot.name] = AccountStateTracker(
                    start_balance=start_balance,
                    is_combine=bot.spec.risk_policy == "combine_intraday",
                )

            def _fleet_positions() -> dict[str, dict[str, int]]:
                # Snapshot each bot's open_positions from its tracker. Reads
                # the tracker's private snapshot path (no fresh timestamp
                # needed — we only want positions). Cheaper than a per-call
                # snapshot() because we skip the AccountState construction.
                return {
                    name: dict(t._positions)
                    for name, t in trackers.items()
                }

            for bot in self._bots:
                journal = await Journal.connect(str(bot.journal_path))
                await journal.apply_migrations()
                journals.append(journal)

                source = _CountingBarSource(self._bar_source_factory(bot.spec))
                sources.append(source)

                # Plan 21: lifecycle hook. Strategies that need to spawn
                # background tasks (SignalStrategy → Discord pump) implement
                # setup() and the runtime calls it BEFORE the loop starts.
                # Uses hasattr to keep the Strategy Protocol pure — Plan 11
                # strategies don't need to change.
                if hasattr(bot.strategy, "setup"):
                    result = bot.strategy.setup()
                    if asyncio.iscoroutine(result):
                        await result

                loop = LiveTradingLoop(
                    strategy=bot.strategy,
                    gate=bot.risk_gate,
                    tracker=trackers[bot.name],
                    broker=self._broker,
                    journal=journal,
                    telemetry=self._telemetry,
                    heartbeat_path=self._heartbeat_path,
                    symbol=bot.spec.symbol,
                    schedule=bot.schedule,
                    allocator=self._allocator,
                    bot_name=bot.name if self._allocator is not None else None,
                    fleet_positions_fn=(
                        _fleet_positions if self._allocator is not None else None
                    ),
                )
                tasks.append(asyncio.create_task(loop.run(source), name=bot.name))

            raw = await asyncio.gather(*tasks, return_exceptions=True)
            results: dict[str, BotResult] = {}
            for bot, source, outcome in zip(self._bots, sources, raw, strict=True):
                err = outcome if isinstance(outcome, BaseException) else None
                results[bot.name] = BotResult(
                    name=bot.name,
                    bars_processed=source.count,
                    error=err,
                )
            return results
        finally:
            for journal in journals:
                try:
                    await journal.close()
                except Exception:
                    # Best-effort cleanup; per-bot failures shouldn't block
                    # the others from closing.
                    pass
