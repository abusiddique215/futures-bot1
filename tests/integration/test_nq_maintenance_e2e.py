"""NQ Maintenance end-to-end — FleetRuntime + AlwaysOn + MeanReversionStrategy.

Plan 20 T5. Drives a 24-hour synthetic MNQ bar stream (overnight + day +
overnight) through the fleet runtime and asserts:

  * Bars at every hour reach the strategy (the AlwaysOn schedule blocks
    nothing).
  * The wide-BB / low-RSI profile produces a low number of entries
    (sanity: < 5 over the 24h fixture).
  * No `STRATEGY_DISABLED` denials appear — that's the rule emitted after
    `gate.force_flatten_now()` and represents the actively-dangerous path
    that LiveOnlyGuard + EFA together prevent. (Note: HARD_FLAT_CLOCK
    denials DO appear after 15:10 CT — the gate enforces the cutoff
    regardless of policy; that's a known Plan-21 limitation. NQ Maintenance
    accepts these as "sit out the last hour" — they only block new
    opens, not existing exits.)
  * EFA Standard's floor is invariant under intraday equity swings
    (regression on the policy itself; same property check the gold and
    propbot e2e tests use).

Same patterns as `test_gold_bot_e2e.py` and `test_propbot_e2e.py`:
  - Contract-suffixed symbol (MNQH26) at BotSpec level — Plan 21 made
    AccountStateTracker's point-value lookup contract-suffix-aware.
  - SimExecutionClient + StaticSource, not TopstepXSimClient scenarios.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.journal.journal import Journal
from bot.observability.bus import NoopTelemetryBus
from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.runtime import FleetRuntime
from bot.runtime.fleet.schedule import AlwaysOn
from bot.runtime.fleet.spec import BotSpec
from bot.types import AccountState, Bar


def _spec(tmp_path: Path) -> BotSpec:
    """NQ Maintenance spec with contract-suffixed MNQH26 + slightly relaxed
    params so the 24h fixture is long enough to fire at least once."""
    return BotSpec(
        name="nq_maintenance_e2e",
        enabled=True,
        symbol="MNQH26",
        strategy_id="mean_reversion_bb",
        strategy_params={
            "symbol": "MNQH26",
            # Looser than shipped so a single 24h fixture exercises an entry —
            # the shipped 50/3.0/20-80 tuning rarely fires by design.
            "bb_period": 20,
            "bb_stddev": 2.0,
            "rsi_period": 7,
            "rsi_oversold": 30.0,
            "rsi_overbought": 70.0,
            "reward_ratio": 0.5,
            "max_trades_per_day": 2,
        },
        risk_policy="efa_standard",
        risk_params={"mll_amount": 2_000},
        schedule_type="always",
        schedule_params={},
        journal_path=tmp_path / "nq_maintenance.db",
    )


def _build_24h_bars() -> list[Bar]:
    """1440 1-min bars covering a full UTC day (overnight + day + overnight).

    Start at 13:00 UTC = 08:00 CT — entry signals land in the 08:30-15:00 CT
    window so the gate's policy-agnostic HARD_FLAT_CLOCK check (any policy,
    after 15:10 CT) doesn't deny all opens.

    Pattern: 30 ranging bars (warm-up the BB) + a 5-bar sharp drop pierces
    lower BB + RSI oversold (one entry), then 30 recovery bars cross the
    mid-band (one exit) — both entry and exit complete before 09:35 CT.
    The remaining bars are mild noise that doesn't trigger more entries
    even under `max_trades_per_day=2` because the strategy's signal
    conditions are not met after the warm-up window.
    """
    bars: list[Bar] = []
    start_utc = datetime(2026, 5, 22, 13, 0, tzinfo=UTC)  # 08:00 CT

    closes: list[float] = [18_000.0 + (0.5 if i % 2 == 0 else -0.5) for i in range(30)]
    for i in range(5):
        closes.append(18_000.0 - (i + 1) * 2.0)
    last = closes[-1]
    for i in range(30):
        closes.append(last + (i + 1) * 0.4)
    last = closes[-1]
    while len(closes) < 1440:
        offset = 0.2 if len(closes) % 2 == 0 else -0.2
        closes.append(last + offset)

    for i, c in enumerate(closes):
        ts = start_utc + timedelta(minutes=i)
        bars.append(Bar(
            symbol="MNQH26", open=c, high=c + 0.25, low=c - 0.25, close=c,
            volume=10, timestamp=ts, interval="1m",
        ))
    return bars


class _StaticSource:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def subscribe(self) -> AsyncIterator[Bar]:
        for bar in self._bars:
            yield bar


@pytest.mark.asyncio
async def test_nq_maintenance_24h_low_frequency_no_forced_flat(tmp_path: Path) -> None:
    """24-hour run through FleetRuntime: a few entries, no forced flatten."""
    sim = SimExecutionClient()
    await sim.connect()
    reg = BotRegistry()
    resolved = reg.build(_spec(tmp_path), broker=sim)
    bars = _build_24h_bars()

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
    assert results["nq_maintenance_e2e"].error is None
    # AlwaysOn schedule blocks nothing — every bar reaches the loop.
    assert results["nq_maintenance_e2e"].bars_processed == len(bars)

    journal = await Journal.connect(str(tmp_path / "nq_maintenance.db"))
    try:
        cursor = await journal._conn.execute(  # type: ignore[attr-defined]
            "SELECT side, approved, rule FROM risk_decisions ORDER BY id",
        )
        rows = await cursor.fetchall()
        await cursor.close()

        approvals = [r for r in rows if r[1] == 1]
        # Maintenance is low-frequency: 1-4 approvals expected across 24h
        # (entries + their mid-band / stop exits, capped by max_trades_per_day=2).
        # Asserts both lower bound (proves the AlwaysOn schedule actually
        # passed bars through) and upper bound (sanity for the wide-BB tuning).
        assert 1 <= len(approvals) <= 4, (
            f"NQ Maintenance fired {len(approvals)} times in 24h — expected 1-4"
        )
        # The load-bearing safety property: no STRATEGY_DISABLED rows. That
        # rule appears only after `gate.force_flatten_now()` (the actively
        # dangerous path) — what LiveOnlyGuard + EFA together prevent.
        # HARD_FLAT_CLOCK denials are EXPECTED for any 24/7 bot post-15:10 CT
        # under the current gate; they only block new opens, not exits.
        rules = {r[2] for r in rows if r[2] is not None}
        assert "STRATEGY_DISABLED" not in rules, (
            "NQ Maintenance must never see STRATEGY_DISABLED — that's the "
            "force_flatten path LiveOnlyGuard + EFA together prevent"
        )
    finally:
        await journal.close()


def test_efa_standard_floor_does_not_move_intraday() -> None:
    """Regression: EFA Standard's phantom_mll is invariant under intraday
    equity swings — same property check the gold/propbot e2e tests use.
    """
    policy = EFAStandardEoDDrawdown(mll_amount=2_000.0)
    base = AccountState(
        equity=50_000.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=50_000.0,
        is_combine=False,
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )
    floor_initial = policy.phantom_mll(base)
    after_up = policy.update_on_tick(replace(base, equity=51_500.0))
    assert policy.phantom_mll(after_up) == floor_initial
    after_down = policy.update_on_tick(replace(base, equity=49_700.0))
    assert policy.phantom_mll(after_down) == floor_initial


def test_always_schedule_blocks_nothing_across_24h() -> None:
    """AlwaysOn.should_trade is True at every hour — including 15:10 CT."""
    sched = AlwaysOn()
    for hour in range(24):
        ts = datetime(2026, 5, 22, hour, 0, tzinfo=UTC)
        assert sched.should_trade(ts) is True
