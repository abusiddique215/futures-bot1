"""TradeSource adapters: JournalSource (SQLite) + BacktestLogSource (JSON).

Both produce `Iterable[ClosedTrade]` so downstream rendering is source-agnostic.

JournalSource:
  Reads the journal SQLite db (read-only), joins fills → orders to recover the
  Side, walks per-symbol cash flow to detect round-trips (flat → flat). Mirrors
  the algorithm in bot.backtest.report._round_trip_pnls but emits ClosedTrade
  instead of just a P&L float.

  `bot_name` is accepted but is a no-op on the current schema (no bot_name
  column on orders yet — Plan 12 adds it). The try/except + filter-in-memory
  fallback keeps callers from breaking when the column lands later.

BacktestLogSource:
  Reads a JSON file shaped as `{"approved_orders": [{"intent": {...},
  "event": {...}}, ...]}` (mirrors TradeLog.approved_orders). This is the
  canonical interchange format for proof bundles generated off a finished
  backtest.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

from bot.constants import MIN_TICK, TICK_VALUES
from bot.proof.metrics import ClosedTrade
from bot.types import Side

_POINT_VALUE: dict[str, float] = {
    sym: TICK_VALUES[sym] / MIN_TICK[sym] for sym in TICK_VALUES
}


class TradeSource(Protocol):
    """Common surface consumed by ProofGenerator."""
    def iter_closed_trades(self) -> Iterable[ClosedTrade]: ...


@dataclass(frozen=True)
class _RawFill:
    """Intermediate shape after joining fills + orders / parsing JSON."""
    symbol: str
    side: Side
    qty: int
    price: float
    ts: datetime


class JournalSource:
    """Reads closed trades from a journal SQLite db (read-only)."""

    def __init__(self, journal_path: Path, bot_name: str | None) -> None:
        self._path = journal_path
        self._bot_name = bot_name

    def iter_closed_trades(self) -> Iterable[ClosedTrade]:
        return list(_walk_round_trips(self._load_fills()))

    def _load_fills(self) -> list[_RawFill]:
        # Read-only URI keeps a stray writer from racing the proof CLI.
        uri = f"file:{self._path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            # Try bot_name filter first (post-Plan-12 schema); fall back to no
            # filter if the column doesn't exist yet. Plan 12 adds the column.
            base_sql = """
                SELECT o.symbol, o.side, f.filled_quantity, f.avg_fill_price,
                       f.timestamp
                FROM fills f
                JOIN orders o ON o.client_order_id = f.client_order_id
                WHERE f.avg_fill_price IS NOT NULL
            """
            order_by = " ORDER BY f.timestamp, f.id"
            if self._bot_name is not None:
                try:
                    cursor = conn.execute(
                        base_sql + " AND o.bot_name = ?" + order_by,
                        (self._bot_name,),
                    )
                except sqlite3.OperationalError:
                    # bot_name column missing → fall back to unfiltered scan.
                    cursor = conn.execute(base_sql + order_by)
            else:
                cursor = conn.execute(base_sql + order_by)
            rows = cursor.fetchall()
        finally:
            conn.close()

        return [
            _RawFill(
                symbol=row[0],
                side=_cast_side(row[1]),
                qty=int(row[2]),
                price=float(row[3]),
                ts=datetime.fromisoformat(row[4]),
            )
            for row in rows
        ]


class BacktestLogSource:
    """Reads closed trades from a JSON file dumped from a BacktestEngine run."""

    def __init__(self, trade_log_path: Path) -> None:
        self._path = trade_log_path

    def iter_closed_trades(self) -> Iterable[ClosedTrade]:
        payload = json.loads(self._path.read_text())
        approved = cast(list[dict[str, dict[str, object]]],
                        payload.get("approved_orders", []))
        fills: list[_RawFill] = []
        for pair in approved:
            intent = pair["intent"]
            event = pair["event"]
            price = event.get("avg_fill_price")
            if price is None:
                continue
            fills.append(_RawFill(
                symbol=cast(str, intent["symbol"]),
                side=_cast_side(cast(str, intent["side"])),
                qty=int(cast(int, event["filled_quantity"])),
                price=float(cast(float, price)),
                ts=datetime.fromisoformat(cast(str, event["timestamp"])),
            ))
        return list(_walk_round_trips(fills))


# ---- shared round-trip walker -----------------------------------------------

def _walk_round_trips(fills: list[_RawFill]) -> Iterator[ClosedTrade]:
    """Per-symbol: each return-to-flat is one ClosedTrade.

    Mirrors bot.backtest.report._round_trip_pnls but additionally remembers
    the first opening fill (entry) and the closing fill (exit) so we can
    populate ClosedTrade's entry/exit fields.
    """
    # symbol -> running (signed_qty, cash_price_points, opener_ts, opener_price,
    #                    opener_side, opener_qty_abs)
    open_legs: dict[
        str, tuple[int, float, datetime, float, Side, int]
    ] = {}
    for fill in fills:
        signed = fill.qty if fill.side == "BUY" else -fill.qty
        existing = open_legs.get(fill.symbol)
        if existing is None:
            open_legs[fill.symbol] = (
                signed, -signed * fill.price,
                fill.ts, fill.price, fill.side, fill.qty,
            )
            continue
        qty, cash, op_ts, op_price, op_side, op_qty = existing
        new_qty = qty + signed
        new_cash = cash + (-signed * fill.price)
        if new_qty == 0 and qty != 0:
            pnl = new_cash * _POINT_VALUE[fill.symbol]
            yield ClosedTrade(
                entry_ts=op_ts,
                exit_ts=fill.ts,
                side=op_side,
                entry_price=op_price,
                exit_price=fill.price,
                qty=op_qty,
                pnl=pnl,
            )
            open_legs.pop(fill.symbol, None)
        else:
            open_legs[fill.symbol] = (
                new_qty, new_cash, op_ts, op_price, op_side, op_qty,
            )


def _cast_side(s: str) -> Side:
    if s in ("BUY", "SELL"):
        return cast(Side, s)
    raise ValueError(f"unrecognized side {s!r}")
