"""PropBot end-to-end — FleetRuntime + SimExecutionClient + Journal.

Plan 16 T4. Drives a synthetic NQ uptrend (09:00 -> 14:30 CT) through the
fleet runtime and asserts on the per-bot journal state.

Deviations from the plan's literal wording:
  - The plan says "FleetRuntime -> TopstepXSimClient (efa_payout_flow_50k
    scenario)". TopstepXSimClient's scenarios are a self-contained driver
    that owns its own bar loop; FleetRuntime needs an ExecutionClient and
    a bar_source. The two harnesses don't compose. We use the
    SimExecutionClient + StaticSource pattern from tests/runtime/fleet/
    test_runtime.py — the same pattern Plan 12 uses for fleet integration
    tests.
  - BotSpec.symbol = "MNQ" (bare root) instead of "MNQH26". The shipped
    YAML uses MNQH26 (Plan T3, test_propbot_config.py covers parsing);
    here we use the bare root because AccountStateTracker._POINT_VALUE is
    keyed on bare roots and would KeyError on the contract suffix. The
    tracker-vs-contract-form issue is pre-existing (orthogonal to Plan 16);
    Plan 21 should resolve it.
  - "EFA Standard floor doesn't move intraday" is a property of
    EFAStandardEoDDrawdown itself; we assert it directly on the policy
    rather than re-deriving it from journal snapshots. Cheaper + more
    precise than scraping equity_snapshots and the only thing the plan
    actually wanted to verify.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.journal.journal import Journal
from bot.observability.bus import NoopTelemetryBus
from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.runtime import FleetRuntime
from bot.runtime.fleet.spec import BotSpec
from bot.types import AccountState, Bar

_CT = ZoneInfo("America/Chicago")


def _spec(tmp_path: Path) -> BotSpec:
    """PropBot spec with bare-root symbol. See module docstring for why."""
    return BotSpec(
        name="propbot_e2e",
        enabled=True,
        symbol="MNQ",
        strategy_id="trend_ema_pullback",
        strategy_params={
            "symbol": "MNQ",
            "fast_ema": 5,
            "slow_ema": 10,
            "pullback_atr_mult": 0.5,
            "reward_ratio": 1.5,
            "max_trades_per_day": 1,
            "session_end_ct": "14:30",
        },
        risk_policy="efa_standard",
        risk_params={"mll_amount": 2_000},
        schedule_type="market_hours",
        schedule_params={"open_ct": "09:00", "close_ct": "14:30"},
        journal_path=tmp_path / "propbot.db",
    )


def _build_uptrend_session_bars() -> list[Bar]:
    """One trading day, 1-min bars from 09:00 to 14:30 CT.

    Pattern: 30 warm-up bars in a strong uptrend (EMA(5) climbs well above
    EMA(10), ATR builds), then a single pullback bar that dips back to the
    fast EMA, then more uptrend bars that should hit the +1.5R take-profit.
    The bar-source naturally terminates at 14:30 CT so the schedule's
    inclusive endpoint is exercised.
    """
    bars: list[Bar] = []
    start_ct = datetime(2026, 5, 22, 9, 0, tzinfo=_CT)
    start_utc = start_ct.astimezone(UTC)
    # 09:00 - 14:30 CT inclusive = 331 minutes; 330 1-min bars + the 14:30 close.
    total_minutes = 331
    # First 30 bars: strong uptrend +2pt/bar.
    closes: list[float] = []
    for i in range(30):
        closes.append(18_000.0 + i * 2.0)
    # Bar 30: pullback dip to roughly the fast EMA.
    closes.append(18_054.0)
    # Bars 31..: resume uptrend so TP is reached quickly.
    for i in range(31, total_minutes):
        closes.append(18_060.0 + (i - 30) * 5.0)

    for i, c in enumerate(closes):
        ts = start_utc + timedelta(minutes=i)
        # Tight high/low so ATR stays small and TP triggers on regular bars.
        bars.append(Bar(
            symbol="MNQ",
            open=c,
            high=c + 0.5,
            low=c - 0.5,
            close=c,
            volume=100,
            timestamp=ts,
            interval="1m",
        ))
    # Replace bar 30 (the pullback) with explicit low touching the fast EMA.
    pullback = bars[30]
    bars[30] = Bar(
        symbol="MNQ", open=pullback.open, high=pullback.high,
        low=18_053.0, close=18_054.0, volume=100,
        timestamp=pullback.timestamp, interval="1m",
    )
    return bars


class _StaticSource:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def subscribe(self) -> AsyncIterator[Bar]:
        for bar in self._bars:
            yield bar


@pytest.mark.asyncio
async def test_propbot_e2e_one_round_trip_zero_denials(tmp_path: Path) -> None:
    """PropBot opens one BUY on the pullback + closes it (TP or EoD). No denials."""
    sim = SimExecutionClient()
    await sim.connect()
    reg = BotRegistry()
    resolved = reg.build(_spec(tmp_path), broker=sim)
    bars = _build_uptrend_session_bars()

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
    assert results["propbot_e2e"].error is None
    assert results["propbot_e2e"].bars_processed == len(bars)

    # Inspect the per-bot journal directly.
    journal = await Journal.connect(str(tmp_path / "propbot.db"))
    try:
        # Risk decisions: one BUY approval + one close-side approval; zero denials.
        cursor = await journal._conn.execute(  # type: ignore[attr-defined]
            "SELECT side, approved, rule FROM risk_decisions ORDER BY id",
        )
        rows = await cursor.fetchall()
        await cursor.close()
        sides = [r[0] for r in rows]
        approvals = [r for r in rows if r[1] == 1]
        denials = [r for r in rows if r[1] == 0]
        assert len(denials) == 0, f"expected 0 denials, got {denials}"
        assert len(approvals) == 2, (
            f"expected 1 open + 1 close approval, got {len(approvals)}: {rows}"
        )
        # Round-trip = BUY then SELL (long entry + close).
        assert sides == ["BUY", "SELL"], f"unexpected side sequence: {sides}"

        # Final equity snapshot should be positive — the strategy made money on
        # the uptrend (long entry around 18_054, TP or EoD at higher price).
        snap = await journal.get_last_equity_snapshot()
        assert snap is not None
        assert snap.realized_pnl_today > 0
    finally:
        await journal.close()


def test_efa_standard_floor_does_not_move_intraday() -> None:
    """Regression: EFA Standard's phantom_mll is invariant under intraday equity
    swings (only update_on_eod moves the floor). Property check on the policy."""
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
    # Equity swings intraday — up $1500, then back down.
    swung_up = replace(base, equity=51_500.0)
    after_tick_up = policy.update_on_tick(swung_up)
    floor_after_up = policy.phantom_mll(after_tick_up)
    assert floor_after_up == floor_initial

    swung_down = replace(base, equity=49_700.0)
    after_tick_down = policy.update_on_tick(swung_down)
    floor_after_down = policy.phantom_mll(after_tick_down)
    assert floor_after_down == floor_initial

    # update_on_eod is the one path that may move it.
    eod = policy.update_on_eod(replace(base, equity=51_000.0))
    floor_after_eod = policy.phantom_mll(eod)
    assert floor_after_eod > floor_initial


def test_schedule_inclusive_endpoint_at_close() -> None:
    """A bar exactly at 14:30 CT should still be `should_trade` (inclusive).

    Belt-and-braces regression on the MarketHours endpoint semantics + the
    strategy's session_end_ct contract: the strategy emits a CLOSE on the
    14:30 bar; the schedule still says trade-window-open so the close intent
    flows through the gate (instead of being shorted on the schedule check).
    """
    from bot.runtime.fleet.schedule import MarketHours
    cutoff_ct = datetime(2026, 5, 22, 14, 30, tzinfo=_CT)
    sched = MarketHours(open_ct=time(9, 0), close_ct=time(14, 30))
    assert sched.should_trade(cutoff_ct.astimezone(UTC)) is True
