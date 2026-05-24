"""Dashboard read-only queries — Journal + heartbeat (Plan 21 T3).

Sync sqlite3 reads. Each per-bot journal is opened with
`file:<path>?mode=ro` so the dashboard cannot race the LiveTradingLoop's
WAL writer. The queries module has no FastAPI / Jinja2 dependency — it's
a pure data layer the routes module composes.

Data shapes:
  BotStatusRow   — one row on the fleet page per bot in `config/bots/`.
  BotDetailView  — full per-bot detail (positions, P&L, recent trades,
                   equity curve series).

Heartbeat:
  The FleetRuntime writes a single shared file (one path for the whole
  fleet — launchd cares whether the fleet is alive, not which bot last
  wrote). `get_fleet_heartbeat()` parses the ISO timestamp out of it.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from bot.runtime.fleet.spec import load_bot_specs


@dataclass(frozen=True)
class BotStatusRow:
    """Fleet-page row: name + enabled flag + journal status."""

    name: str
    enabled: bool
    symbol: str
    journal_path: Path
    # "running"  — journal has at least one equity_snapshot
    # "no_data"  — journal file missing or has no snapshots yet
    status: str


@dataclass(frozen=True)
class TradeRow:
    """One filled order from the journal's fills + orders join."""

    client_order_id: str
    symbol: str
    side: str
    quantity: int
    fill_price: float
    timestamp: datetime


@dataclass(frozen=True)
class EquityPoint:
    """One point on the equity curve."""

    timestamp: datetime
    equity: float
    realized_pnl: float


@dataclass(frozen=True)
class BotDetailView:
    """Bot-detail page payload."""

    bot_name: str
    open_positions: dict[str, int]
    realized_pnl_today: float
    equity: float
    high_water_equity: float
    recent_trades: list[TradeRow]
    equity_curve: list[EquityPoint]


# ---- list_bots --------------------------------------------------------------

def list_bots(bots_dir: Path) -> list[BotStatusRow]:
    """Read every `*.yml` under bots_dir → one BotStatusRow per file.

    Status is "running" iff the bot's journal exists AND has at least one
    equity_snapshot. Otherwise "no_data" (covers brand-new bots that
    haven't ticked yet + missing-journal-file).
    """
    specs = load_bot_specs(bots_dir)
    out: list[BotStatusRow] = []
    for spec in specs:
        out.append(BotStatusRow(
            name=spec.name,
            enabled=spec.enabled,
            symbol=spec.symbol,
            journal_path=spec.journal_path,
            status=_journal_status(spec.journal_path),
        ))
    return out


def _journal_status(path: Path) -> str:
    """Inspect the journal SQLite to classify the bot as running or no_data."""
    if not path.exists():
        return "no_data"
    try:
        with _ro_connect(path) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM equity_snapshots")
            (count,) = cur.fetchone()
    except sqlite3.OperationalError:
        # Table missing / db not initialised yet → no data.
        return "no_data"
    return "running" if count > 0 else "no_data"


# ---- get_bot_detail ---------------------------------------------------------

def get_bot_detail(
    bot_name: str, journal_path: Path, *, recent_trade_limit: int = 20,
) -> BotDetailView:
    """Open the journal + populate a BotDetailView. Missing → empty view."""
    if not journal_path.exists():
        return _empty_view(bot_name)

    try:
        with _ro_connect(journal_path) as conn:
            equity_curve = _query_equity_curve(conn)
            recent_trades = _query_recent_trades(conn, limit=recent_trade_limit)
            last_snap = _query_last_snapshot(conn)
            open_positions = _query_open_positions(conn)
    except sqlite3.OperationalError:
        return _empty_view(bot_name)

    if last_snap is None:
        realized = 0.0
        equity = 0.0
        high_water = 0.0
    else:
        realized, equity, high_water = last_snap

    return BotDetailView(
        bot_name=bot_name,
        open_positions=open_positions,
        realized_pnl_today=realized,
        equity=equity,
        high_water_equity=high_water,
        recent_trades=recent_trades,
        equity_curve=equity_curve,
    )


