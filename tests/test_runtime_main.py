"""Plan 9 T7: bot.runtime.main — 8-step startup orchestrator.

Contract (spec 07 §3.6):
  1. cfg = load_config(args.config)
  2. secrets = load_secrets(cfg)                    — exit 3 on missing
  3. assert_host_allowed(cfg)                       — exit 4 on mismatch
  4. journal = await open_journal(cfg.journal_path) — :memory: in dev/backtest
  5. broker  = await connect_broker(cfg, secrets)   — sim/ib_paper/topstepx
  6. bs = await snapshot_broker(broker); js = await snapshot_journal(journal)
  7. rr = reconcile(bs, js); if not rr.ok and cfg.halt_on_journal_desync:
       log CRITICAL + exit 5
  8. runtime = hydrate_runtime(...); await run_event_loop(runtime)

The integration test uses mocks for EVERY external dep. The only function
under test is `main(args, ...)`. Step 8's `run_event_loop` is also mocked
so the orchestrator returns once setup is done — letting --check share
the same code path with `event_loop=run_event_loop` swapped for a no-op.
"""
from __future__ import annotations

from datetime import UTC, datetime, time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config import BotConfig, DataConfig
from bot.runtime.main import (
    EXIT_HOST_DENIED,
    EXIT_OK,
    EXIT_RECONCILE_FAIL,
    EXIT_SECRETS_MISSING,
    main,
)


def _cfg(broker: str = "sim", env: str = "dev", halt: bool = True) -> BotConfig:
    return BotConfig(
        env=env,  # type: ignore[arg-type]
        broker=broker,  # type: ignore[arg-type]
        account_id="acct-0",
        strategy="orb",
        strategy_profile=Path("config/profiles/surge.yml"),
        risk_policy="combine_50k",
        data=DataConfig(
            historical_root=Path("data/parquet"),
            historical_vendor="firstratedata",
            live_source="ib",
        ),
        news_calendar=Path("config/news_calendar.yml"),
        flat_by_warning_ct=time(14, 0),
        flat_by_force_ct=time(15, 10),
        halt_on_journal_desync=halt,
    )


def _journal_mock() -> MagicMock:
    j = MagicMock()
    j.apply_migrations = AsyncMock(return_value=None)
    j.close = AsyncMock(return_value=None)
    j.get_open_positions = AsyncMock(return_value=[])
    j.get_open_orders = AsyncMock(return_value=[])
    j.get_last_equity_snapshot = AsyncMock(return_value=None)
    j.record_session_start = AsyncMock(return_value=None)
    return j


def _broker_mock() -> MagicMock:
    from bot.types import AccountState
    b = MagicMock()
    b.connect = AsyncMock(return_value=None)
    b.disconnect = AsyncMock(return_value=None)
    b.get_positions = AsyncMock(return_value=[])
    b.get_open_orders = AsyncMock(return_value=[])
    b.get_account = AsyncMock(return_value=AccountState(
        equity=50_000.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=50_000.0,
        is_combine=True,
        timestamp=datetime(2026, 5, 23, 14, 0, tzinfo=UTC),
    ))
    return b


async def test_happy_path_returns_exit_ok() -> None:
    """8 steps complete, event loop runs once and exits cleanly."""
    cfg = _cfg()
    journal = _journal_mock()
    broker = _broker_mock()
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
    broker.disconnect.assert_awaited()
    journal.close.assert_awaited()


async def test_check_mode_skips_event_loop() -> None:
    """--check exits after reconcile / hydrate, never enters the event loop."""
    cfg = _cfg()
    journal = _journal_mock()
    broker = _broker_mock()
    event_loop = AsyncMock(return_value=None)

    exit_code = await main(
        config_path=Path("config/bot.example.yml"),
        check_only=True,
        load_config_fn=lambda p: cfg,
        open_journal_fn=AsyncMock(return_value=journal),
        connect_broker_fn=AsyncMock(return_value=broker),
        event_loop_fn=event_loop,
        hostname_fn=lambda: "any-host",
    )
    assert exit_code == EXIT_OK
    event_loop.assert_not_called()
    broker.disconnect.assert_awaited()
    journal.close.assert_awaited()


