"""Plan 10 T5: main()'s _default_event_loop is now a real LiveTradingLoop.

Tests use injection seams (load_config_fn, open_journal_fn, connect_broker_fn,
bar_source_fn) so no subprocess / real broker / real disk is touched. The
existing Plan 9 smoke test (subprocess --check) is the integration counterpart
and lives in test_runtime_smoke.py.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from bot.config import BotConfig, DataConfig
from bot.journal.journal import Journal
from bot.runtime.bar_source import SimBarSource
from bot.runtime.main import (
    EXIT_OK,
    _default_event_loop,
    _resolve_bar_source,
    _resolve_strategy,
    main,
)
from bot.types import AccountState, Bar, OrderIntent


def _cfg(tmp_path: Path) -> BotConfig:
    return BotConfig(
        env="dev",
        broker="sim",
        account_id="acct-0",
        strategy="orb",
        strategy_profile=Path("config/profiles/surge.yml"),
        risk_policy="combine_50k",
        data=DataConfig(
            historical_root=Path("data/parquet"),
            historical_vendor="firstratedata",
            live_source="ib",
            symbol_primary="MNQ",
        ),
        news_calendar=Path("config/news_calendar.yml"),
        flat_by_warning_ct=time(14, 0),
        flat_by_force_ct=time(15, 10),
        heartbeat_path=tmp_path / "hb",
    )


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    return [
        Bar(
            symbol="MNQ", open=c, high=c, low=c, close=c, volume=100,
            timestamp=start + timedelta(minutes=i), interval="1m",
        )
        for i, c in enumerate(closes)
    ]


class _BuyOnceStrategy:
    def __init__(self) -> None:
        self._i = 0

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        from bot.types import Bracket
        i = self._i
        self._i += 1
        if i == 0:
            return [OrderIntent(
                symbol="MNQ", side="BUY", quantity=1, order_type="MARKET",
                client_order_id="open-1", timestamp=bar.timestamp,
                bracket=Bracket(stop_loss_ticks=40, take_profit_ticks=80),
            )]
        return []


# ---- Config field --------------------------------------------------------

def test_bot_config_has_heartbeat_path_default() -> None:
    """BotConfig grew a heartbeat_path field with a sane default."""
    cfg = BotConfig(
        env="dev", broker="sim", account_id="x", strategy="orb",
        strategy_profile=Path("p.yml"), risk_policy="combine_50k",
        data=DataConfig(
            historical_root=Path("data"), historical_vendor="firstratedata",
            live_source="ib",
        ),
        news_calendar=Path("nc.yml"),
    )
    assert cfg.heartbeat_path == Path("state/heartbeat")


# ---- Factory helpers -----------------------------------------------------

def test_resolve_strategy_returns_placeholder_for_now(tmp_path: Path) -> None:
    """v1 wiring uses PlaceholderStrategy; real ORB factory is Plan 11."""
    cfg = _cfg(tmp_path)
    strat = _resolve_strategy(cfg)
    # PlaceholderStrategy emits zero intents
    out = list(strat.on_bar(
        Bar(symbol="MNQ", open=1, high=1, low=1, close=1, volume=1,
            timestamp=datetime(2026, 5, 22, tzinfo=UTC), interval="1m"),
        AccountState(
            equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
            open_positions={}, pending_intent_count=0,
            high_water_equity=50_000.0, is_combine=True,
            timestamp=datetime(2026, 5, 22, tzinfo=UTC),
        ),
    ))
    assert out == []


async def test_resolve_bar_source_sim_broker_returns_empty(tmp_path: Path) -> None:
    """env=dev + broker=sim → empty SimBarSource so --check / smoke exits."""
    cfg = _cfg(tmp_path)
    src = _resolve_bar_source(cfg, broker=MagicMock())
    assert isinstance(src, SimBarSource)
    received: list[Bar] = []
    async for bar in src.subscribe():
        received.append(bar)
    assert received == []


# ---- _default_event_loop wiring (with injected bar source) ---------------

async def test_default_event_loop_runs_to_completion(tmp_path: Path) -> None:
    """_default_event_loop constructs a LiveTradingLoop and runs to source
    exhaustion. With an empty source the loop returns immediately."""
    from bot.backtest.sim_client import SimExecutionClient
    from bot.runtime.hydrate import RuntimeState
    from bot.runtime.secrets import SecretsDict

    cfg = _cfg(tmp_path)
    journal = await Journal.connect(":memory:")
    await journal.apply_migrations()
    sim = SimExecutionClient()
    await sim.connect()
    runtime = RuntimeState(
        cfg=cfg,
        secrets=SecretsDict(),
        broker=sim, journal=journal,
        positions={}, equity=50_000.0,
        realized_pnl_today=0.0, high_water_equity=50_000.0,
    )
    # Should NOT raise. Empty SimBarSource → loop exits immediately.
    await _default_event_loop(runtime)
    await journal.close()


# ---- main() runs the full loop (with injected bar source) ----------------

async def test_main_runs_loop_with_synthetic_bars(tmp_path: Path) -> None:
    """main() invoked without --check + a custom bar_source_fn that yields 3
    bars: 1 approved order recorded in the journal session."""
    from bot.backtest.sim_client import SimExecutionClient
    from bot.runtime.main import _Bus

    cfg = _cfg(tmp_path)
    journal_holder: dict[str, Journal] = {}

    async def _open_journal(path: str) -> Journal:
        j = await Journal.connect(":memory:")
        await j.apply_migrations()
        journal_holder["j"] = j
        return j

    async def _connect_broker(_cfg: BotConfig, _secrets: object) -> SimExecutionClient:
        sim = SimExecutionClient()
        await sim.connect()
        return sim

    def _bar_source(_cfg: BotConfig, _broker: object) -> SimBarSource:
        return SimBarSource(_bars([18_000.0, 18_001.0, 18_002.0]))

    def _strategy(_cfg: BotConfig) -> _BuyOnceStrategy:
        return _BuyOnceStrategy()

    bus: _Bus = MagicMock(spec=_Bus)

    exit_code = await main(
        config_path=Path("config/bot.example.yml"),
        check_only=False,
        load_config_fn=lambda p: cfg,
        open_journal_fn=_open_journal,
        connect_broker_fn=_connect_broker,
        bar_source_fn=_bar_source,
        strategy_fn=_strategy,
        hostname_fn=lambda: "any-host",
        bus=bus,
    )
    assert exit_code == EXIT_OK

    # The journal got closed by main()'s finally — re-open against the
    # captured handle. We stashed a ref above; check rows BEFORE close was
    # called. Since main() closes the journal in its finally, we can't
    # query it now. So instead inspect via the in-memory aiosqlite handle's
    # private state through a fresh query during the run — done via a
    # subscriber pattern. Simpler: use a journal that survives close (use
    # a tmp file).
    # → swap to file-backed journal for assertions:
    # (kept the in-memory variant above for the smoke; the assertion test
    # uses a file-backed journal in the next test.)
    _ = journal_holder  # silence unused
    _ = bus


async def test_main_journal_records_orders_when_loop_trades(tmp_path: Path) -> None:
    """Same as above but with a file-backed journal so we can re-open and
    assert order rows after main() returns."""
    from bot.backtest.sim_client import SimExecutionClient

    cfg = _cfg(tmp_path)
    journal_path = tmp_path / "journal.db"

    async def _open_journal(_path: str) -> Journal:
        j = await Journal.connect(str(journal_path))
        await j.apply_migrations()
        return j

    async def _connect_broker(_cfg: BotConfig, _secrets: object) -> SimExecutionClient:
        sim = SimExecutionClient()
        await sim.connect()
        return sim

    def _bar_source(_cfg: BotConfig, _broker: object) -> SimBarSource:
        return SimBarSource(_bars([18_000.0, 18_001.0, 18_002.0]))

    def _strategy(_cfg: BotConfig) -> _BuyOnceStrategy:
        return _BuyOnceStrategy()

    exit_code = await main(
        config_path=Path("config/bot.example.yml"),
        check_only=False,
        load_config_fn=lambda p: cfg,
        open_journal_fn=_open_journal,
        connect_broker_fn=_connect_broker,
        bar_source_fn=_bar_source,
        strategy_fn=_strategy,
        hostname_fn=lambda: "any-host",
    )
    assert exit_code == EXIT_OK

    # Re-open the file-backed journal to inspect.
    j = await Journal.connect(str(journal_path))
    cur = await j._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM risk_decisions WHERE approved=1"
    )
    (approved_count,) = await cur.fetchone()  # type: ignore[misc]
    await cur.close()
    assert approved_count == 1
    cur = await j._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM fills"
    )
    (fill_count,) = await cur.fetchone()  # type: ignore[misc]
    await cur.close()
    assert fill_count == 1
    await j.close()


async def test_main_existing_event_loop_fn_override_still_works(tmp_path: Path) -> None:
    """A test passing event_loop_fn=AsyncMock() still overrides the wiring
    so Plan 9 main tests don't have to migrate."""
    cfg = _cfg(tmp_path)
    journal = MagicMock()
    journal.apply_migrations = AsyncMock(return_value=None)
    journal.close = AsyncMock(return_value=None)
    journal.get_open_positions = AsyncMock(return_value=[])
    journal.get_open_orders = AsyncMock(return_value=[])
    journal.get_last_equity_snapshot = AsyncMock(return_value=None)

    broker = MagicMock()
    broker.connect = AsyncMock(return_value=None)
    broker.disconnect = AsyncMock(return_value=None)
    broker.get_positions = AsyncMock(return_value=[])
    broker.get_open_orders = AsyncMock(return_value=[])
    broker.get_account = AsyncMock(return_value=AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True,
        timestamp=datetime(2026, 5, 22, tzinfo=UTC),
    ))

    event_loop = AsyncMock(return_value=None)
    exit_code = await main(
        config_path=Path("config/bot.example.yml"),
        check_only=False,
        load_config_fn=lambda p: cfg,
        open_journal_fn=AsyncMock(return_value=journal),
        connect_broker_fn=AsyncMock(return_value=broker),
        event_loop_fn=event_loop,
        hostname_fn=lambda: "any-host",
    )
    assert exit_code == EXIT_OK
    event_loop.assert_awaited_once()
