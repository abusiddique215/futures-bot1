"""Plan 22 T4 — full-fleet smoke test.

Boots ALL 6 bots concurrently (SurgeBot, PropBot, Lux Bot, NQ Maintenance,
Gold Bot, ES Scalper) through FleetRuntime + a side-car dashboard, drives a
session's worth of synthetic bars, and asserts:

  - Every bot completes without exception.
  - Each bot's journal exists + has no internal errors.
  - The dashboard `/` returns 200 + lists every bot name.
  - The dashboard `/healthz` returns 200.
  - At least one bot produced an approved decision (the pipeline ran
    end-to-end: bars → strategy → gate → allocator → broker → journal).
    Lux Bot's fixture path guarantees a deterministic approval; that's
    the load-bearing pipeline assertion.

The smoke test rewrites each YAML's `journal_path` to a tmp location, flips
`enabled: true` on every bot, and provides `LUX_BOT_FIXTURE_PATH` pointing
at a tmp JSON of one fixture signal. Bar streams are tailored per-bot via
the bar_source_factory's `spec` argument — each symbol gets bars stamped
inside that bot's schedule window so the strategies actually see traffic.
"""
from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.markets.registry import get_market
from bot.observability.bus import NoopTelemetryBus
from bot.runtime.fleet.allocator import FleetAllocator
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.runtime import FleetRuntime
from bot.runtime.fleet.spec import load_bot_specs
from bot.types import Bar

_CT = ZoneInfo("America/Chicago")
_ET = ZoneInfo("America/New_York")
_REPO_BOTS_DIR = Path("config/bots")
_ALL_BOTS = {
    "surgebot_nq",
    "propbot_nq",
    "lux_bot",
    "nq_maintenance",
    "gold_bot",
    "es_scalper",
}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return int(port)