async def test_missing_secret_returns_exit_3(monkeypatch: pytest.MonkeyPatch) -> None:
    """env vars absent for topstepx broker → exit code 3."""
    monkeypatch.delenv("TOPSTEPX_USERNAME", raising=False)
    monkeypatch.delenv("TOPSTEPX_API_KEY", raising=False)
    monkeypatch.delenv("TOPSTEPX_ACCOUNT_NAME", raising=False)

    cfg = _cfg(broker="topstepx", env="paper")
    journal = _journal_mock()
    broker = _broker_mock()

    exit_code = await main(
        config_path=Path("config/bot.example.yml"),
        check_only=False,
        load_config_fn=lambda p: cfg,
        open_journal_fn=AsyncMock(return_value=journal),
        connect_broker_fn=AsyncMock(return_value=broker),
        event_loop_fn=AsyncMock(),
        hostname_fn=lambda: "any-host",
    )
    assert exit_code == EXIT_SECRETS_MISSING


async def test_host_denied_returns_exit_4(monkeypatch: pytest.MonkeyPatch) -> None:
    """env=live + bad hostname → exit code 4. Journal NOT opened."""
    # Set required topstepx vars so we get past T2 and hit T3.
    monkeypatch.setenv("TOPSTEPX_USERNAME", "x")
    monkeypatch.setenv("TOPSTEPX_API_KEY", "y")
    monkeypatch.setenv("TOPSTEPX_ACCOUNT_NAME", "z")

    cfg = BotConfig(
        env="live",
        broker="topstepx",
        account_id="acct-0",
        strategy="orb",
        strategy_profile=Path("config/profiles/surge.yml"),
        risk_policy="combine_50k",
        data=DataConfig(
            historical_root=Path("data/parquet"),
            historical_vendor="firstratedata",
            live_source="ib",
        ),
        news_calendar=Path("config/news_calendar.yml"),
        flat_by_warning_ct=time(14, 0),
        flat_by_force_ct=time(15, 10),
        live_hostnames=["mac-mini-01.local"],
    )

    journal = _journal_mock()
    open_journal = AsyncMock(return_value=journal)

    exit_code = await main(
        config_path=Path("config/bot.example.yml"),
        check_only=False,
        load_config_fn=lambda p: cfg,
        open_journal_fn=open_journal,
        connect_broker_fn=AsyncMock(return_value=_broker_mock()),
        event_loop_fn=AsyncMock(),
        hostname_fn=lambda: "vps-trader-99.cloud",
    )
    assert exit_code == EXIT_HOST_DENIED
    open_journal.assert_not_called()


async def test_reconcile_mismatch_with_halt_returns_exit_5() -> None:
    """halt_on_journal_desync=True + dirty reconcile → exit code 5.
    Event loop NOT entered."""
    from bot.types import Position

    cfg = _cfg(halt=True)
    journal = _journal_mock()
    # Journal claims a position broker doesn't have
    journal.get_open_positions = AsyncMock(return_value=[
        Position(
            symbol="MNQ", signed_qty=1, avg_entry_price=18000.0,
            unrealized_pnl=0.0, opened_at=datetime(2026, 5, 23, 14, 0, tzinfo=UTC),
        ),
    ])
    broker = _broker_mock()  # broker returns empty positions
    event_loop = AsyncMock()

    exit_code = await main(
        config_path=Path("config/bot.example.yml"),
        check_only=False,
        load_config_fn=lambda p: cfg,
        open_journal_fn=AsyncMock(return_value=journal),
        connect_broker_fn=AsyncMock(return_value=broker),
        event_loop_fn=event_loop,
        hostname_fn=lambda: "any-host",
    )
    assert exit_code == EXIT_RECONCILE_FAIL
    event_loop.assert_not_called()
    broker.disconnect.assert_awaited()
    journal.close.assert_awaited()


