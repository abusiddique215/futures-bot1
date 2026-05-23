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
    OrderStatus,
    OrderType,
    Position,
    Side,
)

# Order statuses that mean "this order is still in flight at the broker."
_OPEN_ORDER_STATUSES: tuple[OrderStatus, ...] = ("PENDING", "WORKING", "PARTIAL_FILL")


class Journal:
    """Async SQLite journal.

    Use the classmethod `await Journal.connect(path)` rather than __init__
    directly — connect() opens the underlying aiosqlite connection and sets
    WAL mode in a single await.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._closed = False
        # Sync PnL cache satisfies Plan 3's JournalProvider Protocol (gate.py
        # rule 6 calls these from sync code). Updated on every
        # record_equity_snapshot; recomputed in `connect()` if the db already
        # has rows.
        self._best_day_pnl: float = 0.0
        self._net_pnl: float = 0.0

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
        """Create the 6 tables. Idempotent — IF NOT EXISTS on every CREATE.

        After migration runs the PnL cache is rebuilt from `equity_snapshots`
        so reopening a populated db preserves rule 6 state.
        """
        for ddl in DDL_STATEMENTS:
            await self._conn.execute(ddl)
        await self._conn.commit()
        await self._recompute_pnl_cache()

    async def _recompute_pnl_cache(self) -> None:
        """Replay equity_snapshots in id order and rebuild the PnL cache."""
        cursor = await self._conn.execute(
            "SELECT realized_pnl_today FROM equity_snapshots ORDER BY id"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        best = 0.0
        net = 0.0
        for row in rows:
            net = float(row[0])
            if net > best:
                best = net
        self._best_day_pnl = best
        self._net_pnl = net

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
        """Insert a snapshot of AccountState (one row per tick or per minute).

        Bumps the sync PnL cache so subsequent best_day_pnl_so_far /
        net_pnl_so_far calls see the new value.
        """
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
        self._net_pnl = state.realized_pnl_today
        if state.realized_pnl_today > self._best_day_pnl:
            self._best_day_pnl = state.realized_pnl_today

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

    # ---- query_* helpers (reconcile + reporting) ---------------------------

    async def get_open_orders(self) -> list[Order]:
        """Return orders whose status is PENDING/WORKING/PARTIAL_FILL.

        Reconcile uses this on driver startup to compare against the broker's
        get_open_orders() and warn if they diverge.
        """
        placeholders = ", ".join("?" * len(_OPEN_ORDER_STATUSES))
        cursor = await self._conn.execute(
            f"""
            SELECT client_order_id, broker_order_id, symbol, side, quantity,
                   order_type, status, limit_price, stop_price, timestamp
            FROM orders
            WHERE status IN ({placeholders})
            """,
            _OPEN_ORDER_STATUSES,
        )
        rows = await cursor.fetchall()
        await cursor.close()
        out: list[Order] = []
        for row in rows:
            out.append(Order(
                client_order_id=row[0],
                broker_order_id=row[1],
                symbol=row[2],
                side=_cast_side(row[3]),
                quantity=row[4],
                order_type=_cast_order_type(row[5]),
                status=_cast_status(row[6]),
                limit_price=row[7],
                stop_price=row[8],
                timestamp=datetime.fromisoformat(row[9]),
            ))
        return out

    async def get_open_positions(self) -> list[Position]:
        """Return the latest non-flat position per symbol.

        Latest = max(id) per symbol. Plan 9 may switch to per-bar snapshots; v1
        is a single-row-per-update model.
        """
        cursor = await self._conn.execute(
            """
            SELECT symbol, signed_qty, avg_entry_price, unrealized_pnl, opened_at
            FROM positions
            WHERE id IN (
                SELECT MAX(id) FROM positions GROUP BY symbol
            )
            AND signed_qty != 0
            """
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            Position(
                symbol=row[0],
                signed_qty=row[1],
                avg_entry_price=row[2],
                unrealized_pnl=row[3],
                opened_at=datetime.fromisoformat(row[4]),
            )
            for row in rows
        ]

    async def get_last_equity_snapshot(self) -> AccountState | None:
        """Return the most recent equity_snapshot as a partial AccountState.

        open_positions / pending_intent_count are NOT persisted on this table;
        callers needing them should join with get_open_positions().
        """
        cursor = await self._conn.execute(
            """
            SELECT equity, realized_pnl_today, unrealized_pnl, high_water_equity,
                   is_locked, lock_point, is_combine, timestamp
            FROM equity_snapshots
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return AccountState(
            equity=row[0],
            realized_pnl_today=row[1],
            unrealized_pnl=row[2],
            open_positions={},
            pending_intent_count=0,
            high_water_equity=row[3],
            is_locked=bool(row[4]),
            lock_point=row[5],
            is_combine=bool(row[6]),
            timestamp=datetime.fromisoformat(row[7]),
        )

    # ---- JournalProvider Protocol satisfaction (sync) ----------------------
    #
    # Plan 3's gate.py rule 6 (_check_consistency) calls these inside sync code.
    # They MUST stay sync — the cache is updated on every record_equity_snapshot.
    #
    # v1 semantics (pragmatic):
    #   best_day_pnl_so_far = running max of realized_pnl_today over snapshots
    #                         (floored at 0 — no negative "best day")
    #   net_pnl_so_far      = latest snapshot's realized_pnl_today
    # Plan 9 may rework these once Journal becomes the canonical PnL ledger.

    def best_day_pnl_so_far(self) -> float:
        return self._best_day_pnl

    def net_pnl_so_far(self) -> float:
        return self._net_pnl


def _cast_side(s: str) -> Side:
    if s in ("BUY", "SELL"):
        return s  # type: ignore[return-value]
    raise ValueError(f"unrecognized side {s!r} in db")


def _cast_order_type(s: str) -> OrderType:
    if s in ("MARKET", "LIMIT", "STOP", "STOP_LIMIT", "BRACKET"):
        return s  # type: ignore[return-value]
    raise ValueError(f"unrecognized order_type {s!r} in db")


def _cast_status(s: str) -> OrderStatus:
    if s in ("PENDING", "WORKING", "PARTIAL_FILL", "FILLED", "CANCELED", "REJECTED"):
        return s  # type: ignore[return-value]
    raise ValueError(f"unrecognized status {s!r} in db")
