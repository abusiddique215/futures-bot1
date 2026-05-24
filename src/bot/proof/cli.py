"""CLI runner: `python -m bot.proof --backtest <log.json> --bot <name>`.

Mutually exclusive source flags (`--journal` xor `--backtest`); `--output`
defaults to `state/proof/<bot_name>_<YYYYMMDD-HHMMSS>/`.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from bot.proof.generator import ProofGenerator
from bot.proof.sources import BacktestLogSource, JournalSource, TradeSource


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bot.proof",
        description="Generate a per-bot proof bundle (JSON + PNG + HTML).",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--journal", type=Path, default=None,
                        help="Path to a journal SQLite db.")
    source.add_argument("--backtest", type=Path, default=None,
                        help="Path to a backtest TradeLog JSON dump.")
    parser.add_argument("--bot", required=True,
                        help="Bot name (also used as the no-op journal filter).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output directory (default: state/proof/<bot>_<ts>/).")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    source: TradeSource
    if args.journal is not None:
        source = JournalSource(args.journal, bot_name=args.bot)
    else:
        source = BacktestLogSource(args.backtest)

    output_dir: Path = args.output if args.output is not None else _default_output(args.bot)

    bundle = ProofGenerator().generate(
        source=source,
        bot_name=args.bot,
        output_dir=output_dir,
    )
    print(f"report.json:        {bundle.report_json_path}")
    print(f"equity_curve.png:   {bundle.equity_curve_png_path}")
    print(f"report.html:        {bundle.html_path}")
    return 0


def _default_output(bot_name: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Path("state/proof") / f"{bot_name}_{stamp}"
