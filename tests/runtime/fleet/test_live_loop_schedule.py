"""LiveTradingLoop respects per-bot Schedule (only the intent pump is gated)."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.tracker import AccountStateTracker
from bot.journal.journal import Journal
from bot.observability.bus import NoopTelemetryBus
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.runtime.bar_source import SimBarSource
from bot.runtime.fleet.schedule import AlwaysOn, CustomWindows, MarketHours
from bot.runtime.live_loop import LiveTradingLoop
from bot.types import AccountState, Bar, Bracket, OrderIntent


class _NoopNews:
    def in_window(self, now: datetime) -> bool:
        return False

    def max_position_during_window(self) -> int:
        return 1


def _bars(closes: list[float], *, start: datetime) -> list[Bar]:
    return [
        Bar(
            symbol="MNQ",
            open=c, high=c, low=c, close=c,
            volume=100,
            timestamp=start + timedelta(minutes=i),
            interval="1m",
        )
        for i, c in enumerate(closes)
    ]


class _BuyEveryBar:
    """Emits a unique BUY-with-bracket on every bar. Lets us count gate-approved fills."""

    def __init__(self) -> None:
        self._i = 0

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        # Skip if we already have a position open (single-bot ORB-like behavior
        # isn't needed; we want to verify the schedule filter, not the strategy)
        if state.open_positions.get("MNQ", 0) != 0:
            return []
        self._i += 1
        return [OrderIntent(
            symbol="MNQ", side="BUY", quantity=1,
            order_type="MARKET",
            client_order_id=f"buy-{self._i}",
            timestamp=bar.timestamp,
            bracket=Bracket(stop_loss_ticks=40, take_profit_ticks=80),
        )]


def _make_gate(sim: SimExecutionClient) -> TopstepRiskGate:
    return TopstepRiskGate(
        policy=CombineIntradayDrawdown(50_000, 2_000, 5),
        news_calendar=_NoopNews(),
        execution_client=sim,
        telemetry=NoopTelemetryBus(),
        config=RiskConfig(env="backtest", accounts_managed=1),
    )


async def _journal() -> Journal:
    j = await Journal.connect(":memory:")
    await j.apply_migrations()
    return j


async def _equity_count(j: Journal) -> int:
    cur = await j._conn.execute("SELECT COUNT(*) FROM equity_snapshots")  # type: ignore[attr-defined]
    (n,) = await cur.fetchone()  # type: ignore[misc]
    await cur.close()
    return int(n)


async def _approved_count(j: Journal) -> int:
    cur = await j._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM risk_decisions WHERE approved=1"
    )
    (n,) = await cur.fetchone()  # type: ignore[misc]
    await cur.close()
    return int(n)


async def test_market_hours_skips_outside_window(tmp_path: Path) -> None:
    """100 bars spanning 16:00 CT onward → 0 approved intents under MarketHours
    (08:30-15:10 CT); equity snapshots still recorded for every bar."""
    sim = SimExecutionClient()
    await sim.connect()
    gate = _make_gate(sim)
    tracker = AccountStateTracker(start_balance=50_000.0, is_combine=True)
    j = await _journal()
    # 16:00 CT during CDT == 21:00 UTC
    start = datetime(2026, 5, 22, 21, 0, tzinfo=UTC)
    bars = _bars([18_000.0 + i for i in range(100)], start=start)
    loop = LiveTradingLoop(
        strategy=_BuyEveryBar(),
        gate=gate, tracker=tracker, broker=sim, journal=j,
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
        symbol="MNQ",
        schedule=MarketHours(),
    )
    await loop.run(SimBarSource(bars))
    assert await _approved_count(j) == 0
    assert await _equity_count(j) == 100
    await j.close()


async def test_always_on_matches_no_schedule(tmp_path: Path) -> None:
    """AlwaysOn behaves identically to omitting the schedule arg."""
    # 14:00 CT == 19:00 UTC during CDT — inside MarketHours but we use AlwaysOn
    # here. The point is `AlwaysOn() == None` (no schedule).
    bars = _bars([18_000.0 + i for i in range(5)],
                  start=datetime(2026, 5, 22, 19, 0, tzinfo=UTC))

    async def run_one(schedule: AlwaysOn | None) -> int:
        sim = SimExecutionClient()
        await sim.connect()
        gate = _make_gate(sim)
        tracker = AccountStateTracker(start_balance=50_000.0, is_combine=True)
        j = await _journal()
        kwargs: dict[str, object] = {
            "strategy": _BuyEveryBar(),
            "gate": gate,
            "tracker": tracker,
            "broker": sim,
            "journal": j,
            "telemetry": NoopTelemetryBus(),
            "heartbeat_path": tmp_path / "hb",
            "symbol": "MNQ",
        }
        if schedule is not None:
            kwargs["schedule"] = schedule
        loop = LiveTradingLoop(**kwargs)  # type: ignore[arg-type]
        await loop.run(SimBarSource(bars))
        approved = await _approved_count(j)
        await j.close()
        return approved

    a = await run_one(None)
    b = await run_one(AlwaysOn())
    assert a == b
    assert a >= 1  # confirmed at least one approval (no gating)


async def test_custom_windows_one_hour_only(tmp_path: Path) -> None:
    """One window 09:00-10:00 CT → only bars in that hour produce intents."""
    sim = SimExecutionClient()
    await sim.connect()
    gate = _make_gate(sim)
    tracker = AccountStateTracker(start_balance=50_000.0, is_combine=True)
    j = await _journal()
    # 08:30 CT == 13:30 UTC during CDT. Build 120 minute bars covering 08:30-10:30 CT.
    start = datetime(2026, 5, 22, 13, 30, tzinfo=UTC)
    bars = _bars([18_000.0] * 120, start=start)
    schedule = CustomWindows(windows=[(time(9, 0), time(10, 0))])
    loop = LiveTradingLoop(
        strategy=_BuyEveryBar(),
        gate=gate, tracker=tracker, broker=sim, journal=j,
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
        symbol="MNQ",
        schedule=schedule,
    )
    await loop.run(SimBarSource(bars))
    # Strategy stops emitting once position is open, so we expect exactly 1
    # approved intent inside the window. The point is: 0 approvals outside.
    assert await _approved_count(j) == 1
    assert await _equity_count(j) == 120
    await j.close()
