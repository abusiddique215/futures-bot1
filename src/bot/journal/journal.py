"""aiosqlite-backed Journal.

T3 ships connect/close + apply_migrations + introspection helpers. T4 adds
`record_*` methods; T5 adds `query_*` helpers + the in-memory cache that lets
Journal satisfy the sync `JournalProvider` Protocol from Plan 3.

WAL mode is set in `connect()`. For `:memory:` dbs the pragma silently
falls back to `memory` (SQLite spec) — tests tolerate either.
"""
from __future__ import annotations

from datetime import datetime

import aiosqlite

from bot.journal.schema import DDL_STATEMENTS
from bot.types import (
    AccountState,
    Order,
    OrderEvent,
    OrderIntent,
    Position,
)


class Journal:
    """Async SQLite journal.

    Use the classmethod `await Journal.connect(path)` rather than __init__
    directly — connect() opens the underlying aiosqlite connection and sets
    WAL mode in a single await.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._closed = False

    @classmethod
    async def connect(cls, path: str) -> Journal:
        """Open the journal at `path` (use ':memory:' for tests).

        Sets WAL mode for crash-safety. On in-memory dbs WAL silently degrades
        to `memory`; that's fine because in-memory dbs vanish on process exit
        anyway.
        """
        conn = await aiosqlite.connect(path)
        # WAL = writers don't block readers + atomic commits.
        await conn.execute("PRAGMA journal_mode=WAL")
        return cls(conn)

    async def apply_migrations(self) -> None:
        """Create the 6 tables. Idempotent — IF NOT EXISTS on every CREATE."""
        for ddl in DDL_STATEMENTS:
            await self._conn.execute(ddl)
        await self._conn.commit()

    async def close(self) -> None:
        """Close the underlying connection. Idempotent."""
        if self._closed:
            return
        await self._conn.close()
        self._closed = True

    # ---- Introspection helpers (used by tests + reconcile) ------------------

    async def list_tables(self) -> list[str]:
        """Return all user-defined table names in this db."""
        cursor = await self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [row[0] for row in rows]

    async def column_names(self, table: str) -> set[str]:
        """Return the column names of `table` as a set (for assert.issubset)."""
        cursor = await self._conn.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        await cursor.close()
        # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
        return {row[1] for row in rows}

    async def fetch_journal_mode(self) -> str:
        """Return the active journal_mode pragma (lowercase)."""
        cursor = await self._conn.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        await cursor.close()
        return str(row[0]).lower() if row is not None else "unknown"

    # ---- record_* event writers --------------------------------------------

    async def record_order(self, order: Order) -> None:
        """Insert an order snapshot (broker-reported open order)."""
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO orders (
                client_order_id, broker_order_id, symbol, side, quantity,
                order_type, status, limit_price, stop_price, timestamp, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.client_order_id,
                order.broker_order_id,
                order.symbol,
                order.side,
                order.quantity,
                order.order_type,
                order.status,
                order.limit_price,
                order.stop_price,
                order.timestamp.isoformat(),
                None,
            ),
        )
        await self._conn.commit()

    async def record_fill(self, event: OrderEvent) -> None:
        """Insert a fill event (or any OrderEvent — schema is flexible)."""
        await self._conn.execute(
            """
            INSERT INTO fills (
                client_order_id, broker_order_id, status, filled_quantity,
                avg_fill_price, timestamp, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.client_order_id,
                event.broker_order_id,
                event.status,
                event.filled_quantity,
                event.avg_fill_price,
                event.timestamp.isoformat(),
                None,
            ),
        )
        await self._conn.commit()

    async def record_position(self, position: Position) -> None:
        """Insert a position snapshot (broker-reported)."""
        await self._conn.execute(
            """
            INSERT INTO positions (
                symbol, signed_qty, avg_entry_price, unrealized_pnl,
                opened_at, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                position.symbol,
                position.signed_qty,
                position.avg_entry_price,
                position.unrealized_pnl,
                position.opened_at.isoformat(),
                position.opened_at.isoformat(),  # tracker-reported snapshot ts
            ),
        )
        await self._conn.commit()

    async def record_risk_decision(
        self,
        *,
        intent: OrderIntent,
        approved: bool,
        rule: str | None,
        reason: str | None,
        timestamp: datetime,
    ) -> None:
        """Insert a gate decision (one row per approve_or_deny call).

        For approvals: pass rule=None, reason=None.
        For denials:   pass rule + reason from OrderDenied.
        """
        await self._conn.execute(
            """
            INSERT INTO risk_decisions (
                client_order_id, approved, rule, reason,
                symbol, side, quantity, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent.client_order_id,
                1 if approved else 0,
                rule,
                reason,
                intent.symbol,
                intent.side,
                intent.quantity,
                timestamp.isoformat(),
            ),
        )
        await self._conn.commit()

    async def record_equity_snapshot(self, state: AccountState) -> None:
        """Insert a snapshot of AccountState (one row per tick or per minute)."""
        await self._conn.execute(
            """
            INSERT INTO equity_snapshots (
                equity, realized_pnl_today, unrealized_pnl, high_water_equity,
                is_locked, lock_point, is_combine, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.equity,
                state.realized_pnl_today,
                state.unrealized_pnl,
                state.high_water_equity,
                1 if state.is_locked else 0,
                state.lock_point,
                1 if state.is_combine else 0,
                state.timestamp.isoformat(),
            ),
        )
        await self._conn.commit()

    async def record_session_start(
        self, *, started_at: datetime, notes: str | None = None,
    ) -> None:
        """Insert a row marking session boundary (driver startup)."""
        await self._conn.execute(
            """
            INSERT INTO sessions (started_at, timestamp, notes)
            VALUES (?, ?, ?)
            """,
            (started_at.isoformat(), started_at.isoformat(), notes),
        )
        await self._conn.commit()
