"""Entry point: `python -m bot.execution.topstepx_sim --scenario <name>`."""
from __future__ import annotations

import asyncio
import sys

from bot.execution.topstepx_sim.cli import cli_main

if __name__ == "__main__":
    sys.exit(asyncio.run(cli_main()))
