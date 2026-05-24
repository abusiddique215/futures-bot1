"""Plan 14: `python -m bot.data.ingest` accepts --symbol for every registered market.

Regression coverage for NQ in tests/test_data_ingest_cli.py. This file
exercises a GC ingest end-to-end against a synthetic CSV fixture.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_ingest_cli_help_lists_all_registered_markets() -> None:
    """--symbol choices must include NQ, MNQ, ES, MES, GC, MGC."""
    result = subprocess.run(
        [sys.executable, "-m", "bot.data.ingest", "--help"],
        cwd=str(_PROJECT_ROOT),
        capture_output=True, text=True,
        env={"PYTHONPATH": str(_PROJECT_ROOT / "src")},
        check=False,
    )
    assert result.returncode == 0
    assert "--symbol" in result.stdout
    for root in ("NQ", "MNQ", "ES", "MES", "GC", "MGC"):
        assert root in result.stdout, (
            f"--symbol choices missing {root!r}; help text:\n{result.stdout}"
        )


def test_ingest_cli_ingests_gc(tmp_path: Path) -> None:
    """Synthetic GC fixture: one bar at the seam, writes parquet partition."""
    raw = tmp_path / "raw"
    raw.mkdir()
    # Synthetic 1-min GC bar (April 2026, $2200/oz).
    (raw / "GC_2026J_1min.csv").write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-04-15 09:30:00,2200.00,2200.50,2199.50,2200.10,123\n"
    )
    parquet = tmp_path / "parquet"

    result = subprocess.run(
        [sys.executable, "-m", "bot.data.ingest",
         "--symbol", "GC",
         "--raw-root", str(raw),
         "--parquet-root", str(parquet)],
        cwd=str(_PROJECT_ROOT),
        capture_output=True, text=True,
        env={"PYTHONPATH": str(_PROJECT_ROOT / "src")},
        check=False,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "rows_written=1" in result.stdout
    assert (parquet / "symbol=GC" / "contract=2026J").exists()
