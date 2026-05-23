"""CLI shim for `python -m bot.runtime`.

argparse boilerplate + thin awaiter around bot.runtime.main.main. Kept
separate from main.py so the orchestrator stays testable without arg
parsing.

Usage:
  python -m bot.runtime --config config/bot.example.yml
  python -m bot.runtime --config config/bot.example.yml --check
"""
from __future__ import annotations

import argparse
from pathlib import Path

from bot.runtime.main import main as _runtime_main


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argparse parser. Exposed for testing."""
    p = argparse.ArgumentParser(
        prog="bot.runtime",
        description="Topstep futures bot — 8-step startup orchestrator.",
    )
    p.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to bot.yml (e.g. config/bot.example.yml).",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Exit after reconcile + hydrate (no event loop). Smoke test.",
    )
    return p


async def cli_main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch to runtime.main. Returns the exit code.

    Production callers (`python -m bot.runtime`) wrap this in asyncio.run().
    Tests invoke it directly under pytest-asyncio.
    """
    args = build_parser().parse_args(argv)
    return await _runtime_main(
        config_path=args.config,
        check_only=args.check,
    )
