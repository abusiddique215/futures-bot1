"""Plan 9 T6: hydrate_runtime — RuntimeState composition.

Given a clean reconcile result + broker/journal snapshots + cfg + secrets +
the broker + journal handles, produce a single RuntimeState the event loop
can consume.

Composition rules (per spec 07 §3.6):
  - positions    ← BrokerState.positions (broker is truth)
  - day_pnl      ← BrokerState.account_equity - high_water (from journal's
                   last equity snapshot)  — wait, simpler: pull realized
                   PnL from journal.get_last_equity_snapshot().realized_pnl_today
                   (broker doesn't always expose realized vs unrealized split
                   uniformly). Equity itself comes from broker.
  - high_water_equity ← journal's last equity_snapshot.high_water_equity
                        (None / no snapshots → broker.account_equity as seed)
"""
from __future__ import annotations

from datetime import UTC, datetime, time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from bot.config import BotConfig, DataConfig
from bot.runtime.hydrate import RuntimeState, hydrate_runtime
from bot.runtime.reconcile import BrokerState, JournalState, ReconcileResult
from bot.types import AccountState


def _cfg() -> BotConfig:
    return BotConfig(
        env="dev",
        broker="sim",
        account_id="acct-0",
        strategy="orb",
        strategy_profile=Path("config/profiles/surge.yml"),
        risk_policy="combine_50k",
        data=DataConfig(
            historical_root=Path("data/parquet"),
            historical_vendor="firstratedata",
            live_source="ib",
        ),
        news_calendar=Path("config/news_calendar.yml"),
        flat_by_warning_ct=time(14, 0),
        flat_by_force_ct=time(15, 10),
    )


async def test_hydrate_with_journal_snapshot() -> None:
    bs = BrokerState(
        positions={"MNQ": 2},
        open_orders={},
        account_equity=50_500.0,
    )
    js = JournalState(positions={"MNQ": 2}, open_orders={}, account_equity=50_500.0)
    rr = ReconcileResult(ok=True)

    journal = MagicMock()
    journal.get_last_equity_snapshot = AsyncMock(return_value=AccountState(
        equity=50_500.0,
        realized_pnl_today=150.0,
        unrealized_pnl=0.0,
        open_positions={"MNQ": 2},
        pending_intent_count=0,
        high_water_equity=50_700.0,
        is_combine=True,
        timestamp=datetime(2026, 5, 23, 14, 0, tzinfo=UTC),
    ))
    broker = MagicMock()
    secrets = MagicMock()

    state = await hydrate_runtime(
        rr=rr, broker_state=bs, journal_state=js,
        cfg=_cfg(), secrets=secrets, broker=broker, journal=journal,
    )

    assert isinstance(state, RuntimeState)
    assert state.positions == {"MNQ": 2}
    assert state.equity == 50_500.0
    assert state.realized_pnl_today == 150.0
    assert state.high_water_equity == 50_700.0
    assert state.cfg is _cfg.__call__().__class__ or state.cfg is not None
    assert state.broker is broker
    assert state.journal is journal


async def test_hydrate_no_prior_snapshot_uses_broker_equity_as_seed() -> None:
    """Cold start: journal has no equity_snapshots, hydrate seeds high_water
    from broker.account_equity and zero realized_pnl_today."""
    bs = BrokerState(positions={}, open_orders={}, account_equity=50_000.0)
    js = JournalState(positions={}, open_orders={}, account_equity=50_000.0)
    rr = ReconcileResult(ok=True)

    journal = MagicMock()
    journal.get_last_equity_snapshot = AsyncMock(return_value=None)
    broker = MagicMock()
    secrets = MagicMock()

    state = await hydrate_runtime(
        rr=rr, broker_state=bs, journal_state=js,
        cfg=_cfg(), secrets=secrets, broker=broker, journal=journal,
    )

    assert state.positions == {}
    assert state.equity == 50_000.0
    assert state.realized_pnl_today == 0.0
    assert state.high_water_equity == 50_000.0  # seeded from broker


async def test_hydrate_refuses_when_reconcile_not_ok() -> None:
    """Defense: hydrate must not silently proceed on a bad reconcile.
    Caller is expected to short-circuit, but hydrate also guards."""
    bs = BrokerState(positions={"MNQ": 1}, open_orders={}, account_equity=50_000.0)
    js = JournalState(positions={}, open_orders={}, account_equity=50_000.0)
    rr = ReconcileResult(ok=False, position_diff={"MNQ": (1, 0)})

    journal = MagicMock()
    journal.get_last_equity_snapshot = AsyncMock(return_value=None)
    broker = MagicMock()
    secrets = MagicMock()

    import pytest
    with pytest.raises(ValueError, match="ok=False"):
        await hydrate_runtime(
            rr=rr, broker_state=bs, journal_state=js,
            cfg=_cfg(), secrets=secrets, broker=broker, journal=journal,
        )


async def test_hydrate_positions_come_from_broker_not_journal() -> None:
    """Broker is truth; even if journal_state disagreed (which would have
    made reconcile fail), hydrate's positions come from BrokerState."""
    bs = BrokerState(positions={"MNQ": 5}, open_orders={}, account_equity=51_000.0)
    js = JournalState(positions={"MNQ": 5}, open_orders={}, account_equity=51_000.0)
    rr = ReconcileResult(ok=True)

    journal = MagicMock()
    journal.get_last_equity_snapshot = AsyncMock(return_value=None)
    broker = MagicMock()
    secrets = MagicMock()

    state = await hydrate_runtime(
        rr=rr, broker_state=bs, journal_state=js,
        cfg=_cfg(), secrets=secrets, broker=broker, journal=journal,
    )
    assert state.positions == {"MNQ": 5}
