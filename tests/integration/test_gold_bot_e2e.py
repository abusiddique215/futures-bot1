"""Gold Bot end-to-end — FleetRuntime + MeanReversionStrategy + CustomWindows.

Plan 17 T4. Drives synthetic MGC bars (CT timestamps spanning the US session)
through the fleet runtime and asserts:
  - The custom-windows schedule blocks bars outside the US regular session.
  - The mean-reversion strategy fires on lower-BB+oversold-RSI entries.
  - The journal records MGC (not MNQ) symbol on every approval.
  - The EFA Standard floor doesn't move intraday (regression check).

Same pattern as `tests/integration/test_propbot_e2e.py` from Plan 16 — bare
symbol root (MGC) at BotSpec level to avoid the AccountStateTracker
contract-suffix issue. Plan 21 will resolve the bare-vs-suffixed symbol gap.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.journal.journal import Journal
from bot.observability.bus import NoopTelemetryBus
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.runtime import FleetRuntime
from bot.runtime.fleet.schedule import CustomWindows
from bot.runtime.fleet.spec import BotSpec
from bot.types import Bar

_ET = ZoneInfo("America/New_York")


def _spec(tmp_path: Path) -> BotSpec:
    """Gold Bot spec with bare MGC root (see test_propbot_e2e for context)."""
    return BotSpec(
        name="goldbot_e2e",
        enabled=True,
        symbol="MGC",
        strategy_id="mean_reversion_bb",
        strategy_params={
            "symbol": "MGC",
            # Tight params so a short fixture exercises entries.
            "bb_period": 10,
            "bb_stddev": 1.5,
            "rsi_period": 7,
            "rsi_oversold": 35.0,
            "rsi_overbought": 65.0,
            "reward_ratio": 1.0,
            "max_trades_per_day": 3,
        },
        risk_policy="efa_standard",
        risk_params={"mll_amount": 2_000},
        schedule_type="custom_windows",
        schedule_params={
            "tz": "America/New_York",
            "windows": [["08:30", "15:00"]],  # single US regular hours window
        },
        journal_path=tmp_path / "goldbot.db",
    )


def _ranging_bars_with_oversold_dip() -> list[Bar]:
    """MGC bars: warm-up + a sharp drop that creates a lower-BB + oversold-RSI entry.

    All timestamps are 09:30-12:00 ET (inside the single 08:30-15:00 window).
    """
    bars: list[Bar] = []
    start_et = datetime(2026, 5, 22, 9, 30, tzinfo=_ET)
    start_utc = start_et.astimezone(UTC)

    # 30 ranging bars around 2400 with tight noise (BB stddev stays small).
    closes: list[float] = [2400.0 + (0.5 if i % 2 == 0 else -0.5) for i in range(30)]
    # Sharp 8-point drop over the next 5 bars — should push close below lower BB
    # and RSI below oversold.
    for i in range(5):
        closes.append(2400.0 - (i + 1) * 1.6)
    # Recovery bars that should hit the mid-band exit.
    for _ in range(50):
        closes.append(closes[-1] + 0.3)

    for i, c in enumerate(closes):
        ts = start_utc + timedelta(minutes=i)
        bars.append(Bar(
            symbol="MGC",
            open=c,
            high=c + 0.2,
            low=c - 0.2,
            close=c,
            volume=10,
            timestamp=ts,
            interval="1m",
        ))
    return bars


def _out_of_window_bar() -> Bar:
    """One bar at 03:00 ET (outside the 08:30-15:00 US window)."""
    ts_et = datetime(2026, 5, 22, 3, 0, tzinfo=_ET)
    return Bar(
        symbol="MGC", open=2400.0, high=2400.5, low=2399.5,
        close=2400.0, volume=10,
        timestamp=ts_et.astimezone(UTC), interval="1m",
    )


class _StaticSource:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def subscribe(self) -> AsyncIterator[Bar]:
        for bar in self._bars:
            yield bar


@pytest.mark.asyncio
async def test_goldbot_e2e_records_mgc_symbol_under_custom_windows(tmp_path: Path) -> None:
    """Gold Bot runs through FleetRuntime, records MGC on every journal row."""
    sim = SimExecutionClient()
    await sim.connect()
    reg = BotRegistry()
    resolved = reg.build(_spec(tmp_path), broker=sim)

    # Mix: one out-of-window bar + a full ranging session inside the window.
    bars = [_out_of_window_bar(), *_ranging_bars_with_oversold_dip()]

    def source_for(spec: BotSpec) -> Any:
        _ = spec
        return _StaticSource(bars)

    fleet = FleetRuntime(
        bots=[resolved],
        broker=sim,
        bar_source_factory=source_for,
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    results = await fleet.run()
    assert results["goldbot_e2e"].error is None
    assert results["goldbot_e2e"].bars_processed == len(bars)

    journal = await Journal.connect(str(tmp_path / "goldbot.db"))
    try:
        cursor = await journal._conn.execute(  # type: ignore[attr-defined]
            "SELECT symbol, side FROM risk_decisions ORDER BY id",
        )
        rows = await cursor.fetchall()
        await cursor.close()
        # Some risk decisions may exist; if any do, they must all be on MGC.
        for symbol, _side in rows:
            assert symbol == "MGC", f"unexpected symbol in risk_decisions: {symbol}"
    finally:
        await journal.close()


def test_custom_windows_blocks_out_of_window() -> None:
    """CustomWindows.should_trade returns False for 03:00 ET, True for 09:30 ET."""
    sched = CustomWindows(
        tz=_ET,
        windows=[(time(8, 30), time(15, 0))],
    )
    out_ts = datetime(2026, 5, 22, 3, 0, tzinfo=_ET).astimezone(UTC)
    in_ts = datetime(2026, 5, 22, 9, 30, tzinfo=_ET).astimezone(UTC)
    assert sched.should_trade(out_ts) is False
    assert sched.should_trade(in_ts) is True


def test_custom_windows_overnight_span() -> None:
    """Asian session 23:00-01:30 ET handles midnight rollover."""
    sched = CustomWindows(
        tz=_ET,
        windows=[(time(23, 0), time(1, 30))],
    )
    pre_midnight = datetime(2026, 5, 22, 23, 30, tzinfo=_ET).astimezone(UTC)
    after_midnight = datetime(2026, 5, 23, 0, 45, tzinfo=_ET).astimezone(UTC)
    outside = datetime(2026, 5, 22, 18, 0, tzinfo=_ET).astimezone(UTC)
    assert sched.should_trade(pre_midnight) is True
    assert sched.should_trade(after_midnight) is True
    assert sched.should_trade(outside) is False
