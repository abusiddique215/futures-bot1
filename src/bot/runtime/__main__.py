"""`python -m bot.runtime` entry point.

Thin wrapper that drains an asyncio loop around cli_main. Production
callers invoke this; tests call bot.runtime.cli.cli_main directly.
"""
from __future__ import annotations

import asyncio
import sys

from bot.runtime.cli import cli_main


def _entry() -> None:
    exit_code = asyncio.run(cli_main(sys.argv[1:]))
    sys.exit(exit_code)


if __name__ == "__main__":
    _entry()
