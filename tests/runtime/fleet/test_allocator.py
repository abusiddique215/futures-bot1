"""FleetAllocator — cross-bot account position cap (Plan 21 T1).

Tests cover:
  - Two bots both submit small intents → both approved (sum under cap).
  - Two bots both submit large intents → first approved, second denied.
  - Long + short across bots net to under cap → both approved.
  - Concurrent submits race-safe via internal lock.
  - SELL intents count toward absolute combined position.
  - Contract-suffixed symbol ("MNQH26") routes through the market lookup.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from bot.markets.registry import get_market
from bot.runtime.fleet.allocator import FleetAllocator
from bot.types import ApprovedOrder, OrderDenied, OrderIntent


def _intent(symbol: str, side: str, qty: int, cid: str) -> OrderIntent:
    return OrderIntent(
        symbol=symbol, side=side,  # type: ignore[arg-type]
        quantity=qty, order_type="MARKET",
        client_order_id=cid,
        timestamp=datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
    )


async def test_two_small_intents_both_approved() -> None:
    """2 bots each +3 MNQ; cap = 50 micros. Combined = 6 < 50 → both approved."""
    alloc = FleetAllocator(account_max_mini=5, market_lookup=get_market)
    fleet_positions: dict[str, dict[str, int]] = {"bot_a": {}, "bot_b": {}}

    a = await alloc.approve_intent("bot_a", _intent("MNQ", "BUY", 3, "a"), fleet_positions)
    b = await alloc.approve_intent("bot_b", _intent("MNQ", "BUY", 3, "b"), fleet_positions)

    assert isinstance(a, ApprovedOrder)
    assert isinstance(b, ApprovedOrder)


async def test_second_bot_denied_when_combined_breaches_cap() -> None:
    """Bot A +30 MNQ approved; bot B +30 MNQ denied (combined would = 60 > 50)."""
    alloc = FleetAllocator(account_max_mini=5, market_lookup=get_market)
    fleet_positions: dict[str, dict[str, int]] = {"bot_a": {}, "bot_b": {}}

    a = await alloc.approve_intent("bot_a", _intent("MNQ", "BUY", 30, "a"), fleet_positions)
    assert isinstance(a, ApprovedOrder)
    # After approval, allocator's pending allocations record bot_a's +30 contribution
    # so bot_b's call sees the pending state.
    b = await alloc.approve_intent("bot_b", _intent("MNQ", "BUY", 30, "b"), fleet_positions)
    assert isinstance(b, OrderDenied)
    assert b.rule == "FLEET_POSITION_CAP"
    assert "MNQ" in b.reason
    assert "60" in b.reason or "cap" in b.reason.lower()


async def test_long_plus_short_net_under_cap_both_approved() -> None:
    """Bot A short -10 MNQ, Bot B long +10 MNQ: net = 0, both approved.

    The cap is on |combined signed position|, not on |total absolute exposure|.
    """
    alloc = FleetAllocator(account_max_mini=5, market_lookup=get_market)
    fleet_positions: dict[str, dict[str, int]] = {"bot_a": {}, "bot_b": {}}

    a = await alloc.approve_intent("bot_a", _intent("MNQ", "SELL", 10, "a"), fleet_positions)
    b = await alloc.approve_intent("bot_b", _intent("MNQ", "BUY", 10, "b"), fleet_positions)

    assert isinstance(a, ApprovedOrder)
    assert isinstance(b, ApprovedOrder)


async def test_contract_suffix_symbol_resolves_via_market_lookup() -> None:
    """MNQH26 (with contract suffix) → cap from MNQ market spec, not KeyError."""
    alloc = FleetAllocator(account_max_mini=5, market_lookup=get_market)
    fleet_positions: dict[str, dict[str, int]] = {"bot_a": {}}

    result = await alloc.approve_intent(
        "bot_a", _intent("MNQH26", "BUY", 3, "a"), fleet_positions,
    )
    assert isinstance(result, ApprovedOrder)


async def test_full_contract_uses_smaller_cap() -> None:
    """Full NQ (not micro). cap = 5 minis = 5 contracts.
    +6 NQ from one bot → denied (6 > 5)."""
    alloc = FleetAllocator(account_max_mini=5, market_lookup=get_market)
    fleet_positions: dict[str, dict[str, int]] = {"bot_a": {}}

    result = await alloc.approve_intent(
        "bot_a", _intent("NQ", "BUY", 6, "a"), fleet_positions,
    )
    assert isinstance(result, OrderDenied)
    assert result.rule == "FLEET_POSITION_CAP"


async def test_concurrent_submits_aggregate_correctly() -> None:
    """3 bots concurrently submit +20 MNQ each; cap = 50.

    Expected: first two approved (40 <= 50), third denied (60 > 50).
    The lock is what makes this deterministic — without it the race could
    approve all three.
    """
    suspend = asyncio.Event()

    async def lookup_with_suspend(symbol: str):  # type: ignore[no-untyped-def]
        # Suspend on first call so concurrent calls all wait on the same
        # event, then proceed in order once released.
        await suspend.wait()
        return get_market(symbol)

    alloc = FleetAllocator(
        account_max_mini=5,
        market_lookup=lookup_with_suspend,  # type: ignore[arg-type]
    )
    fleet_positions: dict[str, dict[str, int]] = {f"bot_{i}": {} for i in range(3)}

    async def submit(bot_name: str, cid: str):  # type: ignore[no-untyped-def]
        return await alloc.approve_intent(
            bot_name, _intent("MNQ", "BUY", 20, cid), fleet_positions,
        )

    # Launch all 3 concurrently; they should serialize via the lock.
    t1 = asyncio.create_task(submit("bot_0", "c0"))
    t2 = asyncio.create_task(submit("bot_1", "c1"))
    t3 = asyncio.create_task(submit("bot_2", "c2"))
    # Yield so all 3 tasks start and queue on the suspend event.
    await asyncio.sleep(0)
    suspend.set()
    results = await asyncio.gather(t1, t2, t3)

    approved = [r for r in results if isinstance(r, ApprovedOrder)]
    denied = [r for r in results if isinstance(r, OrderDenied)]
    assert len(approved) == 2, f"expected 2 approvals, got {len(approved)}"
    assert len(denied) == 1, f"expected 1 denial, got {len(denied)}"
    assert denied[0].rule == "FLEET_POSITION_CAP"


async def test_existing_tracker_position_counts_toward_cap() -> None:
    """Bot A already long +40 MNQ (in fleet_positions). Bot B wants +20.
    Combined = 60 > 50 → bot B denied."""
    alloc = FleetAllocator(account_max_mini=5, market_lookup=get_market)
    fleet_positions: dict[str, dict[str, int]] = {
        "bot_a": {"MNQ": 40},
        "bot_b": {},
    }
    result = await alloc.approve_intent(
        "bot_b", _intent("MNQ", "BUY", 20, "b"), fleet_positions,
    )
    assert isinstance(result, OrderDenied)


async def test_cross_symbol_intents_dont_interact() -> None:
    """Bot A +50 MNQ, Bot B +5 MES. Each is at cap for its own market;
    neither denies the other."""
    alloc = FleetAllocator(account_max_mini=5, market_lookup=get_market)
    fleet_positions: dict[str, dict[str, int]] = {"bot_a": {}, "bot_b": {}}

    a = await alloc.approve_intent("bot_a", _intent("MNQ", "BUY", 50, "a"), fleet_positions)
    b = await alloc.approve_intent("bot_b", _intent("MES", "BUY", 5, "b"), fleet_positions)

    assert isinstance(a, ApprovedOrder)
    assert isinstance(b, ApprovedOrder)


async def test_release_intent_frees_pending_allocation() -> None:
    """When a previously-approved intent is later released (e.g., the broker
    rejected), the allocator clears its pending allocation so capacity is
    available again."""
    alloc = FleetAllocator(account_max_mini=5, market_lookup=get_market)
    fleet_positions: dict[str, dict[str, int]] = {"bot_a": {}, "bot_b": {}}

    a = await alloc.approve_intent("bot_a", _intent("MNQ", "BUY", 30, "a"), fleet_positions)
    assert isinstance(a, ApprovedOrder)

    # Release bot_a's allocation (simulating broker rejection / cancel).
    alloc.release_intent("bot_a", _intent("MNQ", "BUY", 30, "a"))

    # Now bot_b's +30 fits.
    b = await alloc.approve_intent("bot_b", _intent("MNQ", "BUY", 30, "b"), fleet_positions)
    assert isinstance(b, ApprovedOrder)


@pytest.mark.parametrize(("side", "qty", "expected_signed"), [
    ("BUY", 5, 5),
    ("SELL", 5, -5),
])
async def test_signed_qty_used_for_projection(side: str, qty: int, expected_signed: int) -> None:
    alloc = FleetAllocator(account_max_mini=5, market_lookup=get_market)
    fleet_positions: dict[str, dict[str, int]] = {"bot_a": {}}
    result = await alloc.approve_intent(
        "bot_a", _intent("MNQ", side, qty, "a"), fleet_positions,
    )
    assert isinstance(result, ApprovedOrder)
    # Internal state — projected position == expected_signed
    assert alloc._pending["bot_a"]["MNQ"] == expected_signed  # type: ignore[attr-defined]
