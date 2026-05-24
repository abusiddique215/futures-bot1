"""FleetRuntime — run N ResolvedBots concurrently with per-bot isolation.

Each bot gets its own LiveTradingLoop + Journal file; the broker and
telemetry bus are shared. `asyncio.gather(..., return_exceptions=True)`
keeps one bot's exception from crashing the rest of the fleet — we
collect per-bot `BotResult` rows describing completion / error /
bars-processed.

The heartbeat path is shared: launchd cares whether the fleet is alive,
not which bot last wrote.

Plan 21: optional `allocator` + `dashboard_port` ctor kwargs wire in
the cross-bot position cap (T2) and the read-only side-car dashboard
(T5). The dashboard binds to 127.0.0.1 only and a crash in its task
does NOT crash the fleet (return_exceptions=True on the gather).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import uvicorn

from bot.backtest.tracker import AccountStateTracker
from bot.dashboard.app import DashboardState, create_app
from bot.execution.ports import ExecutionClient
from bot.journal.journal import Journal
from bot.runtime.bar_source import LiveBarSource
from bot.runtime.fleet.allocator import FleetAllocator
from bot.runtime.fleet.registry import ResolvedBot
from bot.runtime.fleet.spec import BotSpec
from bot.runtime.live_loop import LiveTradingLoop
from bot.types import Bar

log = logging.getLogger(__name__)


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
        dashboard_port: int | None = None,
        dashboard_bots_dir: Path | None = None,
    ) -> None:
        self._bots = bots
        self._broker = broker
        self._bar_source_factory = bar_source_factory
        self._telemetry = telemetry
        self._heartbeat_path = heartbeat_path
        self._allocator = allocator
        # Dashboard side-car config. Loopback-only by hard constant — never
        # `0.0.0.0`. The bots_dir defaults to None so callers can pass a
        # dashboard_port for tests without committing to a specific
        # config/bots/ layout; if not supplied at run() time we fall back
        # to "config/bots".
        self._dashboard_port = dashboard_port
        self._dashboard_host = "127.0.0.1"
        self._dashboard_bots_dir = dashboard_bots_dir
        self._dashboard_server: uvicorn.Server | None = None
        # Shutdown signal that the fleet propagates to every LiveTradingLoop.
        self._stop_event: asyncio.Event | None = None

    def request_shutdown(self) -> None:
        """Signal a graceful shutdown of the fleet + dashboard.

        Sets the stop_event each LiveTradingLoop watches and asks the
        uvicorn server to exit. Idempotent; safe to call from a signal
        handler or another asyncio task.
        """
        if self._stop_event is not None:
            self._stop_event.set()
        if self._dashboard_server is not None:
            self._dashboard_server.should_exit = True

    async def run(self) -> dict[str, BotResult]:
        """Run every bot concurrently. Failures stay local — caller still
        receives a BotResult for every bot, with `.error` set on failures.
        """
        if not self._bots:
            return {}

        self._stop_event = asyncio.Event()
        dashboard_task: asyncio.Task[None] | None = None
        if self._dashboard_port is not None:
            dashboard_task = self._launch_dashboard()

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
                tasks.append(asyncio.create_task(
                    loop.run(source, stop_event=self._stop_event),
                    name=bot.name,
                ))

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
            # Bots done → tell the dashboard to stop and await its task so
            # uvicorn shuts down cleanly (no in-flight requests dropped).
            if dashboard_task is not None and self._dashboard_server is not None:
                self._dashboard_server.should_exit = True
                try:
                    await asyncio.wait_for(dashboard_task, timeout=2.0)
                except (TimeoutError, Exception) as e:
                    log.warning("dashboard shutdown raised: %s", e)
            for journal in journals:
                try:
                    await journal.close()
                except Exception:
                    # Best-effort cleanup; per-bot failures shouldn't block
                    # the others from closing.
                    pass

    def _launch_dashboard(self) -> asyncio.Task[None]:
        """Create the FastAPI app + uvicorn.Server and spawn its serve() task.

        The server task is wrapped so an exception inside uvicorn doesn't
        crash the fleet — we log and continue.
        """
        bots_dir = self._dashboard_bots_dir or Path("config/bots")
        state = DashboardState(
            bots_dir=bots_dir, heartbeat_path=self._heartbeat_path,
        )
        app = create_app(state)
        config = uvicorn.Config(
            app, host=self._dashboard_host, port=self._dashboard_port or 0,
            log_level="warning",
            # access_log off — local single-user dashboard; serving logs
            # are noise in the fleet log.
            access_log=False,
            # Don't install signal handlers — FleetRuntime owns the
            # shutdown story, and uvicorn would otherwise compete for
            # SIGTERM with the runtime's own handler.
            lifespan="off",
        )
        server = uvicorn.Server(config)
        self._dashboard_server = server

        async def _serve() -> None:
            # Call _serve directly (instead of serve) so uvicorn's
            # capture_signals contextmanager doesn't install handlers
            # that fight the fleet's own signal story. should_exit
            # (set via request_shutdown) is still respected.
            try:
                await server._serve(None)
            except Exception as e:
                log.error("dashboard side-car crashed: %s", e)

        return asyncio.create_task(_serve(), name="fleet-dashboard")
