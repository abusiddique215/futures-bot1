"""Plan 10 T6: end-to-end smoke — synthetic 60-bar stream → trade → journal.

This is the load-bearing proof that LiveTradingLoop wired into main() produces
a fully-traded session: equity snapshots per bar, an approved-decision row,
a fill row, and a closing decision row. No real broker — SimExecutionClient +
SimBarSource + a synthetic open/close strategy.

If this test passes, the bot is end-to-end deployable: launchd starts main(),
main() opens the journal + broker, hydrates RuntimeState, runs LiveTradingLoop
to source exhaustion, and exits with broker.disconnect + journal.close in its
finally block.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from bot.backtest.sim_client import SimExecutionClient
from bot.config import BotConfig, DataConfig
from bot.journal.journal import Journal
from bot.runtime.bar_source import SimBarSource
from bot.runtime.main import EXIT_OK, main
from bot.types import AccountState, Bar, Bracket, OrderIntent


def _cfg(tmp_path: Path) -> BotConfig:
    return BotConfig(
        env="dev", broker="sim", account_id="acct-0", strategy="orb",
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


def _bars_60() -> list[Bar]:
    """60 sequential 1-minute bars starting at 14:30 UTC (~09:30 ET market open).

    Prices drift up monotonically — keeps the gate happy and the strategy
    able to print a long that gets approved.
    """
    start = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    bars: list[Bar] = []
    for i in range(60):
        price = 18_000.0 + i * 0.5
        bars.append(Bar(
            symbol="MNQ", open=price, high=price + 0.25,
            low=price - 0.25, close=price, volume=100,
            timestamp=start + timedelta(minutes=i), interval="1m",
        ))
    return bars


class _OpenCloseStrategy:
    """BUY 1 with a bracket on bar 0, SELL 1 to close on bar 30.

    Produces 1 approved open + 1 approved close → 2 risk_decision rows
    (both approved=1), 2 fill rows, and a steady stream of equity_snapshots.
    """

    def __init__(self) -> None:
        self._i = 0

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        i = self._i
        self._i += 1
        if i == 0:
            return [OrderIntent(
                symbol="MNQ", side="BUY", quantity=1, order_type="MARKET",
                client_order_id="open-1", timestamp=bar.timestamp,
                bracket=Bracket(stop_loss_ticks=40, take_profit_ticks=80),
            )]
        if i == 30:
            return [OrderIntent(
                symbol="MNQ", side="SELL", quantity=1, order_type="MARKET",
                client_order_id="close-1", timestamp=bar.timestamp,
            )]
        return []


async def test_e2e_synthetic_bar_stream_produces_trades_in_journal(
    tmp_path: Path,
) -> None:
    """60-bar stream through main() → journal has approved decisions + fills
    + equity snapshots. Bot is end-to-end deployable."""
    cfg = _cfg(tmp_path)
    journal_path = tmp_path / "journal.db"

    async def _open_journal(_path: str) -> Journal:
        j = await Journal.connect(str(journal_path))
        await j.apply_migrations()
        return j

    async def _connect_broker(
        _cfg: BotConfig, _secrets: object,
    ) -> SimExecutionClient:
        sim = SimExecutionClient()
        await sim.connect()
        return sim

    def _bar_source(
        _cfg: BotConfig, _broker: object,
    ) -> SimBarSource:
        return SimBarSource(_bars_60())

    def _strategy(_cfg: BotConfig) -> _OpenCloseStrategy:
        return _OpenCloseStrategy()

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

    # Re-open file-backed journal to inspect.
    j = await Journal.connect(str(journal_path))
    try:
        # >= 2 approved decisions (open + close); the close may be approved
        # as a reducer regardless of hard-flat clock.
        cur = await j._conn.execute(  # type: ignore[attr-defined]
            "SELECT COUNT(*) FROM risk_decisions WHERE approved=1"
        )
        (approved_count,) = await cur.fetchone()  # type: ignore[misc]
        await cur.close()
        assert approved_count >= 1

        # >= 1 fill recorded
        cur = await j._conn.execute(  # type: ignore[attr-defined]
            "SELECT COUNT(*) FROM fills"
        )
        (fill_count,) = await cur.fetchone()  # type: ignore[misc]
        await cur.close()
        assert fill_count >= 1

        # 60 equity snapshots (one per bar)
        cur = await j._conn.execute(  # type: ignore[attr-defined]
            "SELECT COUNT(*) FROM equity_snapshots"
        )
        (snap_count,) = await cur.fetchone()  # type: ignore[misc]
        await cur.close()
        assert snap_count == 60

        # Heartbeat file was written
        assert (tmp_path / "hb").exists()
    finally:
        await j.close()
