"""CLI entry point: python -m bot.data.ingest --symbol <ROOT> --raw-root ... --parquet-root ...

Plan 14: `--symbol` accepts any root registered in `bot.markets.registry.MARKETS`
(NQ, MNQ, ES, MES, GC, MGC as of 2026-05-23). The loader is symbol-agnostic;
the filename regex in `bot.data.firstratedata` is the per-market gate.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bot.data.firstratedata import FirstRateDataLoader, IngestQualityError
from bot.markets.registry import MARKETS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bot.data.ingest")
    parser.add_argument(
        "--symbol", required=True, choices=sorted(MARKETS.keys()),
    )
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--parquet-root", required=True, type=Path)
    parser.add_argument("--quarantine-threshold", type=float, default=0.001)
    args = parser.parse_args(argv)

    loader = FirstRateDataLoader(raw_root=args.raw_root, parquet_root=args.parquet_root)
    try:
        summary = loader.ingest(
            symbol=args.symbol,
            quarantine_rate_threshold=args.quarantine_threshold,
        )
    except IngestQualityError as e:
        print(f"INGEST_FAILED: {e}", file=sys.stderr)
        return 2

    print(
        f"INGEST_OK symbol={args.symbol} "
        f"rows_written={summary.rows_written} "
        f"rows_quarantined={summary.rows_quarantined} "
        f"files_processed={summary.files_processed} "
        f"files_skipped={summary.files_skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
