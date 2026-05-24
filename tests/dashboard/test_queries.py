"""Dashboard read-only queries (Plan 21 T3).

queries.py reads per-bot journal SQLite files (opened with mode=ro so the
dashboard never contends with the WAL writer) plus the shared heartbeat
file. Pure data layer — no FastAPI / Jinja2 dependency.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bot.dashboard.queries import (
    BotDetailView,
    BotStatusRow,
    get_bot_detail,
    get_fleet_heartbeat,
    list_bots,
)
from bot.journal.journal import Journal
from bot.types import AccountState, OrderEvent, OrderIntent

# ---- list_bots --------------------------------------------------------------

def _spec_yaml(name: str, enabled: bool, journal: str) -> str:
    """Minimal valid BotSpec YAML."""
    return (
        f"name: {name}\n"
        f"enabled: {str(enabled).lower()}\n"
        "symbol: MNQH26\n"
        "strategy_id: orb_5m\n"
        "strategy_params:\n  range_minutes: 5\n"
        "risk_policy: efa_standard\n"
        "risk_params:\n  mll_amount: 2000\n"
        "schedule_type: market_hours\n"
        'schedule_params:\n  open_ct: "08:30"\n  close_ct: "15:00"\n'
        f"journal_path: {journal}\n"
    )


def test_list_bots_returns_one_row_per_yaml_file(tmp_path: Path) -> None:
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    (bots_dir / "alpha.yml").write_text(_spec_yaml("alpha", True, str(tmp_path / "a.db")))
    (bots_dir / "beta.yml").write_text(_spec_yaml("beta", False, str(tmp_path / "b.db")))

    rows = list_bots(bots_dir)
    by_name = {r.name: r for r in rows}
    assert set(by_name) == {"alpha", "beta"}
    assert by_name["alpha"].enabled is True
    assert by_name["beta"].enabled is False
    assert all(isinstance(r, BotStatusRow) for r in rows)


def test_list_bots_status_is_missing_when_no_journal_yet(tmp_path: Path) -> None:
    """A bot whose journal file doesn't exist gets `status='no_data'`."""
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    (bots_dir / "alpha.yml").write_text(
        _spec_yaml("alpha", True, str(tmp_path / "never_created.db")),
    )

    rows = list_bots(bots_dir)
    assert len(rows) == 1
    assert rows[0].status == "no_data"


async def test_list_bots_status_is_running_after_equity_snapshot(tmp_path: Path) -> None:
    """A bot whose journal has at least one equity_snapshot is `status='running'`."""
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    j_path = tmp_path / "a.db"
    (bots_dir / "alpha.yml").write_text(
        _spec_yaml("alpha", True, str(j_path)),
    )

    j = await Journal.connect(str(j_path))
    await j.apply_migrations()
    snap = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=False,
        timestamp=datetime(2026, 5, 24, 10, 0, tzinfo=UTC),
    )
    await j.record_equity_snapshot(snap)
    await j.close()

    rows = list_bots(bots_dir)
    assert rows[0].status == "running"


# ---- get_bot_detail ---------------------------------------------------------

async def test_get_bot_detail_returns_view_with_zero_data_for_fresh_journal(
    tmp_path: Path,
) -> None:
    """An empty journal: detail returns BotDetailView with empty fields, no crash."""
    j_path = tmp_path / "empty.db"
    j = await Journal.connect(str(j_path))
    await j.apply_migrations()
    await j.close()

    detail = get_bot_detail("alpha", j_path)
    assert isinstance(detail, BotDetailView)
    assert detail.bot_name == "alpha"
    assert detail.open_positions == {}
    assert detail.realized_pnl_today == 0.0
    assert detail.recent_trades == []
    assert detail.equity_curve == []


