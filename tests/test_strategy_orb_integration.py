"""ORB strategy + BacktestEngine end-to-end — the first real backtest.

Synthesises ~120 1-min MNQ bars for a single ET trading day so the surge
profile loaded from disk produces exactly one round-trip with positive PnL.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.backtest.engine import BacktestEngine
from bot.backtest.report import TradeReport
from bot.backtest.rule_replay import RuleReplayReporter
from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.tracker import AccountStateTracker
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.strategy.orb import OpeningRangeBreakoutStrategy
from bot.strategy.profile_loader import load_orb_profile
from bot.types import Bar

_ET = ZoneInfo("America/New_York")


class _NoNewsCal:
    def in_window(self, now: datetime) -> bool:
        return False

    def max_position_during_window(self) -> int:
        return 1


class _NoopTelemetry:
    def alert(self, kind: str, **kw: object) -> None:
        return None


def _et(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_ET).astimezone(UTC)


def _bar(o: float, h: float, lo: float, c: float, ts: datetime) -> Bar:
    return Bar(
        symbol="MNQ", open=o, high=h, low=lo, close=c,
        volume=100, timestamp=ts, interval="1m",
    )


def _make_gate(sim: SimExecutionClient) -> TopstepRiskGate:
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    return TopstepRiskGate(
        policy=policy,
        news_calendar=_NoNewsCal(),
        execution_client=sim,
        telemetry=_NoopTelemetry(),
        config=cfg,
    )


def _synthesize_day() -> list[Bar]:
    """120 bars on 2026-05-22 ET.

    Bars 0-4 (09:30-09:34): tight range [16500, 16510] with TR=10 each.
    Bar 5 (09:35): close=16515 (breakout above) with TR=10 -> ATR=10, stop=40t, tp=80t.
                   tp_price = 16515 + 80*0.25 = 16535.
    Bar 6 (09:36): high=16540 crosses TP, close=16538 -> closing SELL fills at 16538.
    Bars 7-119: quiet drift, no new signals (surge.max_trades_per_day=2 still allows
                more in principle, but bars produce no breakout against the now-stale
                range).
    """
    start = _et(2026, 5, 22, 9, 30)
    bars: list[Bar] = []
    # Range build (5 bars).
    for i in range(5):
        bars.append(_bar(16500, 16510, 16500, 16505, start + timedelta(minutes=i)))
    # Breakout bar.
    bars.append(_bar(16505, 16515, 16505, 16515, start + timedelta(minutes=5)))
    # TP-hit bar.
    bars.append(_bar(16515, 16540, 16515, 16538, start + timedelta(minutes=6)))
    # Quiet drift: stay inside [16535, 16545] so we don't re-break the range_high=16510
    # ... but those closes ARE above 16510. The strategy's max_trades_per_day=2 allows
    # one more trade. To keep the integration test single-trade, we instead drift bars
    # that close BELOW the breakout entry but ABOVE range_low; pick prices that are
    # between range_low (16500) and range_high (16510) so neither side triggers.
    for i in range(7, 120):
        bars.append(_bar(16505, 16508, 16502, 16505, start + timedelta(minutes=i)))
    return bars


def test_orb_integration_produces_one_winning_round_trip() -> None:
    sim = SimExecutionClient()
    tracker = AccountStateTracker(start_balance=50_000, is_combine=True)
    gate = _make_gate(sim)
    profile = load_orb_profile(Path("config/profiles/surge.yml"))
    strategy = OpeningRangeBreakoutStrategy(profile)
    engine = BacktestEngine(
        strategy=strategy, gate=gate, tracker=tracker, sim=sim, symbol="MNQ",
    )
    bars = _synthesize_day()
    log = engine.run(bars)
    # Two intents (entry + exit), two approvals, no denials, two fills.
    assert log.intents_emitted == 2
    assert log.intents_approved == 2
    assert log.intents_denied == []
    assert len(log.fills) == 2
    # Realized PnL = (16538 - 16515) pts * 2 contracts * $2/pt = $92.
    assert log.final_state.realized_pnl_today == 92.0
    assert log.final_state.equity == 50_092.0
    assert log.final_state.open_positions == {}

    report = TradeReport.from_trade_log(log)
    assert report.total_trades == 1
    assert report.realized_pnl == 92.0
    assert report.win_rate == 1.0

    replay = RuleReplayReporter(gate_factory=lambda: _make_gate(SimExecutionClient()))
    replay_result = replay.replay([])  # v1 RuleReplay smoke check on empty replay
    assert replay_result.clean
