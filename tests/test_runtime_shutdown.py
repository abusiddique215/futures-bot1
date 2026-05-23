"""Plan 10 T4: SIGTERM clean shutdown.

`install_shutdown_handler(stop_event)` registers a SIGTERM/SIGINT handler that
sets the event. The actual signal-handler wiring is tested with a synthetic
`raise_signal` so we don't have to actually kill the test process.

The LiveTradingLoop accepts an optional `stop_event` and checks it before
processing each bar. On stop: any pending force-flatten request is drained,
strategy is permanently disabled by the gate, and the loop returns. Journal
close is the caller's responsibility (main.py does it in its finally).
"""
from __future__ import annotations

import asyncio
import signal
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.strategy import PlaceholderStrategy
from bot.backtest.tracker import AccountStateTracker
from bot.journal.journal import Journal
from bot.observability.bus import NoopTelemetryBus
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.runtime.bar_source import LiveBarSource, SimBarSource
from bot.runtime.live_loop import LiveTradingLoop
from bot.runtime.shutdown import install_shutdown_handler
from bot.types import AccountState, Bar, OrderIntent


class _NoopNews:
    def in_window(self, now: datetime) -> bool:
        return False

    def max_position_during_window(self) -> int:
        return 1


def _bars(n: int) -> list[Bar]:
    start = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    return [
        Bar(
            symbol="MNQ", open=18_000.0, high=18_000.0, low=18_000.0,
            close=18_000.0, volume=10,
            timestamp=start + timedelta(minutes=i), interval="1m",
        )
        for i in range(n)
    ]


async def _new_journal() -> Journal:
    j = await Journal.connect(":memory:")
    await j.apply_migrations()
    return j


def _make_loop(tmp_path: Path, journal: Journal) -> LiveTradingLoop:
    sim = SimExecutionClient()
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    gate = TopstepRiskGate(
        policy=policy, news_calendar=_NoopNews(), execution_client=sim,
        telemetry=NoopTelemetryBus(), config=cfg,
    )
    tracker = AccountStateTracker(start_balance=50_000.0, is_combine=True)
    return LiveTradingLoop(
        strategy=PlaceholderStrategy(), gate=gate, tracker=tracker,
        broker=sim, journal=journal, telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb", symbol="MNQ",
    )


# ---- Handler installation ------------------------------------------------

async def test_install_shutdown_handler_sets_event_on_signal() -> None:
    """Raising a registered signal sets the event.

    We use SIGUSR1 instead of SIGINT/SIGTERM so a failure mid-test can't
    affect pytest's own Ctrl-C handling.
    """
    stop_event = asyncio.Event()
    handler_ref = install_shutdown_handler(stop_event, signals=(signal.SIGUSR1,))
    assert handler_ref is not None
    try:
        signal.raise_signal(signal.SIGUSR1)
        # wait_for re-enters the selector so the asyncio signal callback can
        # fire; a single sleep(0) isn't sufficient on all platforms.
        await asyncio.wait_for(stop_event.wait(), timeout=1.0)
    finally:
        asyncio.get_running_loop().remove_signal_handler(signal.SIGUSR1)


# ---- Loop integration ----------------------------------------------------

async def test_loop_exits_when_stop_event_already_set(tmp_path: Path) -> None:
    """stop_event set before run() → loop never processes a bar."""
    journal = await _new_journal()
    loop = _make_loop(tmp_path, journal)
    stop_event = asyncio.Event()
    stop_event.set()

    await loop.run(SimBarSource(_bars(5)), stop_event=stop_event)

    cur = await journal._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM equity_snapshots"
    )
    (count,) = await cur.fetchone()  # type: ignore[misc]
    await cur.close()
    assert count == 0
    await journal.close()


async def test_loop_exits_mid_stream_when_event_set(tmp_path: Path) -> None:
    """stop_event set after N bars → loop processes exactly N then exits.

    We use a custom bar source that sets the event after 2 bars.
    """
    journal = await _new_journal()
    loop = _make_loop(tmp_path, journal)
    stop_event = asyncio.Event()

    class _SignallingSource:
        def __init__(self, bars: list[Bar], event: asyncio.Event, after: int) -> None:
            self._bars = bars
            self._event = event
            self._after = after

        async def subscribe(self) -> AsyncIterator[Bar]:
            for i, bar in enumerate(self._bars):
                if i == self._after:
                    self._event.set()
                yield bar

    src: LiveBarSource = _SignallingSource(_bars(5), stop_event, after=2)
    await loop.run(src, stop_event=stop_event)

    cur = await journal._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM equity_snapshots"
    )
    (count,) = await cur.fetchone()  # type: ignore[misc]
    await cur.close()
    # Bars 0 and 1 are processed (event set BEFORE bar 2 is delivered to the
    # consumer; the loop sees event-set at the top of bar 2's iteration and
    # bails before snapshotting).
    assert count == 2
    await journal.close()


# ---- Force-flatten on shutdown -------------------------------------------

class _LongOnceStrategy:
    """Opens a long on bar 0 with a wide stop so the gate accepts; emits
    nothing after."""

    def __init__(self) -> None:
        self._i = 0

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        from bot.types import Bracket
        i = self._i
        self._i += 1
        if i == 0:
            return [OrderIntent(
                symbol="MNQ", side="BUY", quantity=1, order_type="MARKET",
                client_order_id="open-1", timestamp=bar.timestamp,
                bracket=Bracket(stop_loss_ticks=40, take_profit_ticks=80),
            )]
        return []


async def test_loop_force_flattens_on_shutdown(tmp_path: Path) -> None:
    """When stop_event fires after a position is open, the loop calls
    `gate.force_flatten_now()` so the broker sees a cancel_all."""
    journal = await _new_journal()
    sim = SimExecutionClient()
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    gate = TopstepRiskGate(
        policy=policy, news_calendar=_NoopNews(), execution_client=sim,
        telemetry=NoopTelemetryBus(), config=cfg,
    )
    tracker = AccountStateTracker(start_balance=50_000.0, is_combine=True)
    loop = LiveTradingLoop(
        strategy=_LongOnceStrategy(), gate=gate, tracker=tracker,
        broker=sim, journal=journal, telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb", symbol="MNQ",
    )

    stop_event = asyncio.Event()

    class _SignallingSource:
        def __init__(self, bars: list[Bar], event: asyncio.Event, after: int) -> None:
            self._bars = bars
            self._event = event
            self._after = after

        async def subscribe(self) -> AsyncIterator[Bar]:
            for i, bar in enumerate(self._bars):
                if i == self._after:
                    self._event.set()
                yield bar

    src: LiveBarSource = _SignallingSource(_bars(3), stop_event, after=2)
    await loop.run(src, stop_event=stop_event)

    # After shutdown, strategy is permanently disabled by the gate's
    # force_flatten_now() finally block.
    assert gate._strategy_disabled is True  # type: ignore[attr-defined]
    await journal.close()
