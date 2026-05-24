"""Scenario builder tests (Plan 11 T4). Each named scenario runs to a known
terminal state through the engine + client."""
from __future__ import annotations

import pytest

from bot.execution.topstepx_sim.scenarios import (
    combine_fail_max_position,
    combine_fail_mll_50k,
    combine_pass_50k,
    efa_consistency_breach,
    efa_payout_flow_50k,
    hard_flat_at_1510_ct,
    run_scenario,
)


async def test_combine_pass_50k_terminates_passed() -> None:
    scenario = combine_pass_50k()
    result = await run_scenario(scenario)
    assert result.account.stage == "combine_passed"
    assert result.account.balance >= 53_000.0  # hit $3K profit target


async def test_combine_fail_mll_50k_terminates_failed() -> None:
    scenario = combine_fail_mll_50k()
    result = await run_scenario(scenario)
    assert result.account.stage == "combine_failed"


async def test_combine_fail_max_position_rejects_oversize() -> None:
    scenario = combine_fail_max_position()
    result = await run_scenario(scenario)
    # Strategy submitted 51 MNQ → engine rejects, no fill.
    assert all(ev.status == "REJECTED" for ev in result.events)
    assert result.account.open_positions == {}
    # Stage stays combine_active (no MLL breach, just bad sizing).
    assert result.account.stage == "combine_active"


async def test_efa_payout_flow_50k_reaches_efa_payout() -> None:
    scenario = efa_payout_flow_50k()
    result = await run_scenario(scenario)
    assert result.account.stage == "efa_payout"


async def test_efa_consistency_breach_denied_by_policy() -> None:
    """A single-day P&L > 40% of total net is flagged by EFAConsistencyDrawdown."""
    from bot.risk.efa_drawdown import EFAConsistencyDrawdown

    scenario = efa_consistency_breach()
    result = await run_scenario(scenario)
    policy = EFAConsistencyDrawdown(mll_amount=2_000.0)
    assert policy.gate_payout(
        best_day=result.best_day_pnl,
        net_profit=result.net_pnl,
    ) is False


async def test_hard_flat_at_1510_ct_rejects_post_cutoff_opens() -> None:
    scenario = hard_flat_at_1510_ct()
    result = await run_scenario(scenario)
    assert any(
        ev.status == "REJECTED"
        and ev.metadata is not None
        and ev.metadata.get("reason") == "HARD_FLAT_CLOCK"
        for ev in result.events
    )


@pytest.mark.parametrize(
    ("scenario_factory", "expected_stage"),
    [
        (combine_pass_50k, "combine_passed"),
        (combine_fail_mll_50k, "combine_failed"),
        (combine_fail_max_position, "combine_active"),
        (efa_payout_flow_50k, "efa_payout"),
    ],
)
async def test_named_scenario_terminates_in_expected_stage(
    scenario_factory: object,
    expected_stage: str,
) -> None:
    scenario = scenario_factory()  # type: ignore[operator]
    result = await run_scenario(scenario)
    assert result.account.stage == expected_stage
