"""BotRegistry — signal_strategy entry + lux_bot.yml spec resolution. T6.

The registry resolves `strategy_id: signal_strategy` into a SignalStrategy
whose SignalSource is chosen by env var:
  - LUX_BOT_FIXTURE_PATH set → FixtureSignalSource reading that JSON file
  - otherwise → DiscordSignalSource (requires DISCORD_BOT_TOKEN)

Tests cover the fixture path (env-driven, no Discord token required) and
verify the YAML spec under `config/bots/lux_bot.yml` parses + resolves.
The Discord branch is not exercised here (T4 covers the source itself);
test_discord_branch_requires_token sanity-checks the env var error path.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.spec import BotSpec, load_bot_specs
from bot.signals.source import SignalEvent
from bot.strategy.signal_strategy import SignalStrategy

REPO_ROOT = Path(__file__).resolve().parents[3]
LUX_YAML = REPO_ROOT / "config" / "bots" / "lux_bot.yml"


def _broker() -> Any:
    return SimExecutionClient()


def _signal_spec(
    *,
    strategy_params: dict[str, Any] | None = None,
    name: str = "lux",
) -> BotSpec:
    return BotSpec(
        name=name,
        enabled=True,
        symbol="MNQH26",
        strategy_id="signal_strategy",
        strategy_params=strategy_params or {
            "max_signals_per_bar": 1,
        },
        risk_policy="efa_standard",
        risk_params={"mll_amount": 2_000},
        schedule_type="always",
        schedule_params={},
        journal_path=Path(f"state/journal_{name}.db"),
    )


def test_signal_strategy_registered_by_default() -> None:
    """The signal_strategy id is a registry builtin alongside orb_5m."""
    reg = BotRegistry()
    # Registry exposes strategies via private dict; the public assertion is
    # that build() resolves the id without KeyError.
    assert "signal_strategy" in reg._strategies  # type: ignore[attr-defined]


def test_fixture_mode_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LUX_BOT_FIXTURE_PATH set → FixtureSignalSource wired in."""
    fixture = tmp_path / "signals.json"
    fixture.write_text(json.dumps([
        {
            "received_at": "2026-05-24T14:30:00+00:00",
            "symbol": "MNQ", "side": "BUY", "qty": 1,
            "limit_price": 20_100.0, "stop_loss": 20_070.0,
            "take_profit": 20_160.0,
            "raw_text": "BUY MNQ @20100 SL=20070 TP=20160",
            "source_id": "fix-1",
        },
    ]))
    monkeypatch.setenv("LUX_BOT_FIXTURE_PATH", str(fixture))
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    reg = BotRegistry()
    resolved = reg.build(_signal_spec(), broker=_broker())
    assert isinstance(resolved.strategy, SignalStrategy)


def test_discord_branch_requires_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No fixture + no DISCORD_BOT_TOKEN → KeyError (loud, not silent)."""
    monkeypatch.delenv("LUX_BOT_FIXTURE_PATH", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    reg = BotRegistry()
    with pytest.raises(
        (KeyError, RuntimeError), match=r"DISCORD_BOT_TOKEN|LUX_BOT_FIXTURE",
    ):
        reg.build(_signal_spec(), broker=_broker())


def test_discord_branch_with_token_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With DISCORD_BOT_TOKEN set + discord_channel_ids in params, build a
    DiscordSignalSource-backed strategy. The discord.py Client is constructed
    eagerly; we don't connect (no .start() called).
    """
    monkeypatch.delenv("LUX_BOT_FIXTURE_PATH", raising=False)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")

    reg = BotRegistry()
    spec = _signal_spec(strategy_params={
        "max_signals_per_bar": 1,
        "discord_channel_ids": [1001, 1002],
        "default_symbol": "MNQH26",
    })
    resolved = reg.build(spec, broker=_broker())
    assert isinstance(resolved.strategy, SignalStrategy)


def test_lux_bot_yaml_loads(tmp_path: Path) -> None:
    """The shipped lux_bot.yml parses cleanly via load_bot_specs.

    Copy into a tmp dir so we don't depend on which other yml files
    exist in config/bots/ at runtime.
    """
    target_dir = tmp_path / "bots"
    target_dir.mkdir()
    target = target_dir / "lux_bot.yml"
    target.write_text(LUX_YAML.read_text(encoding="utf-8"), encoding="utf-8")

    specs = load_bot_specs(target_dir)
    assert len(specs) == 1
    spec = specs[0]
    assert spec.name == "lux_bot"
    assert spec.enabled is False  # disabled by default
    assert spec.strategy_id == "signal_strategy"
    assert spec.schedule_type == "always"
    assert spec.risk_policy == "efa_standard"


def test_fixture_signals_drain_through_pump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke: events in the fixture JSON reach SignalStrategy's deque.

    Builds the resolved strategy, starts the pump, awaits one tick of the
    event loop, then inspects pending_count(). Two events in → two queued.
    """
    import asyncio

    fixture = tmp_path / "signals.json"
    events = [
        {
            "received_at": "2026-05-24T14:30:00+00:00",
            "symbol": "MNQ", "side": "BUY", "qty": 1,
            "limit_price": 20_100.0, "stop_loss": 20_070.0,
            "take_profit": 20_160.0,
            "raw_text": "BUY MNQ @20100 SL=20070 TP=20160",
            "source_id": f"fix-{i}",
        }
        for i in range(2)
    ]
    fixture.write_text(json.dumps(events))
    monkeypatch.setenv("LUX_BOT_FIXTURE_PATH", str(fixture))
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    reg = BotRegistry()
    resolved = reg.build(_signal_spec(), broker=_broker())
    strat = resolved.strategy
    assert isinstance(strat, SignalStrategy)

    async def drive():
        strat.start()
        # Let the pump consume the fixture (yields immediately, no delay).
        for _ in range(10):
            await asyncio.sleep(0)
            if strat.pending_count() >= 2:
                break
        await strat.stop()
        return strat.pending_count()

    count = asyncio.run(drive())
    assert count == 2


def test_signal_event_dict_roundtrip_fields() -> None:
    """Sanity: the fixture JSON shape matches SignalEvent's __init__ signature."""
    raw = {
        "received_at": "2026-05-24T14:30:00+00:00",
        "symbol": "MNQ", "side": "BUY", "qty": 1,
        "limit_price": 20_100.0, "stop_loss": 20_070.0,
        "take_profit": 20_160.0,
        "raw_text": "BUY MNQ @20100 SL=20070 TP=20160",
        "source_id": "fix-1",
    }
    ev = SignalEvent(
        received_at=datetime.fromisoformat(raw["received_at"]),  # type: ignore[arg-type]
        symbol=raw["symbol"],  # type: ignore[arg-type]
        side=raw["side"],  # type: ignore[arg-type]
        qty=raw["qty"],  # type: ignore[arg-type]
        limit_price=raw["limit_price"],  # type: ignore[arg-type]
        stop_loss=raw["stop_loss"],  # type: ignore[arg-type]
        take_profit=raw["take_profit"],  # type: ignore[arg-type]
        raw_text=raw["raw_text"],  # type: ignore[arg-type]
        source_id=raw["source_id"],  # type: ignore[arg-type]
    )
    assert ev.symbol == "MNQ"
    assert ev.received_at.tzinfo == UTC
