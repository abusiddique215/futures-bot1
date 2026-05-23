"""BacktestEngine end-to-end (Bar loop wires Strategy + RiskGate + Sim)."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from bot.backtest.sim_client import SimExecutionClient
from bot.risk.gate import TopstepRiskGate
from bot.types import AccountState, Bar, Bracket, OrderIntent

# ---- Test helpers ---------------------------------------------------------

class _MockTelemetry:
    def alert(self, kind: str, **kw: object) -> None:
        pass


class _MockNewsCal:
    def in_window(self, now: datetime) -> bool:
        return False

    def max_position_during_window(self) -> int:
        return 1


def _make_gate(sim: SimExecutionClient) -> TopstepRiskGate:
    """Construct a TopstepRiskGate wired to a sim client for backtest."""
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    from bot.risk.config import RiskConfig
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    return TopstepRiskGate(
        policy=policy,
        news_calendar=_MockNewsCal(),
        execution_client=sim,
        telemetry=_MockTelemetry(),
        config=cfg,
    )


def _bars(closes: list[float], symbol: str = "MNQ",
          start: datetime | None = None) -> list[Bar]:
    """Generate a list of Bars with given closes; OHLC all = close."""
    start = start or datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    return [
        Bar(symbol=symbol, open=c, high=c, low=c, close=c,
            volume=100, timestamp=start + timedelta(minutes=i),
            interval="1m")
        for i, c in enumerate(closes)
    ]


class _OneShotStrategy:
    """Emits a single open at bar 0, close at bar 5."""

    def __init__(self, symbol: str = "MNQ") -> None:
        self._symbol = symbol
        self._bars_seen = 0

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        idx = self._bars_seen
        self._bars_seen += 1
        if idx == 0:
            return [OrderIntent(
                symbol=self._symbol, side="BUY", quantity=1,
                order_type="MARKET", client_order_id="open-1",
                timestamp=bar.timestamp,
                bracket=Bracket(stop_loss_ticks=40, take_profit_ticks=80),
            )]
        if idx == 5:
            return [OrderIntent(
                symbol=self._symbol, side="SELL", quantity=1,
                order_type="MARKET", client_order_id="close-1",
                timestamp=bar.timestamp,
            )]
        return []


# ---- Tests ----------------------------------------------------------------

def test_engine_with_placeholder_strategy_no_fills_no_pnl() -> None:
    from bot.backtest.engine import BacktestEngine
    from bot.backtest.sim_client import SimExecutionClient
    from bot.backtest.strategy import PlaceholderStrategy
    from bot.backtest.tracker import AccountStateTracker

    sim = SimExecutionClient()
    tracker = AccountStateTracker(start_balance=50_000, is_combine=True)
    gate = _make_gate(sim)
    engine = BacktestEngine(
        strategy=PlaceholderStrategy(),
        gate=gate, tracker=tracker, sim=sim, symbol="MNQ",
    )
    log = engine.run(_bars([16_500.0 + i for i in range(10)]))
    assert log.intents_emitted == 0
    assert log.intents_approved == 0
    assert log.intents_denied == []
    assert log.fills == []
    assert log.final_state.equity == 50_000
    assert log.final_state.open_positions == {}


def test_engine_one_shot_round_trip_realizes_correct_pnl() -> None:
    """Open BUY 1 MNQ at bar 0 (close=16500), close SELL 1 at bar 5 (close=16505).
    Realized = (16505 - 16500) pts * 1 contract * $2/pt = $10."""
    from bot.backtest.engine import BacktestEngine
    from bot.backtest.sim_client import SimExecutionClient
    from bot.backtest.tracker import AccountStateTracker

    sim = SimExecutionClient()
    tracker = AccountStateTracker(start_balance=50_000, is_combine=True)
    gate = _make_gate(sim)
    # bar 0 close=16500, bar 5 close=16505
    closes = [16_500.0, 16_501.0, 16_502.0, 16_503.0, 16_504.0, 16_505.0,
              16_506.0, 16_507.0]
    engine = BacktestEngine(
        strategy=_OneShotStrategy(),
        gate=gate, tracker=tracker, sim=sim, symbol="MNQ",
    )
    log = engine.run(_bars(closes))
    assert log.intents_emitted == 2
    assert log.intents_approved == 2
    assert log.intents_denied == []
    assert len(log.fills) == 2
    assert log.fills[0].status == "FILLED"
    assert log.fills[0].avg_fill_price == 16_500.0
    assert log.fills[1].avg_fill_price == 16_505.0
    assert log.final_state.realized_pnl_today == 10.0
    assert log.final_state.open_positions == {}
    # equity = 50_000 + 10 realized + 0 unrealized
    assert log.final_state.equity == 50_010.0


def test_engine_marks_to_market_before_strategy_sees_state() -> None:
    """During the open hold, strategy.on_bar receives state with unrealized P&L
    already updated from the current bar close."""
    from bot.backtest.engine import BacktestEngine
    from bot.backtest.sim_client import SimExecutionClient
    from bot.backtest.tracker import AccountStateTracker

    seen_unrealized: list[float] = []

    class _Recorder:
        def __init__(self) -> None:
            self._i = 0

        def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
            seen_unrealized.append(state.unrealized_pnl)
            i = self._i
            self._i += 1
            if i == 0:
                return [OrderIntent(
                    symbol="MNQ", side="BUY", quantity=1,
                    order_type="MARKET", client_order_id="o-1",
                    timestamp=bar.timestamp,
                    bracket=Bracket(stop_loss_ticks=40, take_profit_ticks=80),
                )]
            return []

    sim = SimExecutionClient()
    tracker = AccountStateTracker(start_balance=50_000, is_combine=True)
    gate = _make_gate(sim)
    closes = [16_500.0, 16_510.0, 16_520.0]
    engine = BacktestEngine(
        strategy=_Recorder(), gate=gate, tracker=tracker, sim=sim, symbol="MNQ",
    )
    log = engine.run(_bars(closes))
    # bar 0 sees no position yet -> 0; bar 1 sees +10 pts * $2 = $20;
    # bar 2 sees +20 pts * $2 = $40.
    assert seen_unrealized == [0.0, 20.0, 40.0]
    assert log.final_state.open_positions == {"MNQ": 1}
