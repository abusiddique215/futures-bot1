"""Lux Bot end-to-end — FixtureSignalSource → FleetRuntime → SimClient → Journal.

Drives a synthetic 10-minute bar stream + a FixtureSignalSource carrying
3 pre-parsed events through the full live loop. Asserts:

  1. 3 BUY signals → 3 approved orders → 3 fills in the journal.
  2. A 4th signal claiming qty=100 → ONE OrderDenied row with rule=MAX_POSITION
     in risk_decisions. The signal flows through the gate without bypass.

Plan 21 added a `Strategy.setup()` lifecycle hook on FleetRuntime — for
SignalStrategy that hook calls self.start() to spawn the Discord/fixture
pump task. The previous version of this test called start() explicitly
because FleetRuntime didn't know to do so; that work is now wired into
the runtime itself, so the test no longer needs the explicit start().
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bot.backtest.sim_client import SimExecutionClient
from bot.observability.bus import NoopTelemetryBus
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.runtime import FleetRuntime
from bot.runtime.fleet.spec import BotSpec
from bot.signals.fixture_source import FixtureSignalSource
from bot.signals.source import SignalEvent
from bot.strategy.signal_strategy import SignalStrategy
from bot.types import Bar


def _bar(symbol: str, ts: datetime, price: float = 20_100.0) -> Bar:
    return Bar(
        symbol=symbol, open=price, high=price, low=price, close=price,
        volume=100, timestamp=ts, interval="10m",
    )


def _bars(symbol: str, n: int) -> list[Bar]:
    """Build N bars at 10-minute intervals from 14:00 UTC 2026-05-24."""
    start = datetime(2026, 5, 24, 14, 0, tzinfo=UTC)
    return [_bar(symbol, start + timedelta(minutes=10 * i)) for i in range(n)]


class _StaticBarSource:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def subscribe(self):
        for b in self._bars:
            yield b


def _signal(
    *, source_id: str, qty: int = 1,
    side: str = "BUY", limit_price: float = 20_100.0,
) -> SignalEvent:
    return SignalEvent(
        received_at=datetime(2026, 5, 24, 13, 59, tzinfo=UTC),
        symbol="MNQ", side=side,  # type: ignore[arg-type]
        qty=qty, limit_price=limit_price,
        stop_loss=20_070.0, take_profit=20_160.0,
        raw_text=f"{side} MNQ @{limit_price} SL=20070 TP=20160",
        source_id=source_id,
    )


def _build_lux(
    *, tmp_path: Path, broker: Any, events: list[SignalEvent],
) -> tuple[Any, SignalStrategy]:
    """Build a resolved lux bot wired to a FixtureSignalSource(events).

    Bypasses the registry's env-var resolution by registering a custom
    factory that returns a SignalStrategy with the supplied source.
    """
    reg = BotRegistry()
    source = FixtureSignalSource(events)
    # Resolve via a custom factory so we can inject the in-memory source.
    # The bot symbol injection (_bot_symbol) still happens via build().
    def _factory(params: dict[str, Any]) -> SignalStrategy:
        symbol = str(params["_bot_symbol"])
        return SignalStrategy(
            symbol=symbol, source=source,
            max_signals_per_bar=int(params.get("max_signals_per_bar", 1)),
        )
    reg.register_strategy("signal_strategy", _factory)

    spec = BotSpec(
        name="lux_e2e",
        enabled=True,
        symbol="MNQH26",
        strategy_id="signal_strategy",
        strategy_params={"max_signals_per_bar": 1},
        risk_policy="efa_standard",
        risk_params={"mll_amount": 2_000},
        schedule_type="always",
        schedule_params={},
        journal_path=tmp_path / "lux_e2e.db",
    )
    resolved = reg.build(spec, broker=broker)
    assert isinstance(resolved.strategy, SignalStrategy)
    return resolved, resolved.strategy


async def test_three_signals_become_three_fills(tmp_path: Path) -> None:
    """3 BUY signals → 3 approved → 3 fills + 3 risk_decisions(approved=1)."""
    sim = SimExecutionClient()
    await sim.connect()

    events = [_signal(source_id=f"sig-{i}") for i in range(3)]
    resolved, strat = _build_lux(tmp_path=tmp_path, broker=sim, events=events)

    # Plan 21: FleetRuntime calls Strategy.setup() before LiveTradingLoop.run(),
    # which (for SignalStrategy) spawns the pump task that drains the source
    # into the deque. The test used to call strat.start() + wait for
    # pending_count manually — now the runtime owns that wiring.
    fleet = FleetRuntime(
        bots=[resolved], broker=sim,
        bar_source_factory=lambda spec: _StaticBarSource(_bars("MNQ", 5)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    results = await fleet.run()
    await strat.stop()

    assert results["lux_e2e"].error is None
    assert results["lux_e2e"].bars_processed == 5

    # Inspect the journal directly.
    from bot.journal.journal import Journal
    j = await Journal.connect(str(resolved.journal_path))
    try:
        cur = await j._conn.execute(  # type: ignore[attr-defined]
            "SELECT COUNT(*) FROM risk_decisions WHERE approved=1",
        )
        (approved,) = await cur.fetchone()  # type: ignore[misc]
        await cur.close()

        cur = await j._conn.execute(  # type: ignore[attr-defined]
            "SELECT COUNT(*) FROM fills",
        )
        (fills,) = await cur.fetchone()  # type: ignore[misc]
        await cur.close()
    finally:
        await j.close()

    assert approved == 3, f"expected 3 approved decisions, got {approved}"
    assert fills == 3, f"expected 3 fills, got {fills}"


async def test_oversize_signal_denied_by_risk_gate(tmp_path: Path) -> None:
    """Safety property: signal claiming qty=100 → MAX_POSITION deny.

    The signal MUST flow through TopstepRiskGate. The Combine policy caps
    NQ/MNQ at 5 minis (max_mini=5 in risk_params). A signal asking for 100
    units is denied — never reaches the broker.
    """
    sim = SimExecutionClient()
    await sim.connect()

    # Tight stop so DLL ($1000) doesn't trip before MAX_POSITION.
    # MNQ tick_value=$0.50. 1-tick stop * 100 qty = $50 < DLL.
    # Stop distance: 20100.0 - 20099.75 = 1 tick.
    events = [_signal(
        source_id="oversize", qty=100, limit_price=20_100.0,
    )]
    # Replace the broad-stop event with a tight-stop one (override TP/SL).
    events[0] = SignalEvent(
        received_at=events[0].received_at,
        symbol=events[0].symbol, side=events[0].side, qty=events[0].qty,
        limit_price=events[0].limit_price,
        stop_loss=20_099.75,    # 1 tick distance
        take_profit=20_100.25,  # 1 tick distance
        raw_text=events[0].raw_text,
        source_id=events[0].source_id,
    )
    resolved, strat = _build_lux(tmp_path=tmp_path, broker=sim, events=events)

    # FleetRuntime.setup() spawns the pump; no manual start() needed.
    fleet = FleetRuntime(
        bots=[resolved], broker=sim,
        bar_source_factory=lambda spec: _StaticBarSource(_bars("MNQ", 3)),
        telemetry=NoopTelemetryBus(),
        heartbeat_path=tmp_path / "hb",
    )
    results = await fleet.run()
    await strat.stop()
    assert results["lux_e2e"].error is None

    from bot.journal.journal import Journal
    j = await Journal.connect(str(resolved.journal_path))
    try:
        # Exactly one denial, rule = MAX_POSITION
        cur = await j._conn.execute(  # type: ignore[attr-defined]
            "SELECT COUNT(*), MAX(rule) FROM risk_decisions WHERE approved=0",
        )
        row = await cur.fetchone()
        await cur.close()
        denied_count, rule = row  # type: ignore[misc]

        # Zero fills — the oversize order never reached the broker.
        cur = await j._conn.execute(  # type: ignore[attr-defined]
            "SELECT COUNT(*) FROM fills",
        )
        (fills,) = await cur.fetchone()  # type: ignore[misc]
        await cur.close()
    finally:
        await j.close()

    assert denied_count == 1, f"expected 1 denial, got {denied_count}"
    assert rule == "MAX_POSITION", f"expected MAX_POSITION rule, got {rule!r}"
    assert fills == 0, f"oversize signal must not fill, got {fills} fills"
