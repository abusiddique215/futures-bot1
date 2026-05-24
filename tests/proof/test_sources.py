"""Source adapters: JournalSource (SQLite) + BacktestLogSource (JSON)."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bot.journal.schema import DDL_STATEMENTS
from bot.proof.metrics import ClosedTrade
from bot.proof.sources import BacktestLogSource, JournalSource

# ---- helpers ----------------------------------------------------------------

def _init_journal_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        for ddl in DDL_STATEMENTS:
            conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()


def _insert_order(
    conn: sqlite3.Connection,
    *,
    coid: str,
    symbol: str,
    side: str,
    qty: int,
    ts: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO orders (
            client_order_id, broker_order_id, symbol, side, quantity,
            order_type, status, limit_price, stop_price, timestamp, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (coid, f"b-{coid}", symbol, side, qty, "MARKET", "FILLED",
         None, None, ts.isoformat(), None),
    )


def _insert_fill(
    conn: sqlite3.Connection,
    *,
    coid: str,
    qty: int,
    price: float,
    ts: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO fills (
            client_order_id, broker_order_id, status, filled_quantity,
            avg_fill_price, timestamp, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (coid, f"b-{coid}", "FILLED", qty, price, ts.isoformat(), None),
    )


def _ts(minute: int) -> datetime:
    return datetime(2026, 1, 1, 14, minute, tzinfo=UTC)


# ---- JournalSource ----------------------------------------------------------

def test_journal_source_two_round_trips_from_four_fills(tmp_path: Path) -> None:
    db = tmp_path / "j.db"
    _init_journal_db(db)
    conn = sqlite3.connect(db)
    try:
        # RT1: BUY 1 @16500 → SELL 1 @16550 = +50 pts * $2 = +$100
        _insert_order(conn, coid="o1", symbol="MNQ", side="BUY", qty=1, ts=_ts(0))
        _insert_fill(conn, coid="o1", qty=1, price=16_500.0, ts=_ts(0))
        _insert_order(conn, coid="o2", symbol="MNQ", side="SELL", qty=1, ts=_ts(5))
        _insert_fill(conn, coid="o2", qty=1, price=16_550.0, ts=_ts(5))
        # RT2: SELL 1 @16550 → BUY 1 @16575 = -25 pts * $2 = -$50
        _insert_order(conn, coid="o3", symbol="MNQ", side="SELL", qty=1, ts=_ts(10))
        _insert_fill(conn, coid="o3", qty=1, price=16_550.0, ts=_ts(10))
        _insert_order(conn, coid="o4", symbol="MNQ", side="BUY", qty=1, ts=_ts(15))
        _insert_fill(conn, coid="o4", qty=1, price=16_575.0, ts=_ts(15))
        conn.commit()
    finally:
        conn.close()

    src = JournalSource(db, bot_name=None)
    trades = list(src.iter_closed_trades())
    assert len(trades) == 2
    assert all(isinstance(t, ClosedTrade) for t in trades)
    assert trades[0].pnl == pytest.approx(100.0)
    assert trades[0].side == "BUY"
    assert trades[0].entry_price == 16_500.0
    assert trades[0].exit_price == 16_550.0
    assert trades[0].qty == 1
    assert trades[1].pnl == pytest.approx(-50.0)
    assert trades[1].side == "SELL"


def test_journal_source_empty_db(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    _init_journal_db(db)
    src = JournalSource(db, bot_name=None)
    assert list(src.iter_closed_trades()) == []


def test_journal_source_bot_filter_is_noop_on_current_schema(tmp_path: Path) -> None:
    """The orders table has no `bot_name` column yet (Plan 12 lands that).
    Filter is a graceful no-op: every fill is returned regardless of bot."""
    db = tmp_path / "j.db"
    _init_journal_db(db)
    conn = sqlite3.connect(db)
    try:
        _insert_order(conn, coid="o1", symbol="MNQ", side="BUY", qty=1, ts=_ts(0))
        _insert_fill(conn, coid="o1", qty=1, price=16_500.0, ts=_ts(0))
        _insert_order(conn, coid="o2", symbol="MNQ", side="SELL", qty=1, ts=_ts(5))
        _insert_fill(conn, coid="o2", qty=1, price=16_550.0, ts=_ts(5))
        conn.commit()
    finally:
        conn.close()

    # bot_name supplied — same result as None because schema lacks the column.
    src = JournalSource(db, bot_name="some_other_bot")
    trades = list(src.iter_closed_trades())
    assert len(trades) == 1


def test_journal_source_open_position_excluded(tmp_path: Path) -> None:
    """An unclosed leg is not emitted as a ClosedTrade."""
    db = tmp_path / "j.db"
    _init_journal_db(db)
    conn = sqlite3.connect(db)
    try:
        _insert_order(conn, coid="o1", symbol="MNQ", side="BUY", qty=1, ts=_ts(0))
        _insert_fill(conn, coid="o1", qty=1, price=16_500.0, ts=_ts(0))
        conn.commit()
    finally:
        conn.close()
    assert list(JournalSource(db, bot_name=None).iter_closed_trades()) == []


# ---- BacktestLogSource ------------------------------------------------------

def test_backtest_log_source_two_round_trips(tmp_path: Path) -> None:
    """BacktestLogSource reads a JSON file containing approved_orders pairs."""
    payload = {
        "approved_orders": [
            {
                "intent": {
                    "symbol": "MNQ",
                    "side": "BUY",
                    "quantity": 1,
                    "client_order_id": "rt1-open",
                    "timestamp": _ts(0).isoformat(),
                },
                "event": {
                    "client_order_id": "rt1-open",
                    "filled_quantity": 1,
                    "avg_fill_price": 16_500.0,
                    "timestamp": _ts(0).isoformat(),
                },
            },
            {
                "intent": {
                    "symbol": "MNQ",
                    "side": "SELL",
                    "quantity": 1,
                    "client_order_id": "rt1-close",
                    "timestamp": _ts(5).isoformat(),
                },
                "event": {
                    "client_order_id": "rt1-close",
                    "filled_quantity": 1,
                    "avg_fill_price": 16_550.0,
                    "timestamp": _ts(5).isoformat(),
                },
            },
            {
                "intent": {
                    "symbol": "MNQ",
                    "side": "SELL",
                    "quantity": 1,
                    "client_order_id": "rt2-open",
                    "timestamp": _ts(10).isoformat(),
                },
                "event": {
                    "client_order_id": "rt2-open",
                    "filled_quantity": 1,
                    "avg_fill_price": 16_550.0,
                    "timestamp": _ts(10).isoformat(),
                },
            },
            {
                "intent": {
                    "symbol": "MNQ",
                    "side": "BUY",
                    "quantity": 1,
                    "client_order_id": "rt2-close",
                    "timestamp": _ts(15).isoformat(),
                },
                "event": {
                    "client_order_id": "rt2-close",
                    "filled_quantity": 1,
                    "avg_fill_price": 16_575.0,
                    "timestamp": _ts(15).isoformat(),
                },
            },
        ]
    }
    path = tmp_path / "log.json"
    path.write_text(json.dumps(payload))

    src = BacktestLogSource(path)
    trades = list(src.iter_closed_trades())
    assert len(trades) == 2
    assert trades[0].pnl == pytest.approx(100.0)
    assert trades[1].pnl == pytest.approx(-50.0)


def test_backtest_log_source_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"approved_orders": []}))
    assert list(BacktestLogSource(path).iter_closed_trades()) == []
