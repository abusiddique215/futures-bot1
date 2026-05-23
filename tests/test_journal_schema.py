"""Plan 7 T3: Journal schema + migrations.

The Journal is the SQLite-backed source of truth for every order, fill,
position snapshot, gate decision, equity snapshot, and session boundary.
6 tables, WAL mode (where the journal type supports it; in-memory is fine).

Tests use `:memory:` so they're hermetic — no tmp file, no iCloud sqlite
corruption hazard.
"""
from __future__ import annotations

import pytest

from bot.journal.journal import Journal

ALL_TABLES = {
    "orders",
    "fills",
    "positions",
    "risk_decisions",
    "equity_snapshots",
    "sessions",
}


async def test_apply_migrations_creates_six_tables():
    j = await Journal.connect(":memory:")
    try:
        await j.apply_migrations()
        names = await j.list_tables()
        assert ALL_TABLES.issubset(set(names))
    finally:
        await j.close()


async def test_apply_migrations_is_idempotent():
    j = await Journal.connect(":memory:")
    try:
        await j.apply_migrations()
        # Second call must not raise.
        await j.apply_migrations()
        names = await j.list_tables()
        assert ALL_TABLES.issubset(set(names))
    finally:
        await j.close()


async def test_wal_mode_pragma_set():
    # In-memory dbs report `memory` not `wal` for journal_mode (sqlite spec).
    # The pragma should still execute without raising.
    j = await Journal.connect(":memory:")
    try:
        await j.apply_migrations()
        mode = await j.fetch_journal_mode()
        assert mode in {"wal", "memory"}
    finally:
        await j.close()


async def test_wal_mode_on_disk(tmp_path):
    # File-backed dbs (outside iCloud thanks to tmp_path) should land in WAL.
    db_path = tmp_path / "journal.sqlite"
    j = await Journal.connect(str(db_path))
    try:
        await j.apply_migrations()
        mode = await j.fetch_journal_mode()
        assert mode == "wal"
    finally:
        await j.close()


async def test_close_is_idempotent():
    j = await Journal.connect(":memory:")
    await j.apply_migrations()
    await j.close()
    # Calling close twice must not raise.
    await j.close()


async def test_orders_table_has_expected_columns():
    j = await Journal.connect(":memory:")
    try:
        await j.apply_migrations()
        cols = await j.column_names("orders")
        # Minimum core columns we record from OrderEvent / OrderIntent
        assert {"client_order_id", "symbol", "side", "quantity", "status", "timestamp"}.issubset(cols)
    finally:
        await j.close()


async def test_risk_decisions_table_records_rule_and_reason():
    j = await Journal.connect(":memory:")
    try:
        await j.apply_migrations()
        cols = await j.column_names("risk_decisions")
        assert {"client_order_id", "rule", "reason", "approved", "timestamp"}.issubset(cols)
    finally:
        await j.close()


@pytest.mark.parametrize(
    "table",
    sorted(ALL_TABLES),
)
async def test_every_table_has_timestamp_column(table):
    j = await Journal.connect(":memory:")
    try:
        await j.apply_migrations()
        cols = await j.column_names(table)
        assert "timestamp" in cols, f"{table} missing timestamp column"
    finally:
        await j.close()
