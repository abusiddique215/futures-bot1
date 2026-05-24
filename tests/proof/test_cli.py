"""CLI runner for the proof bundle."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bot.proof.cli import main


def _ts(minute: int) -> datetime:
    return datetime(2026, 1, 1, 14, minute, tzinfo=UTC)


def _write_backtest_log(path: Path) -> None:
    payload = {
        "approved_orders": [
            {
                "intent": {
                    "symbol": "MNQ", "side": "BUY", "quantity": 1,
                    "client_order_id": "o1",
                    "timestamp": _ts(0).isoformat(),
                },
                "event": {
                    "client_order_id": "o1", "filled_quantity": 1,
                    "avg_fill_price": 16_500.0, "timestamp": _ts(0).isoformat(),
                },
            },
            {
                "intent": {
                    "symbol": "MNQ", "side": "SELL", "quantity": 1,
                    "client_order_id": "o2",
                    "timestamp": _ts(5).isoformat(),
                },
                "event": {
                    "client_order_id": "o2", "filled_quantity": 1,
                    "avg_fill_price": 16_550.0, "timestamp": _ts(5).isoformat(),
                },
            },
        ]
    }
    path.write_text(json.dumps(payload))


def test_cli_backtest_source_writes_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    log = tmp_path / "log.json"
    _write_backtest_log(log)
    out = tmp_path / "out"

    rc = main([
        "--backtest", str(log),
        "--bot", "demo_bot",
        "--output", str(out),
    ])
    assert rc == 0
    assert (out / "report.json").exists()
    assert (out / "equity_curve.png").exists()
    assert (out / "report.html").exists()
    printed = capsys.readouterr().out
    assert "report.json" in printed
    assert "equity_curve.png" in printed
    assert "report.html" in printed


def test_cli_no_source_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--bot", "demo"])
    assert exc.value.code != 0


def test_cli_both_sources_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    log = tmp_path / "log.json"
    _write_backtest_log(log)
    db = tmp_path / "j.db"
    db.write_bytes(b"")  # placeholder; argparse rejects before we read it
    with pytest.raises(SystemExit) as exc:
        main([
            "--backtest", str(log),
            "--journal", str(db),
            "--bot", "demo",
        ])
    assert exc.value.code != 0


def test_python_dash_m_invocation_exit_zero(
    tmp_path: Path,
) -> None:
    """Smoke-test `python -m bot.proof ...` to confirm __main__ wires up."""
    import subprocess

    log = tmp_path / "log.json"
    _write_backtest_log(log)
    out = tmp_path / "out"
    res = subprocess.run(
        [sys.executable, "-m", "bot.proof",
         "--backtest", str(log), "--bot", "demo", "--output", str(out)],
        capture_output=True, text=True, check=False,
    )
    assert res.returncode == 0, res.stderr
    assert (out / "report.json").exists()
