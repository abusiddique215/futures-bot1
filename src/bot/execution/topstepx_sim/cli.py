"""CLI runner: `python -m bot.execution.topstepx_sim --scenario <name>`.

Deviation from plan T6 prose: the scenarios in T4 are action-driven (each
scenario provides its own per-bar intent callbacks). Wiring them through
`LiveTradingLoop` + `OpeningRangeBreakoutStrategy` would require the ORB
state-machine to fire on the synthetic series — possible but redundant with
the unit + parity tests already in place. The CLI runs scenarios via
`run_scenario` directly; that is the only end-to-end exit point the spec
needs (Combine pass / fail / hard-flat). Strategy-driven runs go through
`python -m bot.backtest` (Plan 5) and `python -m bot.runtime` (Plan 10).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bot.execution.topstepx_sim.scenarios import (
    SCENARIOS,
    ScenarioResult,
    run_scenario,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bot.execution.topstepx_sim",
        description="Run a named TopstepX simulator scenario end-to-end.",
    )
    parser.add_argument(
        "--scenario",
        required=True,
        choices=sorted(SCENARIOS.keys()),
        help="Named scenario to execute (see scenarios.SCENARIOS).",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write the final account snapshot as JSON.",
    )
    return parser


async def run(scenario: str, *, json_out: Path | None) -> int:
    """Build + execute the named scenario; print a summary line."""
    factory = SCENARIOS[scenario]
    result = await run_scenario(factory())
    _print_summary(result)
    if json_out is not None:
        json_out.write_text(_to_json(result))
    return 0


def _print_summary(result: ScenarioResult) -> None:
    filled = sum(1 for ev in result.events if ev.status == "FILLED")
    rejected = sum(1 for ev in result.events if ev.status == "REJECTED")
    print(
        f"scenario={result.name} "
        f"stage={result.account.stage} "
        f"balance={result.account.balance:.2f} "
        f"equity={result.account.equity:.2f} "
        f"realized={result.account.realized_pnl:.2f} "
        f"unrealized={result.account.unrealized_pnl:.2f} "
        f"trades={filled} "
        f"rejected={rejected} "
        f"best_day={result.best_day_pnl:.2f} "
        f"net={result.net_pnl:.2f}",
    )


def _to_json(result: ScenarioResult) -> str:
    payload = {
        "scenario": result.name,
        "stage": result.account.stage,
        "balance": result.account.balance,
        "equity": result.account.equity,
        "realized_pnl": result.account.realized_pnl,
        "unrealized_pnl": result.account.unrealized_pnl,
        "high_water_equity": result.account.high_water_equity,
        "best_day_pnl": result.best_day_pnl,
        "net_pnl": result.net_pnl,
        "events": [
            {
                "client_order_id": ev.client_order_id,
                "status": ev.status,
                "avg_fill_price": ev.avg_fill_price,
                "metadata": ev.metadata,
            }
            for ev in result.events
        ],
    }
    return json.dumps(payload, indent=2, default=str)


async def cli_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return await run(scenario=args.scenario, json_out=args.json_out)
