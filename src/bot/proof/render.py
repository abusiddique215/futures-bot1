"""Equity-curve PNG renderer + HTML report renderer.

matplotlib is forced to the headless Agg backend at module import — required
for CI hosts and macOS LaunchAgents that have no display. The `use(...)` call
MUST precede any `pyplot` import.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # MUST precede pyplot import — headless rendering.

import matplotlib.pyplot as plt
from jinja2 import Environment, FileSystemLoader, select_autoescape

from bot.proof.metrics import ClosedTrade, StrategyReport

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "j2"]),
)


def _fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _fmt_float(value: float) -> str:
    return f"{value:.3f}"


_ENV.globals.update(
    fmt_money=_fmt_money, fmt_pct=_fmt_pct, fmt_float=_fmt_float,
)


def render_equity_curve(
    trades: list[ClosedTrade], bot_name: str, output_path: Path,
) -> Path:
    """Write a 1200x600 PNG of cumulative net P&L vs exit timestamp.

    Empty trade list produces a PNG with a "No trades yet" placeholder rather
    than crashing — proof bundles are valuable even at zero trades for
    operational visibility.
    """
    fig, ax = plt.subplots(figsize=(12, 6), dpi=100)
    if not trades:
        ax.text(
            0.5, 0.5, "No trades yet",
            ha="center", va="center", fontsize=24, color="#888888",
            transform=ax.transAxes,
        )
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        xs = [t.exit_ts for t in trades]
        equity = 0.0
        ys: list[float] = []
        for t in trades:
            equity += t.pnl
            ys.append(equity)
        ax.plot(xs, ys, color="#1f77b4", linewidth=2.0)
        ax.axhline(0.0, color="#999999", linewidth=0.8, linestyle="--")
        ax.set_xlabel("Exit timestamp (UTC)")
        ax.set_ylabel("Cumulative P&L ($)")
        fig.autofmt_xdate()
    ax.set_title(f"Equity curve - {bot_name}")
    fig.tight_layout()
    fig.savefig(output_path, format="png")
    plt.close(fig)
    return output_path


def render_html(
    report: StrategyReport, equity_curve_filename: str, output_path: Path,
) -> Path:
    """Render the proof HTML page from the Jinja2 template.

    `equity_curve_filename` is written into the `<img src=...>` as-is — keep
    it relative to `output_path.parent` so the bundle stays portable.
    """
    template = _ENV.get_template("report.html.j2")
    html = template.render(report=report, equity_curve_filename=equity_curve_filename)
    output_path.write_text(html)
    return output_path
