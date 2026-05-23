"""CLI entry point: python -m bot.backtest --strategy placeholder ...

Wires FirstRateDataLoader → BacktestEngine (with PlaceholderStrategy) and
prints a TradeReport summary + RuleReplay summary on completion. Continuous-
series loading (contract=None) raises NotImplementedError in Plan 2 — full
runs against ingested parquet land with Plan 5+. For now the CLI is shaped
so `python -m bot.backtest --help` works and the wiring is in place.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from bot.backtest.engine import BacktestEngine, TradeLog
from bot.backtest.report import TradeReport
from bot.backtest.rule_replay import RuleReplayReporter
from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.strategy import PlaceholderStrategy, Strategy
from bot.backtest.tracker import AccountStateTracker
from bot.data.firstratedata import FirstRateDataLoader
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.risk.news import NewsCalendar
from bot.strategy.orb import OpeningRangeBreakoutStrategy
from bot.strategy.profile_loader import load_orb_profile


class _NoNewsCalendar:
    """Backtest-mode no-op calendar (no high-impact windows)."""

    def in_window(self, now: datetime) -> bool:
        return False

    def max_position_during_window(self) -> int:
        return 1


class _NoopTelemetry:
    def alert(self, kind: str, **kw: object) -> None:
        return None


def _parse_date(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bot.backtest")
    parser.add_argument("--strategy", choices=["placeholder", "orb"], default="placeholder")
    parser.add_argument("--symbol", choices=["MNQ", "NQ"], default="MNQ")
    parser.add_argument("--start", required=True, type=_parse_date,
                        help="UTC start (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, type=_parse_date,
                        help="UTC end (YYYY-MM-DD)")
    parser.add_argument("--parquet-root", type=Path, default=Path("data/parquet"))
    parser.add_argument("--start-balance", type=float, default=50_000.0)
    parser.add_argument("--contract", default=None,
                        help="Optional contract code (e.g. NQH24); "
                             "default uses continuous series")
    parser.add_argument("--profile", type=Path, default=None,
                        help="Strategy profile YAML (required when --strategy orb)")
    return parser


def _build_strategy(args: argparse.Namespace) -> Strategy:
    if args.strategy == "placeholder":
        return PlaceholderStrategy()
    if args.strategy == "orb":
        if args.profile is None:
            raise SystemExit("--profile is required when --strategy orb")
        profile = load_orb_profile(args.profile)
        return OpeningRangeBreakoutStrategy(profile)
    raise SystemExit(f"unknown strategy: {args.strategy}")


def _make_gate(
    sim: SimExecutionClient, news: NewsCalendar, start_balance: float,
) -> TopstepRiskGate:
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(start_balance, 2_000, 5)
    return TopstepRiskGate(
        policy=policy,
        news_calendar=news,
        execution_client=sim,
        telemetry=_NoopTelemetry(),
        config=cfg,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    strategy = _build_strategy(args)
    loader = FirstRateDataLoader(raw_root=args.parquet_root, parquet_root=args.parquet_root)
    bars = loader.load(
        symbol=args.symbol,
        contract=args.contract,
        start=args.start,
        end=args.end,
    )
    sim = SimExecutionClient()
    tracker = AccountStateTracker(
        start_balance=args.start_balance, is_combine=True,
    )
    news = _NoNewsCalendar()
    gate = _make_gate(sim, news, args.start_balance)
    engine = BacktestEngine(
        strategy=strategy,
        gate=gate, tracker=tracker, sim=sim, symbol=args.symbol,
    )
    log: TradeLog = engine.run(bars)
    report = TradeReport.from_trade_log(log)
    replay = RuleReplayReporter(
        gate_factory=lambda: _make_gate(SimExecutionClient(), news, args.start_balance),
    )
    replay_result = replay.replay([])  # no approved-order state snapshots in v1
    print(
        f"BACKTEST_OK symbol={args.symbol} "
        f"intents_emitted={log.intents_emitted} "
        f"intents_approved={log.intents_approved} "
        f"intents_denied={len(log.intents_denied)} "
        f"fills={len(log.fills)} "
        f"total_trades={report.total_trades} "
        f"realized_pnl={report.realized_pnl:.2f} "
        f"max_drawdown={report.max_drawdown_dollars:.2f} "
        f"win_rate={report.win_rate:.2f} "
        f"profit_factor={report.profit_factor:.2f} "
        f"replay_clean={replay_result.clean} "
        f"replay_violations={len(replay_result.violations)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
