"""Plan 7 T5: query_* helpers for reconcile + JournalProvider compatibility.

The async query helpers return broker-shape snapshots. The two sync helpers
(`best_day_pnl_so_far`, `net_pnl_so_far`) satisfy Plan 3's `JournalProvider`
Protocol — gate.py's rule 6 calls them inside sync code, so they MUST stay sync.

V1 semantics for the sync cache:
- `best_day_pnl_so_far` = running max of realized_pnl_today across snapshots
- `net_pnl_so_far`      = latest snapshot's realized_pnl_today
Both default to 0.0 with no snapshots (matches _NoopJournalProvider behavior).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from bot.journal.journal import Journal
from bot.risk.gate import JournalProvider
from bot.types import AccountState, Order, Position


def _now() -> datetime:
    return datetime(2026, 5, 22, 14, 30, tzinfo=UTC)


def _state(realized: float = 0.0, ts: datetime | None = None) -> AccountState:
    return AccountState(
        equity=50_000.0 + realized,
        realized_pnl_today=realized,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=50_000.0,
        is_combine=True,
        timestamp=ts or _now(),
    )


@pytest.fixture
async def journal():
    j = await Journal.connect(":memory:")
    await j.apply_migrations()
    yield j
    await j.close()


async def test_journal_satisfies_journal_provider_protocol(journal):
    # Runtime-checkable Protocol from gate.py rule 6.
    assert isinstance(journal, JournalProvider)


async def test_best_day_pnl_defaults_zero(journal):
    assert journal.best_day_pnl_so_far() == 0.0
    assert journal.net_pnl_so_far() == 0.0


async def test_best_day_pnl_tracks_running_max(journal):
    await journal.record_equity_snapshot(_state(realized=100.0))
    await journal.record_equity_snapshot(_state(realized=300.0))
    await journal.record_equity_snapshot(_state(realized=50.0))
    assert journal.best_day_pnl_so_far() == 300.0


async def test_net_pnl_is_latest_snapshot(journal):
    await journal.record_equity_snapshot(_state(realized=100.0))
    await journal.record_equity_snapshot(_state(realized=300.0))
    await journal.record_equity_snapshot(_state(realized=50.0))
    assert journal.net_pnl_so_far() == 50.0


async def test_best_day_negative_is_zero_floor(journal):
    # Losing days shouldn't bump "best day" above the all-losses zero.
    await journal.record_equity_snapshot(_state(realized=-100.0))
    await journal.record_equity_snapshot(_state(realized=-50.0))
    assert journal.best_day_pnl_so_far() == 0.0
    assert journal.net_pnl_so_far() == -50.0


async def test_get_open_orders_filters_terminal_states(journal):
    base = Order(
        client_order_id="x", broker_order_id="bx",
        symbol="MNQ", side="BUY", quantity=1, order_type="MARKET",
        status="WORKING", timestamp=_now(),
    )
    await journal.record_order(base)
    await journal.record_order(replace(base, client_order_id="y", status="FILLED"))
    await journal.record_order(replace(base, client_order_id="z", status="CANCELED"))
    await journal.record_order(replace(base, client_order_id="w", status="REJECTED"))
    await journal.record_order(replace(base, client_order_id="v", status="PARTIAL_FILL"))

    open_orders = await journal.get_open_orders()
    coids = {o.client_order_id for o in open_orders}
    assert coids == {"x", "v"}  # WORKING + PARTIAL_FILL


async def test_get_open_positions_returns_latest_per_symbol(journal):
    p1 = Position(symbol="MNQ", signed_qty=2, avg_entry_price=21000.0, unrealized_pnl=0.0, opened_at=_now())
    p2 = Position(symbol="MNQ", signed_qty=0, avg_entry_price=21000.0, unrealized_pnl=0.0, opened_at=_now())
    await journal.record_position(p1)
    await journal.record_position(p2)
    open_positions = await journal.get_open_positions()
    # latest snapshot is flat → no open positions
    assert open_positions == []


async def test_get_open_positions_returns_non_flat(journal):
    p = Position(symbol="MNQ", signed_qty=3, avg_entry_price=21000.0, unrealized_pnl=0.0, opened_at=_now())
    await journal.record_position(p)
    open_positions = await journal.get_open_positions()
    assert len(open_positions) == 1
    assert open_positions[0].symbol == "MNQ"
    assert open_positions[0].signed_qty == 3


async def test_get_last_equity_snapshot(journal):
    assert await journal.get_last_equity_snapshot() is None
    await journal.record_equity_snapshot(_state(realized=10.0))
    await journal.record_equity_snapshot(_state(realized=50.0))
    snap = await journal.get_last_equity_snapshot()
    assert snap is not None
    assert snap.realized_pnl_today == 50.0
