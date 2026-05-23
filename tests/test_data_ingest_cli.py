"""bot.data.ingest CLI."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_ingest_cli_writes_parquet(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "NQ_2023Z_1min.csv").write_text(
        (_FIXTURES / "nq_2023z_clean.csv").read_text()
    )
    parquet = tmp_path / "parquet"

    result = subprocess.run(
        [sys.executable, "-m", "bot.data.ingest",
         "--symbol", "NQ",
         "--raw-root", str(raw),
         "--parquet-root", str(parquet)],
        cwd=str(_PROJECT_ROOT),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "rows_written=3" in result.stdout
    assert (parquet / "symbol=NQ" / "contract=2023Z").exists()


def test_ingest_cli_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bot.data.ingest", "--help"],
        cwd=str(_PROJECT_ROOT),
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--symbol" in result.stdout
    assert "--raw-root" in result.stdout
