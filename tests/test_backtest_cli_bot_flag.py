"""`python -m bot.backtest --bot <name>` — Plan 15 T4.

Asserts the new flag loads the BotSpec via the registry, runs the engine
on a CSV fixture, and emits a Plan-13 ProofBundle. Legacy CLI behavior is
unchanged (covered by tests/test_backtest_cli.py).
"""
from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bot.backtest.cli import main as backtest_main


def _write_fixture_csv(path: Path, n_bars: int = 30) -> None:
    """Tiny synthetic 1-min OHLCV fixture (UTC), monotonic-rising prices."""
    lines = ["timestamp,open,high,low,close,volume"]
    start = datetime(2024, 1, 8, 14, 30, tzinfo=UTC)  # ET 09:30 in winter
    for i in range(n_bars):
        ts = start + timedelta(minutes=i)
        c = 18000.0 + i
        lines.append(
            f"{ts.isoformat()},{c:.2f},{c + 0.5:.2f},"
            f"{c - 0.5:.2f},{c:.2f},100",
        )
    path.write_text("\n".join(lines) + "\n")


def test_bot_flag_requires_data_fixture(tmp_path: Path) -> None:
    """`--bot foo` without `--data-fixture` exits non-zero with a clear msg."""
    with pytest.raises(SystemExit) as excinfo:
        backtest_main([
            "--bot", "surgebot_nq",
            "--start", "2024-01-01",
            "--end", "2024-01-31",
        ])
    assert "--data-fixture" in str(excinfo.value)


def test_bot_flag_unknown_bot_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        backtest_main([
            "--bot", "nonexistent_bot",
            "--start", "2024-01-01",
            "--end", "2024-01-31",
            "--data-fixture", "/tmp/does-not-matter.csv",
        ])
    assert "nonexistent_bot" in str(excinfo.value)


def test_bot_flag_runs_through_registry_and_emits_proof_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = tmp_path / "bars.csv"
    _write_fixture_csv(fixture)
    proof_dir = tmp_path / "proof"
    exit_code = backtest_main([
        "--bot", "surgebot_nq",
        "--start", "2024-01-01",
        "--end", "2024-01-31",
        "--data-fixture", str(fixture),
        "--proof-output", str(proof_dir),
    ])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "BACKTEST_BOT_OK" in captured.out
    assert "bot=surgebot_nq" in captured.out
    # The three proof artefacts MUST land in the proof dir.
    assert (proof_dir / "report.html").exists()
    assert (proof_dir / "report.json").exists()
    assert (proof_dir / "equity_curve.png").exists()
    # And the trade-log JSON we round-tripped through BacktestLogSource.
    assert (proof_dir / "trade_log.json").exists()


def test_legacy_strategy_path_still_works_in_help() -> None:
    """The legacy --strategy {placeholder|orb} interface must be preserved."""
    proc = subprocess.run(
        [sys.executable, "-m", "bot.backtest", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0
    assert "--strategy" in proc.stdout
    assert "--bot" in proc.stdout
    assert "--data-fixture" in proc.stdout
