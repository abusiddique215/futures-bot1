"""SurgeBot end-to-end — FleetRuntime + TieredSizingDecorator + ORB.

Plan 15 T6. Drives synthetic MNQ bars through the fleet runtime and asserts:
  - The bot loads through the registry without error.
  - The fleet completes the bar stream cleanly (no exceptions, no missing bars).
  - Any approved orders carry tier_qty consistent with start-of-day (no prior
    profit → tier_qty = 1 micro per the [0,1] breakpoint).
  - The journal records MNQ as the symbol.

Same pattern as Plan 16's test_propbot_e2e — bare symbol root + StaticSource.
ORB strategy requires very specific bar shapes to fire; this test is about the
end-to-end runtime, NOT about producing entries. ORB entry coverage lives in
`tests/test_strategy_orb_*.py`.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.journal.journal import Journal
from bot.observability.bus import NoopTelemetryBus
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.runtime import FleetRuntime
from bot.runtime.fleet.spec import BotSpec
from bot.types import Bar

_CT = ZoneInfo("America/Chicago")


def _spec(tmp_path: Path) -> BotSpec:
    return BotSpec(
        name="surgebot_e2e",
        enabled=True,
        symbol="MNQ",
        strategy_id="orb_5m_tiered",
        strategy_params={
            "strategy": {
                "symbol": "MNQ",
                "range_minutes": 5,
                "atr_mult": 1.0,
                "tp_r_multiple": 2.0,
                "max_trades_per_day": 2,
            },
            "tiered": {
                "symbol": "MNQ",
                "tier_breakpoints": [(0, 1), (500, 2), (1500, 4), (2500, 5)],
            },
        },
        risk_policy="combine_intraday",
        risk_params={
            "start_balance": 50_000,
            "mll_amount": 2_000,
            "max_mini": 5,
        },
        schedule_type="market_hours",
        schedule_params={"open_ct": "08:30", "close_ct": "15:00"},
        journal_path=tmp_path / "surgebot.db",
    )


def _session_bars() -> list[Bar]:
    """8:30 - 15:00 CT with a clear opening range and a break above."""
    bars: list[Bar] = []
    start_ct = datetime(2026, 5, 22, 8, 30, tzinfo=_CT)
    start_utc = start_ct.astimezone(UTC)
    # First 5 minutes: tight range 18000-18010.
    for i in range(5):
        ts = start_utc + timedelta(minutes=i)
        bars.append(Bar(
            symbol="MNQ", open=18_002.0 + (i % 2),
            high=18_010.0, low=18_000.0,
            close=18_005.0 + (i % 3),
            volume=100, timestamp=ts, interval="1m",
        ))
    # Bars 5+: break above 18010 (long ORB entry).
    closes = [18_015.0 + i * 0.5 for i in range(180)]
    for i, c in enumerate(closes):
        ts = start_utc + timedelta(minutes=5 + i)
        bars.append(Bar(
            symbol="MNQ", open=c, high=c + 1.0, low=c - 0.5,
            close=c, volume=100, timestamp=ts, interval="1m",
        ))
    return bars


class _StaticSource:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def subscribe(self) -> AsyncIterator[Bar]:
        for bar in self._bars:
            yield bar


@pytest.mark.asyncio
async def test_surgebot_e2e_loads_and_runs_through_fleet(tmp_path: Path) -> None:
    """SurgeBot loads via registry, fleet processes all bars without exception."""
    sim = SimExecutionClient()
    await sim.connect()
    reg = BotRegistry()
    resolved = reg.build(_spec(tmp_path), broker=sim)
    bars = _session_bars()

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
    assert results["surgebot_e2e"].error is None
    assert results["surgebot_e2e"].bars_processed == len(bars)


@pytest.mark.asyncio
async def test_surgebot_e2e_uses_tier_one_at_session_start(tmp_path: Path) -> None:
    """At session start (no realized profit), TieredSizingDecorator overrides qty=1."""
    sim = SimExecutionClient()
    await sim.connect()
    reg = BotRegistry()
    resolved = reg.build(_spec(tmp_path), broker=sim)
    bars = _session_bars()

    def source_for(spec: BotSpec) -> Any:
        _ = spec
        return _StaticSource(bars)

    fleet = FleetRuntime(
        bots=[resolved], broker=sim,
        bar_source_factory=source_for,
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    await fleet.run()

    journal = await Journal.connect(str(tmp_path / "surgebot.db"))
    try:
        cursor = await journal._conn.execute(  # type: ignore[attr-defined]
            "SELECT symbol, side, quantity FROM risk_decisions WHERE approved=1 ORDER BY id",
        )
        rows = await cursor.fetchall()
        await cursor.close()
        # If any approvals happened, they must all be MNQ (regression on Plan 14).
        # And qty must be 10 micros (= tier 1 mini x 10 micros/mini for MNQ).
        for symbol, _side, qty in rows:
            assert symbol == "MNQ", f"unexpected symbol: {symbol}"
            assert qty == 10, f"expected tier_qty=10 micros (1 mini), got {qty}"
    finally:
        await journal.close()
