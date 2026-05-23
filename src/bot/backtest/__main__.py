"""CLI entry point for bot.backtest module."""
from __future__ import annotations

import sys

from bot.backtest.cli import main

if __name__ == "__main__":
    sys.exit(main())
