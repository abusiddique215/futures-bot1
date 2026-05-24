"""CLI entry point: python -m bot.backtest --strategy placeholder ...

Wires FirstRateDataLoader → BacktestEngine (with PlaceholderStrategy) and
prints a TradeReport summary + RuleReplay summary on completion. Continuous-
series loading (contract=None) raises NotImplementedError in Plan 2 — full
runs against ingested parquet land with Plan 5+. For now the CLI is shaped
so `python -m bot.backtest --help` works and the wiring is in place.

Plan 15 adds `--bot <name>`: loads `config/bots/<name>.yml`, builds the
strategy + risk gate via the registry, runs the engine, and emits a
ProofBundle to `state/proof/<bot>_<YYYYMMDD-HHMMSS>/`. The legacy
`--strategy {placeholder|orb}` path is untouched.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from bot.backtest.engine import BacktestEngine, TradeLog
from bot.backtest.report import TradeReport
from bot.backtest.rule_replay import RuleReplayReporter
from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.strategy import PlaceholderStrategy, Strategy
from bot.backtest.tracker import AccountStateTracker
from bot.data.firstratedata import FirstRateDataLoader
from bot.proof.generator import ProofBundle, ProofGenerator
from bot.proof.sources import BacktestLogSource
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.risk.news import NewsCalendar
from bot.runtime.fleet.registry import BotRegistry, ResolvedBot
from bot.runtime.fleet.spec import BotSpec, load_bot_specs
from bot.strategy.orb import OpeningRangeBreakoutStrategy
from bot.strategy.profile_loader import load_orb_profile
from bot.types import Bar


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
    parser.add_argument("--bot", default=None,
                        help="Bot name; loads config/bots/<name>.yml and runs the "
                             "engine through that bot's strategy + risk policy")
    parser.add_argument("--bots-dir", type=Path, default=Path("config/bots"),
                        help="Directory of BotSpec YAMLs (default: config/bots)")
    parser.add_argument("--data-fixture", type=Path, default=None,
                        help="CSV fixture for the --bot path (timestamp UTC + OHLCV)")
    parser.add_argument("--proof-output", type=Path, default=None,
                        help="Output dir for the proof bundle "
                             "(default: state/proof/<bot>_<ts>/)")
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


# ---- --bot path -------------------------------------------------------------

def _load_bot_spec(bot_name: str, bots_dir: Path) -> BotSpec:
    specs = load_bot_specs(bots_dir)
    for s in specs:
        if s.name == bot_name:
            return s
    available = ", ".join(sorted(s.name for s in specs))
    raise SystemExit(
        f"unknown --bot: {bot_name!r}. available: [{available}]",
    )


def _load_fixture_bars(path: Path, symbol: str, interval: str = "1m") -> list[Bar]:
    """Load OHLCV rows from a CSV fixture; timestamps are assumed UTC.

    Expected columns: timestamp, open, high, low, close, volume.
    """
    bars: list[Bar] = []
    with path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ts = datetime.fromisoformat(row["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            bars.append(Bar(
                symbol=symbol,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                timestamp=ts,
                interval=interval,
            ))
    return bars


def _serialise_trade_log_to_backtest_source(log: TradeLog, output: Path) -> None:
    """Dump approved_orders in the BacktestLogSource shape so the proof
    generator can read it back."""
    payload = {
        "approved_orders": [
            {
                "intent": {
                    "symbol": intent.symbol,
                    "side": intent.side,
                    "quantity": intent.quantity,
                },
                "event": {
                    "filled_quantity": event.filled_quantity,
                    "avg_fill_price": event.avg_fill_price,
                    "timestamp": event.timestamp.isoformat(),
                },
            }
            for intent, event in log.approved_orders
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2))


def _default_proof_output(bot_name: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Path("state/proof") / f"{bot_name}_{stamp}"


def _run_bot(args: argparse.Namespace) -> tuple[TradeLog, ProofBundle, ResolvedBot]:
    """Hydrate the BotSpec, build via registry, run the engine on fixture bars."""
    spec = _load_bot_spec(args.bot, args.bots_dir)
    sim = SimExecutionClient()
    registry = BotRegistry()
    resolved = registry.build(spec, broker=sim)

    if args.data_fixture is None:
        raise SystemExit(
            "--data-fixture is required when --bot is set "
            "(continuous-series loading is not implemented yet)",
        )
    bars = _load_fixture_bars(args.data_fixture, symbol=spec.symbol)

    start_balance = float(spec.risk_params.get("start_balance", 50_000.0))
    tracker = AccountStateTracker(
        start_balance=start_balance,
        is_combine=spec.risk_policy == "combine_intraday",
    )
    engine = BacktestEngine(
        strategy=resolved.strategy,
        gate=resolved.risk_gate,
        tracker=tracker,
        sim=sim,
        symbol=spec.symbol,
    )
    log = engine.run(bars)

    output_dir = args.proof_output if args.proof_output is not None else (
        _default_proof_output(spec.name)
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    # Round-trip the TradeLog through a JSON dump → BacktestLogSource so the
    # ProofGenerator picks up only fills (the shared sources layer.)
    log_dump_path = output_dir / "trade_log.json"
    _serialise_trade_log_to_backtest_source(log, log_dump_path)
    bundle = ProofGenerator().generate(
        source=BacktestLogSource(log_dump_path),
        bot_name=spec.name,
        output_dir=output_dir,
    )
    return log, bundle, resolved


# ---- main -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.bot is not None:
        log, bundle, resolved = _run_bot(args)
        print(
            f"BACKTEST_BOT_OK bot={resolved.name} symbol={resolved.spec.symbol} "
            f"intents_emitted={log.intents_emitted} "
            f"intents_approved={log.intents_approved} "
            f"intents_denied={len(log.intents_denied)} "
            f"fills={len(log.fills)} "
            f"report_html={bundle.html_path}",
        )
        return 0

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
    log = engine.run(bars)
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