def _empty_view(bot_name: str) -> BotDetailView:
    return BotDetailView(
        bot_name=bot_name,
        open_positions={},
        realized_pnl_today=0.0,
        equity=0.0,
        high_water_equity=0.0,
        recent_trades=[],
        equity_curve=[],
    )


def _query_equity_curve(conn: sqlite3.Connection) -> list[EquityPoint]:
    cur = conn.execute(
        "SELECT timestamp, equity, realized_pnl_today "
        "FROM equity_snapshots ORDER BY id",
    )
    return [
        EquityPoint(
            timestamp=datetime.fromisoformat(row[0]),
            equity=float(row[1]),
            realized_pnl=float(row[2]),
        )
        for row in cur.fetchall()
    ]


def _query_recent_trades(
    conn: sqlite3.Connection, *, limit: int,
) -> list[TradeRow]:
    """Most recent `limit` fills, newest first.

    Joins fills against orders to recover symbol/side. The journal's
    orders table is populated only on snapshot writes (Plan 9-era code);
    if the order is missing we fall back to risk_decisions for symbol/side
    so dashboard rows still render.
    """
    # Try the risk_decisions join first since LiveTradingLoop always
    # records an approval row before placing the order.
    cur = conn.execute(
        """
        SELECT f.client_order_id, COALESCE(r.symbol, ''), COALESCE(r.side, ''),
               f.filled_quantity, COALESCE(f.avg_fill_price, 0.0), f.timestamp
        FROM fills f
        LEFT JOIN risk_decisions r ON r.client_order_id = f.client_order_id
                                   AND r.approved = 1
        ORDER BY f.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [
        TradeRow(
            client_order_id=row[0],
            symbol=row[1],
            side=row[2],
            quantity=int(row[3]),
            fill_price=float(row[4]),
            timestamp=datetime.fromisoformat(row[5]),
        )
        for row in cur.fetchall()
    ]


def _query_last_snapshot(
    conn: sqlite3.Connection,
) -> tuple[float, float, float] | None:
    """Return (realized_pnl_today, equity, high_water_equity) of newest snap."""
    cur = conn.execute(
        "SELECT realized_pnl_today, equity, high_water_equity "
        "FROM equity_snapshots ORDER BY id DESC LIMIT 1",
    )
    row = cur.fetchone()
    if row is None:
        return None
    return float(row[0]), float(row[1]), float(row[2])


def _query_open_positions(conn: sqlite3.Connection) -> dict[str, int]:
    """Latest non-flat positions, keyed by symbol."""
    try:
        cur = conn.execute(
            """
            SELECT symbol, signed_qty FROM positions
            WHERE id IN (SELECT MAX(id) FROM positions GROUP BY symbol)
              AND signed_qty != 0
            """,
        )
        return {row[0]: int(row[1]) for row in cur.fetchall()}
    except sqlite3.OperationalError:
        return {}


# ---- get_fleet_heartbeat ----------------------------------------------------

def get_fleet_heartbeat(heartbeat_path: Path) -> datetime | None:
    """Read the heartbeat file. Returns None if missing or unparseable.

    The heartbeat writer (bot.runtime.heartbeat) writes a single ISO
    timestamp via tmp + atomic rename, so a partial-truncate is
    impossible. Garbage contents → return None (don't crash the
    dashboard if a different writer somehow polluted the file).
    """
    if not heartbeat_path.exists():
        return None
    try:
        text = heartbeat_path.read_text(encoding="utf-8").strip()
        return datetime.fromisoformat(text)
    except (OSError, ValueError):
        return None


# ---- internals --------------------------------------------------------------

def _ro_connect(path: Path) -> sqlite3.Connection:
    """Open `path` read-only via SQLite URI so we can't race the WAL writer."""
    uri = f"file:{path}?mode=ro"
    return sqlite3.connect(uri, uri=True)
