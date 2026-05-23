"""bot.backtest CLI (python -m bot.backtest) — argparse + entry point.

Integration against real parquet is out of scope here (FirstRateDataLoader.load
with contract=None raises NotImplementedError as of Plan 2). These tests cover
the argparse contract only; engine behavior is tested at lower levels.
"""
from __future__ import annotations

import subprocess
import sys


def test_cli_help_exits_zero_and_lists_start_flag() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "bot.backtest", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--start" in proc.stdout
    assert "--end" in proc.stdout
    assert "--symbol" in proc.stdout


def test_cli_missing_required_args_exits_nonzero() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "bot.backtest"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "--start" in proc.stderr or "--end" in proc.stderr


def test_cli_help_lists_profile_flag_when_strategy_orb_available() -> None:
    """`--help` should mention --profile because orb is a supported strategy."""
    proc = subprocess.run(
        [sys.executable, "-m", "bot.backtest", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--profile" in proc.stdout
    assert "orb" in proc.stdout


def test_cli_strategy_orb_requires_profile_argument() -> None:
    """--strategy orb without --profile must exit non-zero with a clear message."""
    proc = subprocess.run(
        [
            sys.executable, "-m", "bot.backtest",
            "--strategy", "orb",
            "--start", "2026-05-22",
            "--end", "2026-05-23",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "--profile" in proc.stderr or "--profile" in proc.stdout
