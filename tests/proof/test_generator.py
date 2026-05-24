"""ProofGenerator end-to-end: source → JSON + PNG + HTML bundle."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from bot.proof.generator import ProofBundle, ProofGenerator
from bot.proof.sources import BacktestLogSource


def _ts(minute: int) -> datetime:
    return datetime(2026, 1, 1, 14, minute, tzinfo=UTC)


def _write_backtest_log(path: Path) -> None:
    payload = {
        "approved_orders": [
            {
                "intent": {
                    "symbol": "MNQ", "side": "BUY", "quantity": 1,
                    "client_order_id": "rt1-open",
                    "timestamp": _ts(0).isoformat(),
                },
                "event": {
                    "client_order_id": "rt1-open", "filled_quantity": 1,
                    "avg_fill_price": 16_500.0, "timestamp": _ts(0).isoformat(),
                },
            },
            {
                "intent": {
                    "symbol": "MNQ", "side": "SELL", "quantity": 1,
                    "client_order_id": "rt1-close",
                    "timestamp": _ts(5).isoformat(),
                },
                "event": {
                    "client_order_id": "rt1-close", "filled_quantity": 1,
                    "avg_fill_price": 16_550.0, "timestamp": _ts(5).isoformat(),
                },
            },
        ]
    }
    path.write_text(json.dumps(payload))


def test_generate_writes_three_files_and_returns_bundle(tmp_path: Path) -> None:
    log_path = tmp_path / "log.json"
    _write_backtest_log(log_path)
    out_dir = tmp_path / "proof_out"

    bundle = ProofGenerator().generate(
        source=BacktestLogSource(log_path),
        bot_name="demo",
        output_dir=out_dir,
    )

    assert isinstance(bundle, ProofBundle)
    assert bundle.report_json_path == out_dir / "report.json"
    assert bundle.equity_curve_png_path == out_dir / "equity_curve.png"
    assert bundle.html_path == out_dir / "report.html"
    for p in (bundle.report_json_path,
              bundle.equity_curve_png_path,
              bundle.html_path):
        assert p.exists()
        assert p.stat().st_size > 0

    assert bundle.report.bot_name == "demo"
    assert bundle.report.net_profit == 100.0  # 50 pts * $2/pt for MNQ
    assert bundle.report.total_trades == 1

    json_data = json.loads(bundle.report_json_path.read_text())
    assert json_data["net_profit"] == 100.0
    assert json_data["bot_name"] == "demo"
    assert json_data["total_trades"] == 1


def test_generate_creates_nested_output_dir(tmp_path: Path) -> None:
    log_path = tmp_path / "log.json"
    _write_backtest_log(log_path)
    out_dir = tmp_path / "deep" / "nested" / "proof"

    bundle = ProofGenerator().generate(
        source=BacktestLogSource(log_path),
        bot_name="demo",
        output_dir=out_dir,
    )
    assert out_dir.is_dir()
    assert bundle.html_path.exists()