async def test_reconcile_mismatch_without_halt_proceeds() -> None:
    """halt_on_journal_desync=False + dirty reconcile → logs CRITICAL + proceeds."""
    from bot.types import Position

    cfg = _cfg(halt=False)
    journal = _journal_mock()
    journal.get_open_positions = AsyncMock(return_value=[
        Position(
            symbol="MNQ", signed_qty=1, avg_entry_price=18000.0,
            unrealized_pnl=0.0, opened_at=datetime(2026, 5, 23, 14, 0, tzinfo=UTC),
        ),
    ])
    broker = _broker_mock()
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


async def test_main_uses_icloud_check_warning() -> None:
    """When cwd is iCloud-tree, the WARN alert fires but startup proceeds."""
    cfg = _cfg()
    journal = _journal_mock()
    broker = _broker_mock()

    class _CountingBus:
        def __init__(self) -> None:
            self.alerts: list[tuple[str, dict[str, object]]] = []
        def alert(self, kind: str, **kw: object) -> None:
            self.alerts.append((kind, kw))

    bus = _CountingBus()
    exit_code = await main(
        config_path=Path("config/bot.example.yml"),
        check_only=True,
        load_config_fn=lambda p: cfg,
        open_journal_fn=AsyncMock(return_value=journal),
        connect_broker_fn=AsyncMock(return_value=broker),
        event_loop_fn=AsyncMock(),
        hostname_fn=lambda: "any-host",
        bus=bus,
        cwd=Path("/Users/alice/Library/Mobile Documents/CloudDocs/proj"),
    )
    assert exit_code == EXIT_OK
    kinds = [a[0] for a in bus.alerts]
    assert "ICLOUD_TREE_WARNING" in kinds


async def test_broker_disconnect_called_even_on_event_loop_error() -> None:
    """Cleanup must happen on the event-loop-raising path too."""
    cfg = _cfg()
    journal = _journal_mock()
    broker = _broker_mock()
    event_loop = AsyncMock(side_effect=RuntimeError("simulated crash"))

    with pytest.raises(RuntimeError, match="simulated crash"):
        await main(
            config_path=Path("config/bot.example.yml"),
            check_only=False,
            load_config_fn=lambda p: cfg,
            open_journal_fn=AsyncMock(return_value=journal),
            connect_broker_fn=AsyncMock(return_value=broker),
            event_loop_fn=event_loop,
            hostname_fn=lambda: "any-host",
        )
    broker.disconnect.assert_awaited()
    journal.close.assert_awaited()


async def test_main_emits_startup_banner_with_dual_pricing_paths() -> None:
    """Spec patch: dual pricing path ($49+$149 vs $95+$0) surfaced in startup."""
    cfg = _cfg()
    journal = _journal_mock()
    broker = _broker_mock()

    class _Bus:
        def __init__(self) -> None:
            self.alerts: list[tuple[str, dict[str, object]]] = []
        def alert(self, kind: str, **kw: object) -> None:
            self.alerts.append((kind, kw))

    bus = _Bus()
    await main(
        config_path=Path("config/bot.example.yml"),
        check_only=True,
        load_config_fn=lambda p: cfg,
        open_journal_fn=AsyncMock(return_value=journal),
        connect_broker_fn=AsyncMock(return_value=broker),
        event_loop_fn=AsyncMock(),
        hostname_fn=lambda: "any-host",
        bus=bus,
    )
    banner_alerts = [a for a in bus.alerts if a[0] == "STARTUP_BANNER"]
    assert len(banner_alerts) == 1
    payload = banner_alerts[0][1]
    # Dual pricing path should appear somewhere in the banner text
    text = str(payload.get("reason", "")) + " " + " ".join(
        str(v) for v in payload.values() if isinstance(v, str)
    )
    assert "$49" in text or "49" in text
    assert "$95" in text or "95" in text
