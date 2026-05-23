"""SQLite DDL for the Journal's 6 tables.

The schema is intentionally permissive — `metadata` columns hold JSON for any
broker-specific fields we don't want to model relationally. All timestamps are
ISO-8601 strings with tz info, stored as TEXT (sqlite has no native datetime).

Migrations are append-only and idempotent. v1 ships them all at once; later
plans can add an alembic-lite version table if real upgrades land.
"""
from __future__ import annotations

# Each statement runs independently; IF NOT EXISTS makes them idempotent.
DDL_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS orders (
        client_order_id TEXT PRIMARY KEY,
        broker_order_id TEXT,
        symbol          TEXT NOT NULL,
        side            TEXT NOT NULL,
        quantity        INTEGER NOT NULL,
        order_type      TEXT NOT NULL,
        status          TEXT NOT NULL,
        limit_price     REAL,
        stop_price      REAL,
        timestamp       TEXT NOT NULL,
        metadata        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fills (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        client_order_id TEXT NOT NULL,
        broker_order_id TEXT,
        status          TEXT NOT NULL,
        filled_quantity INTEGER NOT NULL,
        avg_fill_price  REAL,
        timestamp       TEXT NOT NULL,
        metadata        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol          TEXT NOT NULL,
        signed_qty      INTEGER NOT NULL,
        avg_entry_price REAL NOT NULL,
        unrealized_pnl  REAL NOT NULL,
        opened_at       TEXT NOT NULL,
        timestamp       TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_decisions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        client_order_id TEXT NOT NULL,
        approved        INTEGER NOT NULL,  -- 0/1 boolean
        rule            TEXT,              -- null on approval
        reason          TEXT,              -- null on approval
        symbol          TEXT NOT NULL,
        side            TEXT NOT NULL,
        quantity        INTEGER NOT NULL,
        timestamp       TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS equity_snapshots (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        equity              REAL NOT NULL,
        realized_pnl_today  REAL NOT NULL,
        unrealized_pnl      REAL NOT NULL,
        high_water_equity   REAL NOT NULL,
        is_locked           INTEGER NOT NULL,
        lock_point          REAL,
        is_combine          INTEGER NOT NULL,
        timestamp           TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at    TEXT NOT NULL,
        timestamp     TEXT NOT NULL,
        notes         TEXT
    )
    """,
)
