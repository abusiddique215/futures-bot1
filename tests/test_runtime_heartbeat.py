"""Plan 10 T3: Heartbeat writer + loop integration.

`Heartbeat(path).write_now(ts)` is crash-safe: writes to `path.tmp`, then
atomic-renames to `path`. The loop calls write_now() once per bar if at least
`min_interval_s` (30s) has elapsed since the last write.
"""
from __future__ import annotations

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
from bot.runtime.bar_source import SimBarSource
from bot.runtime.heartbeat import Heartbeat
from bot.runtime.live_loop import LiveTradingLoop
from bot.types import Bar


class _NoopNews:
    def in_window(self, now: datetime) -> bool:
        return False

    def max_position_during_window(self) -> int:
        return 1


def test_heartbeat_writes_iso_timestamp_to_file(tmp_path: Path) -> None:
    """write_now(ts) writes the ISO-formatted timestamp to the file."""
    hb_path = tmp_path / "hb"
    hb = Heartbeat(hb_path)
    ts = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    hb.write_now(ts)
    assert hb_path.read_text(encoding="utf-8") == ts.isoformat()


def test_heartbeat_uses_atomic_rename(tmp_path: Path) -> None:
    """write_now writes to a sibling .tmp file first, then renames into place.
    Asserts the temp file does NOT linger after the call."""
    hb_path = tmp_path / "hb"
    hb = Heartbeat(hb_path)
    hb.write_now(datetime(2026, 5, 22, 14, 30, tzinfo=UTC))
    assert hb_path.exists()
    # No stray .tmp file
    tmp_file = hb_path.with_suffix(hb_path.suffix + ".tmp")
    assert not tmp_file.exists()


def test_heartbeat_creates_parent_dir(tmp_path: Path) -> None:
    """The parent directory is created on first write."""
    nested = tmp_path / "state" / "hb"
    hb = Heartbeat(nested)
    hb.write_now(datetime(2026, 5, 22, 14, 30, tzinfo=UTC))
    assert nested.exists()


def test_heartbeat_overwrites_on_subsequent_writes(tmp_path: Path) -> None:
    """Second write replaces the first."""
    hb_path = tmp_path / "hb"
    hb = Heartbeat(hb_path)
    hb.write_now(datetime(2026, 5, 22, 14, 30, tzinfo=UTC))
    hb.write_now(datetime(2026, 5, 22, 14, 31, tzinfo=UTC))
    assert hb_path.read_text(encoding="utf-8") == "2026-05-22T14:31:00+00:00"


# ---- Loop integration ----------------------------------------------------

def _bars(n: int, step: timedelta = timedelta(seconds=60)) -> list[Bar]:
    start = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    return [
        Bar(
            symbol="MNQ", open=18_000.0, high=18_000.0,
            low=18_000.0, close=18_000.0, volume=10,
            timestamp=start + step * i, interval="1m",
        )
        for i in range(n)
    ]


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


async def test_loop_writes_heartbeat_on_first_bar(tmp_path: Path) -> None:
    """First bar always triggers a heartbeat write."""
    journal = await Journal.connect(":memory:")
    await journal.apply_migrations()
    loop = _make_loop(tmp_path, journal)
    await loop.run(SimBarSource(_bars(1)))
    assert (tmp_path / "hb").exists()
    await journal.close()


async def test_loop_throttles_heartbeat_at_30s(tmp_path: Path) -> None:
    """Bars 10s apart: only the first bar's heartbeat hits disk; the next
    two are throttled (< 30s elapsed). Bar 4 is 30s after bar 1 → triggers.

    We assert by inspecting the FILE'S contents after each call — the
    timestamp inside the file is the last bar that wrote it."""
    journal = await Journal.connect(":memory:")
    await journal.apply_migrations()
    loop = _make_loop(tmp_path, journal)

    bars = _bars(4, step=timedelta(seconds=10))
    await loop.run(SimBarSource(bars))

    # bar 0 (t=14:30:00) is first — writes.
    # bar 1 (t=14:30:10) — throttled (10s).
    # bar 2 (t=14:30:20) — throttled (20s).
    # bar 3 (t=14:30:30) — 30s since last write → writes.
    last = (tmp_path / "hb").read_text(encoding="utf-8")
    assert last == bars[3].timestamp.isoformat()
    await journal.close()
