"""Plan 10 T2: LiveTradingLoop core.

Mirrors BacktestEngine's per-bar pipeline (mark-to-market → snapshot → on_tick
→ strategy.on_bar → approve_or_deny → broker.place_order → journal), but
consumes an async Bar stream (LiveBarSource) instead of a sync Iterable.
All tests use SimExecutionClient + synthetic SimBarSource — no real broker.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.strategy import PlaceholderStrategy
from bot.backtest.tracker import AccountStateTracker
from bot.journal.journal import Journal
from bot.observability.bus import NoopTelemetryBus
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.runtime.bar_source import SimBarSource
from bot.runtime.live_loop import LiveTradingLoop
from bot.types import AccountState, Bar, Bracket, OrderIntent


class _NoopNews:
    def in_window(self, now: datetime) -> bool:
        return False

    def max_position_during_window(self) -> int:
        return 1


def _bars(closes: list[float], *, start: datetime | None = None) -> list[Bar]:
    start = start or datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    return [
        Bar(
            symbol="MNQ",
            open=c,
            high=c,
            low=c,
            close=c,
            volume=100,
            timestamp=start + timedelta(minutes=i),
            interval="1m",
        )
        for i, c in enumerate(closes)
    ]


def _make_gate(sim: SimExecutionClient) -> TopstepRiskGate:
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    return TopstepRiskGate(
        policy=policy,
        news_calendar=_NoopNews(),
        execution_client=sim,
        telemetry=NoopTelemetryBus(),
        config=cfg,
    )


class _BuyOnceStrategy:
    """Emits a single BUY-with-bracket on bar 0."""

    def __init__(self) -> None:
        self._i = 0

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        i = self._i
        self._i += 1
        if i == 0:
            return [OrderIntent(
                symbol="MNQ", side="BUY", quantity=1,
                order_type="MARKET", client_order_id="open-1",
                timestamp=bar.timestamp,
                bracket=Bracket(stop_loss_ticks=40, take_profit_ticks=80),
            )]
        return []


async def _new_journal() -> Journal:
    j = await Journal.connect(":memory:")
    await j.apply_migrations()
    return j


# ---- Tests ---------------------------------------------------------------

async def test_loop_with_placeholder_strategy_runs_clean(tmp_path: Path) -> None:
    """5 bars + PlaceholderStrategy: no decisions, no fills, journal opens
    and closes cleanly."""
    sim = SimExecutionClient()
    await sim.connect()
    gate = _make_gate(sim)
    tracker = AccountStateTracker(start_balance=50_000.0, is_combine=True)
    journal = await _new_journal()
    loop = LiveTradingLoop(
        strategy=PlaceholderStrategy(),
        gate=gate,
        tracker=tracker,
        broker=sim,
        journal=journal,
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
        symbol="MNQ",
    )
    await loop.run(SimBarSource(_bars([18_000.0, 18_001.0, 18_002.0, 18_003.0, 18_004.0])))
    # 5 equity snapshots written (one per bar). No decisions, no fills.
    last = await journal.get_last_equity_snapshot()
    assert last is not None
    await journal.close()


async def test_loop_one_shot_buy_records_approval(tmp_path: Path) -> None:
    """Strategy emits BUY on bar 0 → gate approves → sim places fill → journal
    has one approved-risk-decision row and one fill row."""
    sim = SimExecutionClient()
    await sim.connect()
    gate = _make_gate(sim)
    tracker = AccountStateTracker(start_balance=50_000.0, is_combine=True)
    journal = await _new_journal()
    loop = LiveTradingLoop(
        strategy=_BuyOnceStrategy(),
        gate=gate,
        tracker=tracker,
        broker=sim,
        journal=journal,
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
        symbol="MNQ",
    )
    await loop.run(SimBarSource(_bars([18_000.0, 18_001.0, 18_002.0])))

    # One approved risk decision recorded
    cur = await journal._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM risk_decisions WHERE approved=1"
    )
    (approved_count,) = await cur.fetchone()  # type: ignore[misc]
    await cur.close()
    assert approved_count == 1

    # One fill recorded
    cur = await journal._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM fills"
    )
    (fill_count,) = await cur.fetchone()  # type: ignore[misc]
    await cur.close()
    assert fill_count == 1

    await journal.close()


async def test_loop_after_15_10_ct_denies_all_openers(tmp_path: Path) -> None:
    """Bars timestamped > 15:10 CT: hard-flat-clock denies the open intent.
    Journal records the denial."""
    # 15:30 CT = 20:30 UTC (CDT, May → UTC-5)
    after_close_utc = datetime(2026, 5, 22, 20, 30, tzinfo=UTC)
    sim = SimExecutionClient()
    await sim.connect()
    gate = _make_gate(sim)
    tracker = AccountStateTracker(start_balance=50_000.0, is_combine=True)
    journal = await _new_journal()
    loop = LiveTradingLoop(
        strategy=_BuyOnceStrategy(),
        gate=gate,
        tracker=tracker,
        broker=sim,
        journal=journal,
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
        symbol="MNQ",
    )
    bars = _bars([18_000.0, 18_001.0], start=after_close_utc)
    # Quick sanity: first bar's CT is after 15:10
    from zoneinfo import ZoneInfo
    ct = bars[0].timestamp.astimezone(ZoneInfo("America/Chicago"))
    assert ct.time() >= time(15, 10)

    await loop.run(SimBarSource(bars))

    cur = await journal._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*), MAX(rule) FROM risk_decisions WHERE approved=0"
    )
    (denied_count, rule) = await cur.fetchone()  # type: ignore[misc]
    await cur.close()
    assert denied_count == 1
    assert rule == "HARD_FLAT_CLOCK"
    await journal.close()


async def test_loop_max_bars_caps_iteration(tmp_path: Path) -> None:
    """max_bars=2 means only the first 2 bars get processed even if 10 supplied."""
    sim = SimExecutionClient()
    await sim.connect()
    gate = _make_gate(sim)
    tracker = AccountStateTracker(start_balance=50_000.0, is_combine=True)
    journal = await _new_journal()
    loop = LiveTradingLoop(
        strategy=PlaceholderStrategy(),
        gate=gate,
        tracker=tracker,
        broker=sim,
        journal=journal,
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
        symbol="MNQ",
    )
    bars = _bars([18_000.0 + i for i in range(10)])
    await loop.run(SimBarSource(bars), max_bars=2)

    cur = await journal._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM equity_snapshots"
    )
    (snap_count,) = await cur.fetchone()  # type: ignore[misc]
    await cur.close()
    assert snap_count == 2
    await journal.close()
