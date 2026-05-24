"""ProofGenerator — orchestrates source → StrategyReport → 3-file bundle.

Bundle contents (under `output_dir`):
  - report.json        : StrategyReport fields as JSON
  - equity_curve.png   : cumulative-PnL curve
  - report.html        : HTML page embedding the PNG + metric tables
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from bot.proof.metrics import StrategyReport, compute_report
from bot.proof.render import render_equity_curve, render_html
from bot.proof.sources import TradeSource

_EQUITY_PNG_NAME = "equity_curve.png"
_REPORT_JSON_NAME = "report.json"
_REPORT_HTML_NAME = "report.html"


@dataclass(frozen=True)
class ProofBundle:
    """Paths + summary returned by ProofGenerator.generate()."""
    report_json_path: Path
    equity_curve_png_path: Path
    html_path: Path
    report: StrategyReport


class ProofGenerator:
    """Pure orchestrator. Stateless; one instance can produce many bundles."""

    def generate(
        self,
        source: TradeSource,
        bot_name: str,
        output_dir: Path,
    ) -> ProofBundle:
        output_dir.mkdir(parents=True, exist_ok=True)
        trades = list(source.iter_closed_trades())
        report = compute_report(trades, bot_name=bot_name)

        json_path = output_dir / _REPORT_JSON_NAME
        json_path.write_text(json.dumps(_report_to_dict(report), indent=2))

        png_path = output_dir / _EQUITY_PNG_NAME
        render_equity_curve(trades, bot_name, png_path)

        html_path = output_dir / _REPORT_HTML_NAME
        render_html(report, _EQUITY_PNG_NAME, html_path)

        return ProofBundle(
            report_json_path=json_path,
            equity_curve_png_path=png_path,
            html_path=html_path,
            report=report,
        )


def _report_to_dict(report: StrategyReport) -> dict[str, Any]:
    """asdict + ISO-format the two datetime fields so JSON serializer accepts."""
    raw = asdict(report)
    for key in ("period_start", "period_end"):
        value = raw[key]
        if isinstance(value, datetime):
            raw[key] = value.isoformat()
    return raw