async def test_get_bot_detail_populates_fields_from_journal(tmp_path: Path) -> None:
    """Records 3 fills + 2 equity snapshots, expects them in the detail view."""
    j_path = tmp_path / "populated.db"
    j = await Journal.connect(str(j_path))
    await j.apply_migrations()

    base_ts = datetime(2026, 5, 24, 13, 30, tzinfo=UTC)
    # 3 fills (alternating BUY/SELL same symbol — closes a position twice).
    for i in range(3):
        intent = OrderIntent(
            symbol="MNQH26",
            side="BUY" if i % 2 == 0 else "SELL",
            quantity=1, order_type="MARKET",
            client_order_id=f"cid-{i}",
            timestamp=base_ts,
        )
        await j.record_risk_decision(
            intent=intent, approved=True, rule=None, reason=None,
            timestamp=base_ts,
        )
        await j.record_fill(OrderEvent(
            client_order_id=f"cid-{i}", broker_order_id=f"bid-{i}",
            status="FILLED", filled_quantity=1, avg_fill_price=18_000.0 + i,
            timestamp=base_ts,
        ))
    # 2 equity snapshots — the bot has $123 realized.
    for i in range(2):
        snap = AccountState(
            equity=50_000.0 + (i + 1) * 100.0,
            realized_pnl_today=123.0 if i == 1 else 0.0,
            unrealized_pnl=0.0,
            open_positions={},
            pending_intent_count=0,
            high_water_equity=50_100.0 if i == 1 else 50_000.0,
            is_combine=False,
            timestamp=base_ts,
        )
        await j.record_equity_snapshot(snap)
    await j.close()

    detail = get_bot_detail("alpha", j_path)
    assert detail.bot_name == "alpha"
    assert detail.realized_pnl_today == 123.0
    assert len(detail.recent_trades) == 3
    assert len(detail.equity_curve) == 2


def test_get_bot_detail_missing_journal_returns_empty_view(tmp_path: Path) -> None:
    """Journal file doesn't exist → BotDetailView with empties, no crash."""
    detail = get_bot_detail("alpha", tmp_path / "never_created.db")
    assert detail.bot_name == "alpha"
    assert detail.recent_trades == []
    assert detail.equity_curve == []


async def test_get_bot_detail_respects_recent_trade_cap(tmp_path: Path) -> None:
    """The view returns at most `limit` (default 20) recent trades, newest-first."""
    j_path = tmp_path / "manyfills.db"
    j = await Journal.connect(str(j_path))
    await j.apply_migrations()
    base_ts = datetime(2026, 5, 24, 13, 30, tzinfo=UTC)
    for i in range(50):
        intent = OrderIntent(
            symbol="MNQH26", side="BUY", quantity=1, order_type="MARKET",
            client_order_id=f"cid-{i}", timestamp=base_ts,
        )
        await j.record_risk_decision(
            intent=intent, approved=True, rule=None, reason=None,
            timestamp=base_ts,
        )
        await j.record_fill(OrderEvent(
            client_order_id=f"cid-{i}", broker_order_id=f"bid-{i}",
            status="FILLED", filled_quantity=1, avg_fill_price=18_000.0 + i,
            timestamp=base_ts,
        ))
    await j.close()

    detail = get_bot_detail("alpha", j_path, recent_trade_limit=10)
    assert len(detail.recent_trades) == 10


# ---- get_fleet_heartbeat ----------------------------------------------------

def test_get_fleet_heartbeat_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert get_fleet_heartbeat(tmp_path / "missing") is None


def test_get_fleet_heartbeat_parses_iso_timestamp(tmp_path: Path) -> None:
    hb = tmp_path / "heartbeat"
    ts = datetime(2026, 5, 24, 13, 30, 45, tzinfo=UTC)
    hb.write_text(ts.isoformat(), encoding="utf-8")

    parsed = get_fleet_heartbeat(hb)
    assert parsed == ts


def test_get_fleet_heartbeat_returns_none_on_garbage(tmp_path: Path) -> None:
    """A corrupt heartbeat doesn't crash the dashboard — returns None."""
    hb = tmp_path / "heartbeat"
    hb.write_text("not-an-iso-date", encoding="utf-8")
    assert get_fleet_heartbeat(hb) is None
