"""Plan 7 T4: Journal.record_* round-trip tests.

Each `record_*` writes one row and is callable from async code. Tests do a
round-trip: record → query back via raw SQL → assert values.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.journal.journal import Journal
from bot.types import (
    AccountState,
    Order,
    OrderDenied,
    OrderEvent,
    OrderIntent,
    Position,
)


@pytest.fixture
async def journal():
    j = await Journal.connect(":memory:")
    await j.apply_migrations()
    yield j
    await j.close()


def _now() -> datetime:
    return datetime(2026, 5, 22, 14, 30, tzinfo=UTC)


def _intent(coid: str = "coid-1") -> OrderIntent:
    return OrderIntent(
        symbol="MNQ",
        side="BUY",
        quantity=2,
        order_type="MARKET",
        client_order_id=coid,
        timestamp=_now(),
    )


def _state() -> AccountState:
    return AccountState(
        equity=50_000.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=50_000.0,
        is_combine=True,
        timestamp=_now(),
    )


async def test_record_order_round_trip(journal):
    order = Order(
        client_order_id="coid-1",
        broker_order_id="bx-9",
        symbol="MNQ",
        side="BUY",
        quantity=2,
        order_type="MARKET",
        status="WORKING",
        timestamp=_now(),
    )
    await journal.record_order(order)

    cur = await journal._conn.execute("SELECT client_order_id, symbol, side, quantity, status FROM orders")
    row = await cur.fetchone()
    await cur.close()
    assert row == ("coid-1", "MNQ", "BUY", 2, "WORKING")


async def test_record_fill_round_trip(journal):
    event = OrderEvent(
        client_order_id="coid-1",
        broker_order_id="bx-9",
        status="FILLED",
        filled_quantity=2,
        avg_fill_price=21000.25,
        timestamp=_now(),
    )
    await journal.record_fill(event)

    cur = await journal._conn.execute(
        "SELECT client_order_id, status, filled_quantity, avg_fill_price FROM fills"
    )
    row = await cur.fetchone()
    await cur.close()
    assert row == ("coid-1", "FILLED", 2, 21000.25)


async def test_record_position_round_trip(journal):
    pos = Position(
        symbol="MNQ",
        signed_qty=3,
        avg_entry_price=21000.0,
        unrealized_pnl=15.0,
        opened_at=_now(),
    )
    await journal.record_position(pos)

    cur = await journal._conn.execute(
        "SELECT symbol, signed_qty, avg_entry_price, unrealized_pnl FROM positions"
    )
    row = await cur.fetchone()
    await cur.close()
    assert row == ("MNQ", 3, 21000.0, 15.0)


async def test_record_risk_decision_approval(journal):
    # An approved order is stored with approved=1, rule=NULL, reason=NULL.
    intent = _intent("coid-A")
    await journal.record_risk_decision(intent=intent, approved=True, rule=None, reason=None, timestamp=_now())

    cur = await journal._conn.execute(
        "SELECT client_order_id, approved, rule, reason FROM risk_decisions"
    )
    row = await cur.fetchone()
    await cur.close()
    assert row == ("coid-A", 1, None, None)


async def test_record_risk_decision_denial(journal):
    intent = _intent("coid-D")
    denied = OrderDenied(
        intent=intent,
        reason="DLL would be breached",
        rule="DLL",
        state_snapshot=_state(),
        timestamp=_now(),
    )
    await journal.record_risk_decision(
        intent=denied.intent,
        approved=False,
        rule=denied.rule,
        reason=denied.reason,
        timestamp=denied.timestamp,
    )

    cur = await journal._conn.execute(
        "SELECT client_order_id, approved, rule, reason FROM risk_decisions"
    )
    row = await cur.fetchone()
    await cur.close()
    assert row == ("coid-D", 0, "DLL", "DLL would be breached")


async def test_record_equity_snapshot_round_trip(journal):
    await journal.record_equity_snapshot(_state())

    cur = await journal._conn.execute(
        "SELECT equity, realized_pnl_today, unrealized_pnl, high_water_equity, is_combine FROM equity_snapshots"
    )
    row = await cur.fetchone()
    await cur.close()
    assert row == (50_000.0, 0.0, 0.0, 50_000.0, 1)


async def test_record_session_start(journal):
    started = _now()
    await journal.record_session_start(started_at=started, notes="dev smoke")

    cur = await journal._conn.execute("SELECT started_at, notes FROM sessions")
    row = await cur.fetchone()
    await cur.close()
    assert row is not None
    assert row[0] == started.isoformat()
    assert row[1] == "dev smoke"


async def test_multiple_fills_appended(journal):
    for i, qty in enumerate([1, 1, 2]):
        await journal.record_fill(OrderEvent(
            client_order_id=f"coid-{i}",
            broker_order_id="bx",
            status="FILLED",
            filled_quantity=qty,
            avg_fill_price=21000.0,
            timestamp=_now(),
        ))
    cur = await journal._conn.execute("SELECT COUNT(*) FROM fills")
    row = await cur.fetchone()
    await cur.close()
    assert row is not None
    assert row[0] == 3
