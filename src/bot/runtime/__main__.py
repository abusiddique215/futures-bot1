"""`python -m bot.runtime` entry point.

Thin wrapper that drains an asyncio loop around cli_main. Production
callers invoke this; tests call bot.runtime.cli.cli_main directly.

Plan 22 T2: configures root logging at INFO so the startup banner +
fleet config lines (account_max_mini, dashboard URL, --check resolved
bots) reach stderr by default. Without this the operator runs
`--check` and sees no output, which makes the verification step
pointless.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from bot.runtime.cli import cli_main


def _entry() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    exit_code = asyncio.run(cli_main(sys.argv[1:]))
    sys.exit(exit_code)


if __name__ == "__main__":
    _entry()
