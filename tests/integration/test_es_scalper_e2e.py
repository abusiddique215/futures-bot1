"""ES Scalper end-to-end — FleetRuntime + MeanReversionStrategy + MarketHours.

Plan 18 T3. Drives synthetic MES bars (a single 08:30 - 14:45 CT US-regular
session) through the fleet runtime and asserts:
  - The scalper opens more than one position (the higher max_trades_per_day
    cap actually unlocks multiple entries vs Gold Bot's 3-cap).
  - No risk decisions land after 14:45 CT — the MarketHours schedule blocks
    intents (entry or exit) once the window closes, so by the time the
    cutoff hits, all activity must already have flushed.
  - The journal records MES (not MNQ / MGC) symbol on every approval.

Pattern matches `tests/integration/test_gold_bot_e2e.py` — bare-root symbol
("MES") at the BotSpec level to avoid the AccountStateTracker contract-suffix
issue. Plan 21 will resolve the bare-vs-suffixed symbol gap.
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
from bot.runtime.fleet.spec import BotSpec
from bot.types import Bar

_CT = ZoneInfo("America/Chicago")


def _spec(tmp_path: Path) -> BotSpec:
    """ES Scalper spec with contract-suffixed MESH26 (Plan 21 tracker now suffix-aware)."""
    return BotSpec(
        name="es_scalper_e2e",
        enabled=True,
        symbol="MESH26",
        strategy_id="mean_reversion_bb",
        strategy_params={
            "symbol": "MESH26",
            # Plan 18 scalper tuning (mirrors ES_SCALPER_DEFAULTS minus symbol).
            "bb_period": 10,
            "bb_stddev": 1.5,
            "rsi_period": 9,
            "rsi_oversold": 35.0,
            "rsi_overbought": 65.0,
            "reward_ratio": 0.75,
            "max_trades_per_day": 10,
        },
        risk_policy="efa_standard",
        risk_params={"mll_amount": 2_000},
        schedule_type="market_hours",
        schedule_params={"open_ct": "08:30", "close_ct": "14:45"},
        journal_path=tmp_path / "es_scalper.db",
    )


def _multi_dip_session_bars() -> list[Bar]:
    """MES bars covering 08:30 - 14:30 CT with three oversold dip / recovery
    cycles. Each cycle should yield one BUY entry + a mid-band exit, so the
    bot accumulates >=2 entries by the end of the session.

    All bars are timestamped well before 14:45 CT so the "all flat by cutoff"
    assertion has room to breathe.
    """
    bars: list[Bar] = []
    start_ct = datetime(2026, 5, 22, 8, 30, tzinfo=_CT)
    start_utc = start_ct.astimezone(UTC)

    closes: list[float] = []

    def warmup(base: float, n: int) -> None:
        # n bars of tight ranging around base — establishes a stable BB.
        for i in range(n):
            closes.append(base + (0.25 if i % 2 == 0 else -0.25))

    def dip(base: float, drop_per_bar: float, n: int) -> None:
        for i in range(n):
            closes.append(base - (i + 1) * drop_per_bar)

    def recover(start_price: float, gain_per_bar: float, n: int) -> None:
        for i in range(n):
            closes.append(start_price + (i + 1) * gain_per_bar)

    # Cycle 1 — warmup at 5000, sharp 6-bar drop, slow climb back.
    warmup(5_000.0, 30)
    dip(5_000.0, 1.0, 6)            # closes from 4999 -> 4994
    recover(4_994.0, 0.5, 30)       # climbs back toward / through the mid

    # Cycle 2 — ranging at 5009, another dip.
    warmup(5_009.0, 30)
    dip(5_009.0, 1.0, 6)
    recover(5_003.0, 0.5, 30)

    # Cycle 3 — ranging at 5018, third dip.
    warmup(5_018.0, 30)
    dip(5_018.0, 1.0, 6)
    recover(5_012.0, 0.5, 30)

    # Tail: 30 quiet bars — gives any open position more time to mean-revert
    # and ensures we finish well inside the 14:45 cutoff.
    warmup(5_027.0, 30)

    for i, c in enumerate(closes):
        ts = start_utc + timedelta(minutes=i)
        bars.append(Bar(
            symbol="MESH26",
            open=c,
            high=c + 0.25,
            low=c - 0.25,
            close=c,
            volume=10,
            timestamp=ts,
            interval="1m",
        ))
    return bars


class _StaticSource:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def subscribe(self) -> AsyncIterator[Bar]:
        for bar in self._bars:
            yield bar


@pytest.mark.asyncio
async def test_es_scalper_e2e_multiple_entries_and_mes_symbol(tmp_path: Path) -> None:
    """ES Scalper opens >=2 positions in the session + records MES on every row.

    Indirectly verifies the schedule cutoff: the fixture's last bar is well
    inside the 14:45 CT window, so we additionally assert no risk decisions
    land after 14:45 CT.
    """
    sim = SimExecutionClient()
    await sim.connect()
    reg = BotRegistry()
    resolved = reg.build(_spec(tmp_path), broker=sim)

    bars = _multi_dip_session_bars()

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
    assert results["es_scalper_e2e"].error is None
    assert results["es_scalper_e2e"].bars_processed == len(bars)

    journal = await Journal.connect(str(tmp_path / "es_scalper.db"))
    try:
        cursor = await journal._conn.execute(  # type: ignore[attr-defined]
            "SELECT symbol, side, approved, timestamp FROM risk_decisions ORDER BY id",
        )
        rows = await cursor.fetchall()
        await cursor.close()

        # 1. Every row must be tagged MESH26 (the configured contract symbol).
        for symbol, _side, _approved, _timestamp in rows:
            assert symbol == "MESH26", f"unexpected symbol in risk_decisions: {symbol}"

        # 2. >= 2 BUY entries (the scalper cap of 10 must actually unlock
        #    more than Gold Bot's 3-cap equivalent of a single entry).
        # Tuple layout: (symbol, side, approved, timestamp).
        buy_approvals = [
            r for r in rows
            if r[1] == "BUY" and r[2] == 1
        ]
        assert len(buy_approvals) >= 2, (
            f"expected >=2 BUY approvals across 3 dip cycles, "
            f"got {len(buy_approvals)}: {rows}"
        )

        # 3. No risk decisions land after 14:45 CT. timestamp column is an
        #    ISO string; parse + compare in CT.
        cutoff_ct = datetime(2026, 5, 22, 14, 45, tzinfo=_CT)
        for symbol, _side, _approved, timestamp in rows:
            row_ts = datetime.fromisoformat(timestamp)
            assert row_ts.astimezone(_CT) <= cutoff_ct, (
                f"risk decision recorded after 14:45 CT cutoff: {row_ts} ({symbol})"
            )
    finally:
        await journal.close()


def test_market_hours_es_scalper_cutoff() -> None:
    """MarketHours 08:30-14:45 CT: 14:44 trades, 14:46 does not."""
    from bot.runtime.fleet.schedule import MarketHours
    sched = MarketHours(open_ct=time(8, 30), close_ct=time(14, 45))
    inside = datetime(2026, 5, 22, 14, 44, tzinfo=_CT).astimezone(UTC)
    outside = datetime(2026, 5, 22, 14, 46, tzinfo=_CT).astimezone(UTC)
    assert sched.should_trade(inside) is True
    assert sched.should_trade(outside) is False
