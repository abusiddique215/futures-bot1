"""aiosqlite-backed Journal.

T3 ships connect/close + apply_migrations + introspection helpers. T4 adds
`record_*` methods; T5 adds `query_*` helpers + the in-memory cache that lets
Journal satisfy the sync `JournalProvider` Protocol from Plan 3.

WAL mode is set in `connect()`. For `:memory:` dbs the pragma silently
falls back to `memory` (SQLite spec) — tests tolerate either.
"""
from __future__ import annotations

import aiosqlite

from bot.journal.schema import DDL_STATEMENTS


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
