"""CLI shim for `python -m bot.runtime`.

Two top-level dispatch paths (mutually exclusive):
  --config <bot.yml>      single-bot startup (legacy, Plan 9)
  --bots   <bots-dir>     multi-bot fleet     (Plan 12)

Both accept `--check` for the smoke-test path that exits before the
event loop / fleet `.run()`.

Usage:
  python -m bot.runtime --config config/bot.example.yml
  python -m bot.runtime --bots   config/bots/ --check
  python -m bot.runtime --bots   config/bots/ --account-max-mini 15
"""
from __future__ import annotations

import argparse
from pathlib import Path

from bot.runtime.main import main as _runtime_main
from bot.runtime.main import run_fleet as _runtime_fleet


def _positive_int(value: str) -> int:
    """argparse type: parse `value` as an int and require it to be > 0.

    Plan 22 T2 — `--account-max-mini` must be a positive integer. Argparse's
    bare `type=int` accepts 0 and negatives; this wrapper rejects both so
    the CLI fails loudly at parse time rather than at allocator-construction
    time deep inside run_fleet.
    """
    try:
        n = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"expected a positive integer, got {value!r}",
        ) from e
    if n <= 0:
        raise argparse.ArgumentTypeError(
            f"must be > 0, got {n}",
        )
    return n


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
    # Plan 22 T2: cross-bot account cap. Default 5 = Topstep $50K Combine
    # cap. $100K = 10, $150K = 15. Per-bot risk_params.max_mini still applies
    # via the bot's own gate; this is the FLEET-WIDE shared-account cap.
    p.add_argument(
        "--account-max-mini",
        type=_positive_int,
        default=5,
        help="Account-wide max minis across all bots (FleetAllocator). "
             "Default 5 (Topstep $50K Combine). $100K=10, $150K=15.",
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
            account_max_mini=args.account_max_mini,
        )
    if args.dashboard:
        # Single-bot mode (--config) doesn't run the fleet dashboard. Be
        # loud about the mismatch instead of silently ignoring the flag.
        raise SystemExit("--dashboard requires --bots (the fleet runtime).")
    return await _runtime_main(
        config_path=args.config,
        check_only=args.check,
    )
