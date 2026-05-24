"""CLI shim for `python -m bot.runtime`.

Two top-level dispatch paths (mutually exclusive):
  --config <bot.yml>      single-bot startup (legacy, Plan 9)
  --bots   <bots-dir>     multi-bot fleet     (Plan 12)

Both accept `--check` for the smoke-test path that exits before the
event loop / fleet `.run()`.

Usage:
  python -m bot.runtime --config config/bot.example.yml
  python -m bot.runtime --bots   config/bots/ --check
"""
from __future__ import annotations

import argparse
from pathlib import Path

from bot.runtime.main import main as _runtime_main
from bot.runtime.main import run_fleet as _runtime_fleet


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argparse parser. Exposed for testing."""
    p = argparse.ArgumentParser(
        prog="bot.runtime",
        description="Topstep futures bot — single-bot or multi-bot orchestrator.",
    )
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a single-bot bot.yml (e.g. config/bot.example.yml).",
    )
    grp.add_argument(
        "--bots",
        type=Path,
        default=None,
        help="Path to a directory of per-bot YAML files (e.g. config/bots/).",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Exit after reconcile + hydrate (no event loop). Smoke test.",
    )
    # Plan 21: dashboard side-car (loopback-only read-only fleet monitor).
    p.add_argument(
        "--dashboard",
        action="store_true",
        help="Run the local read-only dashboard alongside the fleet "
             "(--bots only). Binds to 127.0.0.1.",
    )
    p.add_argument(
        "--dashboard-port",
        type=int,
        default=8765,
        help="Port for --dashboard. Default 8765.",
    )
    return p


async def cli_main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch to runtime.main or runtime.run_fleet."""
    args = build_parser().parse_args(argv)
    if args.bots is not None:
        return await _runtime_fleet(
            bots_dir=args.bots,
            check_only=args.check,
            dashboard_enabled=args.dashboard,
            dashboard_port=args.dashboard_port,
        )
    if args.dashboard:
        # Single-bot mode (--config) doesn't run the fleet dashboard. Be
        # loud about the mismatch instead of silently ignoring the flag.
        raise SystemExit("--dashboard requires --bots (the fleet runtime).")
    return await _runtime_main(
        config_path=args.config,
        check_only=args.check,
    )