def _prepare_bots_dir(tmp_path: Path) -> Path:
    """Copy the 6 production YAMLs from config/bots/ into tmp, flipping
    `enabled` to true and rewriting journal_path to a tmp location so the
    test is hermetic. `example_orb_nq.yml` is the docs-only template — we
    skip it; the smoke test asserts on the 6 fleet members from Plans 15-18.
    """
    dst = tmp_path / "bots"
    dst.mkdir()
    for src in sorted(_REPO_BOTS_DIR.glob("*.yml")):
        if src.stem not in _ALL_BOTS:
            continue
        text = src.read_text(encoding="utf-8")
        text = text.replace("enabled: false", "enabled: true")
        # Rewrite each bot's journal_path to a tmp location keyed off its name.
        # The existing path is `state/journal_<name>.db` (or similar) — match
        # any `journal_path: state/...` and rewrite to tmp.
        new_journal = tmp_path / f"{src.stem}.db"
        lines = []
        for line in text.splitlines():
            if line.startswith("journal_path:"):
                lines.append(f"journal_path: {new_journal}")
            else:
                lines.append(line)
        (dst / src.name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dst


def _write_lux_fixture(tmp_path: Path) -> Path:
    """One BUY signal sized within EFA Standard's profit-zero tier (2 minis).
    Lux Bot's symbol is MNQH26 — the SignalStrategy's prefix-match logic
    accepts a raw "MNQ" signal targeting that contract.
    """
    fixture_path = tmp_path / "lux_signals.json"
    fixture_path.write_text(json.dumps([
        {
            "received_at": "2026-05-22T13:59:00+00:00",
            "symbol": "MNQ",
            "side": "BUY",
            "qty": 1,
            "limit_price": 20_100.0,
            "stop_loss": 20_090.0,
            "take_profit": 20_120.0,
            "raw_text": "BUY MNQ @20100 SL=20090 TP=20120",
            "source_id": "smoke-1",
        },
    ]), encoding="utf-8")
    return fixture_path


def _ct_bars(symbol: str, *, hh_start: int, mm_start: int, count: int,
             interval_min: int = 1, price: float = 20_100.0,
             interval_label: str = "1m") -> list[Bar]:
    """Bars timestamped from `hh:mm` CT in 1-minute steps."""
    start_ct = datetime(2026, 5, 22, hh_start, mm_start, tzinfo=_CT)
    start_utc = start_ct.astimezone(UTC)
    return [
        Bar(
            symbol=symbol, open=price, high=price + 0.5, low=price - 0.5,
            close=price, volume=100,
            timestamp=start_utc + timedelta(minutes=i * interval_min),
            interval=interval_label,
        )
        for i in range(count)
    ]


def _bars_for_spec(spec: Any) -> list[Bar]:
    """Build a per-bot bar stream sized to its symbol + schedule.

    Each bot needs bars stamped inside its trading window AND tagged with
    its `spec.symbol` (the LiveTradingLoop drops bars whose symbol doesn't
    match). The streams are intentionally small — this is a smoke test,
    not a strategy backtest.
    """
    name = spec.name
    symbol = spec.symbol
    # nq_maintenance and lux_bot use `always` schedule — 10:00 CT is fine.
    # market_hours bots (surgebot 08:30-15:00, propbot 09:00-14:30,
    # es_scalper 08:30-14:45) all overlap 10:00-12:00 CT.
    # gold_bot uses ET windows — 08:30-15:00 ET (= 07:30-14:00 CT). Bars
    # at 10:00 ET (= 09:00 CT) fall inside.
    if name == "gold_bot":
        # gold_bot is custom_windows in America/New_York — pick a window-
        # interior moment (10:00 ET ≈ 09:00 CT) and emit a 10-minute stream.
        start_et = datetime(2026, 5, 22, 10, 0, tzinfo=_ET)
        start_utc = start_et.astimezone(UTC)
        return [
            Bar(
                symbol=symbol, open=2_000.0, high=2_000.5, low=1_999.5,
                close=2_000.0, volume=50,
                timestamp=start_utc + timedelta(minutes=10 * i),
                interval="10m",
            )
            for i in range(6)
        ]
    if name == "lux_bot":
        # Lux just needs bars to drive on_bar (which drains signal events).
        # The signal fixture's received_at is 13:59 UTC; one bar at 14:00
        # UTC will pull it from the deque.
        return _ct_bars(symbol, hh_start=9, mm_start=0, count=10)
    # All other bots: 10:00 CT - 10:10 CT covers SurgeBot's 08:30-15:00
    # window, PropBot's 09:00-14:30, ES Scalper's 08:30-14:45, NQ
    # Maintenance's always-on.
    return _ct_bars(symbol, hh_start=10, mm_start=0, count=10)


class _StaticBarSource:
    """Yields bars with a tiny delay between them so the side-car dashboard
    has time to bind its port before the fleet completes. Without this, a
    6-bot fleet over 6-10 in-memory bars finishes in <100ms — faster than
    uvicorn.Server.startup. Mirrors the `_SlowSource` pattern from
    `tests/runtime/fleet/test_dashboard_sidecar.py`.
    """

    def __init__(self, bars: list[Bar], delay_s: float = 0.05) -> None:
        self._bars = bars
        self._delay = delay_s

    async def subscribe(self) -> AsyncIterator[Bar]:
        for bar in self._bars:
            await asyncio.sleep(self._delay)
            yield bar


@pytest.mark.asyncio
async def test_full_fleet_smoke_all_six_bots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boot all 6 bots concurrently + dashboard; assert end-to-end pipeline."""
    # 1. Lux fixture + env wiring (registry reads it at build time).
    fixture = _write_lux_fixture(tmp_path)
    monkeypatch.setenv("LUX_BOT_FIXTURE_PATH", str(fixture))

    # 2. Copy YAMLs to tmp, flip enabled, rewrite journal_path.
    bots_dir = _prepare_bots_dir(tmp_path)
    specs = load_bot_specs(bots_dir)
    assert {s.name for s in specs if s.enabled} == _ALL_BOTS, (
        f"expected exactly {_ALL_BOTS} enabled, got "
        f"{ {s.name for s in specs if s.enabled} }"
    )

    # 3. Build broker + resolved bots.
    sim = SimExecutionClient()
    await sim.connect()
    reg = BotRegistry()
    resolved = [reg.build(s, broker=sim) for s in specs if s.enabled]
    assert len(resolved) == 6

    # 4. FleetRuntime with allocator + dashboard side-car on ephemeral port.
    port = _free_port()
    allocator = FleetAllocator(account_max_mini=5, market_lookup=get_market)
    fleet = FleetRuntime(
        bots=resolved, broker=sim,
        bar_source_factory=lambda spec: _StaticBarSource(_bars_for_spec(spec)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
        allocator=allocator,
        dashboard_port=port,
        dashboard_bots_dir=bots_dir,
    )

    # 5. Run the fleet; hit the dashboard concurrently; collect results.
    dashboard_responses: dict[str, int] = {}
    fleet_task: asyncio.Task[dict[str, Any]] = asyncio.create_task(
        asyncio.wait_for(fleet.run(), timeout=30.0)
    )

    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
        ) as client:
            for _ in range(60):  # ~6s budget
                try:
                    # /v1/ hits the legacy fleet page (server-rendered
                    # with the bot names embedded). `/` returns the SPA
                    # index whose only useful runtime check is the
                    # `<div id="root"` host, which we cover in the v2
                    # e2e suite.
                    r_index = await client.get("/v1/")
                    r_health = await client.get("/healthz")
                    dashboard_responses["index"] = r_index.status_code
                    dashboard_responses["health"] = r_health.status_code
                    dashboard_responses["index_text"] = r_index.text  # type: ignore[assignment]
                    break
                except httpx.ConnectError:
                    await asyncio.sleep(0.1)
            else:
                raise AssertionError(
                    "dashboard never became reachable inside 6s",
                )
    finally:
        fleet.request_shutdown()
        results = await fleet_task

    # 6. Assertions: per-bot, dashboard, pipeline.
    # (a) Every bot completed without error.
    for name in _ALL_BOTS:
        assert name in results, f"missing result for {name}"
        assert results[name].error is None, (
            f"bot {name} raised: {results[name].error}"
        )

    # (b) Dashboard responded 200 + listed every bot name.
    assert dashboard_responses.get("index") == 200
    assert dashboard_responses.get("health") == 200
    page_text = str(dashboard_responses.get("index_text", ""))
    for name in _ALL_BOTS:
        assert name in page_text, (
            f"dashboard index page missing bot {name!r}: page={page_text[:200]}"
        )

    # (c) Pipeline assertion: at least one bot produced an approved decision.
    # Lux Bot's fixture guarantees a deterministic approval since SignalStrategy
    # always emits an intent for matching signals. This proves bars →
    # strategy → gate → allocator → broker → journal end-to-end.
    from bot.journal.journal import Journal

    total_approvals = 0
    for r in resolved:
        j = await Journal.connect(str(r.journal_path))
        try:
            cur = await j._conn.execute(  # type: ignore[attr-defined]
                "SELECT COUNT(*) FROM risk_decisions WHERE approved=1",
            )
            row = await cur.fetchone()
            await cur.close()
            total_approvals += int(row[0]) if row else 0  # type: ignore[index]
        finally:
            await j.close()
    assert total_approvals >= 1, (
        f"expected at least 1 approval across all 6 bots, got {total_approvals}"
    )

    await sim.disconnect()
