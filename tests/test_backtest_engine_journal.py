"""Plan 7 T8: BacktestEngine writes to Journal when one is provided.

The engine.run() stays synchronous for Plan 4 callers that pass no journal.
When a journal IS provided, callers MUST use the new async `run_async()` —
journal writes are aiosqlite (async). Tests run inside `async def` so they're
on the same event loop the Journal was opened on; aiosqlite connections are
loop-bound, so this is necessary.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from bot.backtest.engine import BacktestEngine
from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.tracker import AccountStateTracker
from bot.journal.journal import Journal
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.types import AccountState, Bar, Bracket, OrderIntent


class _NoopTel:
    def alert(self, kind: str, **kw: object) -> None:
        pass


class _NoopNews:
    def in_window(self, now: datetime) -> bool:
        return False

    def max_position_during_window(self) -> int:
        return 1


def _make_gate(sim: SimExecutionClient) -> TopstepRiskGate:
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    return TopstepRiskGate(
        policy=policy,
        news_calendar=_NoopNews(),
        execution_client=sim,
        telemetry=_NoopTel(),
        config=cfg,
    )


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    return [
        Bar(symbol="MNQ", open=c, high=c, low=c, close=c, volume=100,
            timestamp=start + timedelta(minutes=i), interval="1m")
        for i, c in enumerate(closes)
    ]


class _OneShot:
    """BUY 1 at bar 0, SELL 1 at bar 5 — produces 2 fills + 2 approvals."""

    def __init__(self) -> None:
        self._i = 0

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        i = self._i
        self._i += 1
        if i == 0:
            return [OrderIntent(
                symbol="MNQ", side="BUY", quantity=1,
                order_type="MARKET", client_order_id="o-1",
                timestamp=bar.timestamp,
                bracket=Bracket(stop_loss_ticks=40, take_profit_ticks=80),
            )]
        if i == 5:
            return [OrderIntent(
                symbol="MNQ", side="SELL", quantity=1,
                order_type="MARKET", client_order_id="c-1",
                timestamp=bar.timestamp,
            )]
        return []


async def test_engine_runs_without_journal_unchanged():
    # Regression: engine without journal works as Plan 4 originally shipped.
    sim = SimExecutionClient()
    tracker = AccountStateTracker(start_balance=50_000, is_combine=True)
    engine = BacktestEngine(
        strategy=_OneShot(), gate=_make_gate(sim),
        tracker=tracker, sim=sim, symbol="MNQ",
    )
    log = engine.run(_bars([16_500.0 + i for i in range(8)]))
    assert log.intents_approved == 2
    assert len(log.fills) == 2


async def test_engine_with_journal_persists_fills():
    journal = await Journal.connect(":memory:")
    await journal.apply_migrations()
    try:
        sim = SimExecutionClient()
        tracker = AccountStateTracker(start_balance=50_000, is_combine=True)
        engine = BacktestEngine(
            strategy=_OneShot(), gate=_make_gate(sim),
            tracker=tracker, sim=sim, symbol="MNQ",
            journal=journal,
        )
        await engine.run_async(_bars([16_500.0 + i for i in range(8)]))

        cur = await journal._conn.execute("SELECT COUNT(*) FROM fills")
        row = await cur.fetchone()
        await cur.close()
        assert row is not None
        assert row[0] == 2
    finally:
        await journal.close()


async def test_engine_with_journal_persists_risk_decisions():
    journal = await Journal.connect(":memory:")
    await journal.apply_migrations()
    try:
        sim = SimExecutionClient()
        tracker = AccountStateTracker(start_balance=50_000, is_combine=True)
        engine = BacktestEngine(
            strategy=_OneShot(), gate=_make_gate(sim),
            tracker=tracker, sim=sim, symbol="MNQ",
            journal=journal,
        )
        await engine.run_async(_bars([16_500.0 + i for i in range(8)]))

        cur = await journal._conn.execute(
            "SELECT COUNT(*), SUM(approved) FROM risk_decisions"
        )
        row = await cur.fetchone()
        await cur.close()
        assert row is not None
        # 2 intents, both approved
        assert row[0] == 2
        assert row[1] == 2
    finally:
        await journal.close()


async def test_engine_with_journal_records_equity_snapshot_per_bar():
    journal = await Journal.connect(":memory:")
    await journal.apply_migrations()
    try:
        sim = SimExecutionClient()
        tracker = AccountStateTracker(start_balance=50_000, is_combine=True)
        engine = BacktestEngine(
            strategy=_OneShot(), gate=_make_gate(sim),
            tracker=tracker, sim=sim, symbol="MNQ",
            journal=journal,
        )
        n_bars = 8
        await engine.run_async(_bars([16_500.0 + i for i in range(n_bars)]))

        cur = await journal._conn.execute("SELECT COUNT(*) FROM equity_snapshots")
        row = await cur.fetchone()
        await cur.close()
        assert row is not None
        assert row[0] == n_bars
    finally:
        await journal.close()


async def test_engine_with_journal_records_denials():
    # Override OneShot to emit an intent that will be denied (qty=0 → MAX_POSITION
    # isn't denied, but submitting BUY 1000 with no bracket triggers STOP_REQUIRED).
    class _DenyStrategy:
        def __init__(self) -> None:
            self._fired = False

        def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
            if self._fired:
                return []
            self._fired = True
            return [OrderIntent(
                symbol="MNQ", side="BUY", quantity=1000,
                order_type="MARKET", client_order_id="dn-1",
                timestamp=bar.timestamp,
            )]

    journal = await Journal.connect(":memory:")
    await journal.apply_migrations()
    try:
        sim = SimExecutionClient()
        tracker = AccountStateTracker(start_balance=50_000, is_combine=True)
        engine = BacktestEngine(
            strategy=_DenyStrategy(), gate=_make_gate(sim),
            tracker=tracker, sim=sim, symbol="MNQ",
            journal=journal,
        )
        log = await engine.run_async(_bars([16_500.0, 16_500.0]))
        assert len(log.intents_denied) == 1

        cur = await journal._conn.execute(
            "SELECT approved, rule FROM risk_decisions"
        )
        rows = await cur.fetchall()
        await cur.close()
        assert (0, "STOP_REQUIRED") in rows
    finally:
        await journal.close()
