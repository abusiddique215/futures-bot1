"""CLI runner: `python -m bot.execution.topstepx_sim --scenario <name>`.

Deviation from plan T6 prose: the scenarios in T4 are action-driven (each
scenario provides its own per-bar intent callbacks). Wiring them through
`LiveTradingLoop` + `OpeningRangeBreakoutStrategy` would require the ORB
state-machine to fire on the synthetic series — possible but redundant with
the unit + parity tests already in place. The CLI runs scenarios via
`run_scenario` directly; that is the only end-to-end exit point the spec
needs (Combine pass / fail / hard-flat). Strategy-driven runs go through
`python -m bot.backtest` (Plan 5) and `python -m bot.runtime` (Plan 10).

Plan 15 adds `--bot <name>`: looks up `config/bots/<name>.yml`, validates
it resolves cleanly through the registry, and labels the scenario output
with `bot=<name>`. Today the scenarios stay action-driven; the flag is a
spec-level binding so downstream tooling (and the eventual
strategy-driven scenarios) sees which bot a sim run was tagged for. See
the module docstring above for why we don't replay strategy logic through
the scenarios in this plan.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bot.backtest.sim_client import SimExecutionClient
from bot.execution.topstepx_sim.scenarios import (
    SCENARIOS,
    ScenarioResult,
    run_scenario,
)
from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.spec import BotSpec, load_bot_specs


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
    parser.add_argument(
        "--bot",
        default=None,
        help="Bot name; loads config/bots/<name>.yml, validates it resolves "
             "through the registry, and tags the summary output with bot=<name>.",
    )
    parser.add_argument(
        "--bots-dir",
        type=Path,
        default=Path("config/bots"),
        help="Directory of BotSpec YAMLs (default: config/bots)",
    )
    return parser


def _resolve_bot(bot_name: str, bots_dir: Path) -> BotSpec:
    """Look up the spec by name + assert it resolves through the registry."""
    specs = load_bot_specs(bots_dir)
    for spec in specs:
        if spec.name == bot_name:
            # Surface registry errors at CLI boot, not somewhere downstream.
            BotRegistry().build(spec, broker=SimExecutionClient())
            return spec
    available = ", ".join(sorted(s.name for s in specs))
    raise SystemExit(
        f"unknown --bot: {bot_name!r}. available: [{available}]",
    )


async def run(
    scenario: str,
    *,
    json_out: Path | None,
    bot: str | None = None,
    bots_dir: Path = Path("config/bots"),
) -> int:
    """Build + execute the named scenario; print a summary line."""
    bot_spec = _resolve_bot(bot, bots_dir) if bot is not None else None
    factory = SCENARIOS[scenario]
    result = await run_scenario(factory())
    _print_summary(result, bot_name=bot_spec.name if bot_spec else None)
    if json_out is not None:
        json_out.write_text(_to_json(result, bot_name=bot_spec.name if bot_spec else None))
    return 0


def _print_summary(result: ScenarioResult, *, bot_name: str | None) -> None:
    filled = sum(1 for ev in result.events if ev.status == "FILLED")
    rejected = sum(1 for ev in result.events if ev.status == "REJECTED")
    bot_field = f"bot={bot_name} " if bot_name else ""
    print(
        f"{bot_field}"
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


def _to_json(result: ScenarioResult, *, bot_name: str | None = None) -> str:
    payload: dict[str, object] = {
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
    if bot_name is not None:
        payload["bot"] = bot_name
    return json.dumps(payload, indent=2, default=str)


async def cli_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return await run(
        scenario=args.scenario,
        json_out=args.json_out,
        bot=getattr(args, "bot", None),
    )
