"""Named end-to-end scenarios for the TopstepX simulator.

Each scenario bundles a SimAccount + TopstepSimEngine + TopstepXSimClient + a
synthetic bar series + a queue of `(bar_index, intent)` actions. `run_scenario`
drives the bars one by one, marking-to-market, dispatching actions, and
collecting OrderEvents. Used by the CLI runner and the integration tests.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from bot.execution.topstepx_sim.account import (
    SimAccount,
    Stage,
    advance_stage,
)
from bot.execution.topstepx_sim.client import TopstepXSimClient
from bot.execution.topstepx_sim.engine import TopstepSimEngine
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
from bot.types import Bar, OrderEvent, OrderIntent

# ---- Scenario data shapes ---------------------------------------------------

ActionFn = Callable[[TopstepXSimClient, Bar], Awaitable[list[OrderEvent]]]


@dataclass
class Scenario:
    """A self-contained run: bars + engine + per-bar actions."""
    name: str
    engine: TopstepSimEngine
    client: TopstepXSimClient
    bars: list[Bar]
    actions: list[ActionFn] = field(default_factory=list)
    # Optional post-run stage transition (e.g. broker promotes Combine → EFA).
    terminal_stage: Stage | None = None


@dataclass
class ScenarioResult:
    name: str
    account: SimAccount
    events: list[OrderEvent]
    best_day_pnl: float
    net_pnl: float


# ---- Helpers ----------------------------------------------------------------

_DEFAULT_START: Final[datetime] = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)


def _bars(
    closes: list[float],
    *,
    symbol: str = "MNQ",
    start: datetime = _DEFAULT_START,
    interval_minutes: int = 1,
) -> list[Bar]:
    return [
        Bar(
            symbol=symbol,
            open=c, high=c, low=c, close=c,
            volume=100,
            timestamp=start + timedelta(minutes=i * interval_minutes),
            interval=f"{interval_minutes}m",
        )
        for i, c in enumerate(closes)
    ]


def _make_engine(
    *,
    stage: Stage = "combine_active",
    slippage_ticks: int = 0,
    start_clock: datetime = _DEFAULT_START,
) -> TopstepSimEngine:
    account = SimAccount.new(
        start_balance=50_000.0, mll_amount=2_000.0, stage=stage,
    )
    combine = CombineIntradayDrawdown(50_000.0, 2_000.0, max_mini=5)
    efa = EFAStandardEoDDrawdown(mll_amount=2_000.0)
    return TopstepSimEngine(
        account=account,
        combine_policy=combine,
        efa_policy=efa,
        slippage_ticks=slippage_ticks,
        now=lambda: start_clock,
    )


def _make_client(engine: TopstepSimEngine, bars: list[Bar]) -> TopstepXSimClient:
    # mid source returns the close of the most-recent bar processed (engine's
    # latest mark). Scenarios call client.place_order from action callbacks
    # AFTER tick, so the engine has the current bar's mark.
    async def mid_source(symbol: str) -> float:
        mark = engine.account.last_mark.get(symbol)
        if mark is not None:
            return mark
        # Fallback: first bar's close.
        return bars[0].close

    return TopstepXSimClient(engine=engine, mid_price_source=mid_source)


def _intent_at(
    ts: datetime,
    *,
    side: str = "BUY",
    qty: int = 1,
    symbol: str = "MNQ",
    coid: str | None = None,
) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=qty,
        order_type="MARKET",
        client_order_id=coid or f"{side.lower()}-{ts.isoformat()}",
        timestamp=ts,
    )


# ---- Scenario builders ------------------------------------------------------

def combine_pass_50k() -> Scenario:
    """$50K Combine: buy 1 MNQ at 18_000, ride to 19_500 (= +$3K profit target).

    Stage transition combine_active → combine_passed is scripted at the end
    (the engine doesn't auto-promote on profit; the real Topstep does it via
    backend processing). Test scaffolding mirrors that contract.
    """
    closes = [18_000.0 + 5.0 * i for i in range(301)]  # 18_000 → 19_500
    bars = _bars(closes)
    eng = _make_engine()
    client = _make_client(eng, bars)

    async def open_on_first_bar(c: TopstepXSimClient, b: Bar) -> list[OrderEvent]:
        if b is bars[0]:
            ev = await c.place_order(_intent_at(b.timestamp, side="BUY"))
            return [ev]
        return []

    async def close_on_last_bar(c: TopstepXSimClient, b: Bar) -> list[OrderEvent]:
        if b is bars[-1]:
            ev = await c.place_order(_intent_at(b.timestamp, side="SELL", coid="close"))
            return [ev]
        return []

    return Scenario(
        name="combine_pass_50k",
        engine=eng,
        client=client,
        bars=bars,
        actions=[open_on_first_bar, close_on_last_bar],
        terminal_stage="combine_passed",
    )


def combine_fail_mll_50k() -> Scenario:
    """$50K Combine: buy 1 NQ at 18_000; price drops 410 pts → -$8_200 loss.

    NQ point value is $20; we need to drop equity from 50_000 to <= phantom_mll
    floor of 48_000. 1 NQ x ~100+ pts down = -$2_000+. Use a sharp drop so
    the phantom MLL is breached on a single bar's tick.
    """
    # Open at 18_000, plummet to 17_890 (110 pts down x $20/pt = $2_200 loss).
    closes = [18_000.0, 17_950.0, 17_890.0]
    bars = _bars(closes, symbol="NQ")
    eng = _make_engine()
    client = _make_client(eng, bars)

    async def open_on_first(c: TopstepXSimClient, b: Bar) -> list[OrderEvent]:
        if b is bars[0]:
            ev = await c.place_order(
                _intent_at(b.timestamp, side="BUY", symbol="NQ", coid="open"),
            )
            return [ev]
        return []

    return Scenario(
        name="combine_fail_mll_50k",
        engine=eng,
        client=client,
        bars=bars,
        actions=[open_on_first],
    )


def combine_fail_max_position() -> Scenario:
    """Strategy submits 51 MNQ → engine rejects (cap = 50)."""
    bars = _bars([18_000.0, 18_001.0])
    eng = _make_engine()
    client = _make_client(eng, bars)

    async def oversize(c: TopstepXSimClient, b: Bar) -> list[OrderEvent]:
        if b is bars[0]:
            ev = await c.place_order(
                _intent_at(b.timestamp, side="BUY", qty=51, coid="oversize"),
            )
            return [ev]
        return []

    return Scenario(
        name="combine_fail_max_position",
        engine=eng,
        client=client,
        bars=bars,
        actions=[oversize],
    )


def efa_payout_flow_50k() -> Scenario:
    """Start in efa_active; take a $1K profit; advance to efa_payout."""
    # 1 MNQ x 500 pts x $2/pt = $1_000 profit.
    closes = [18_000.0 + 5.0 * i for i in range(101)]
    bars = _bars(closes)
    eng = _make_engine(stage="efa_active")
    client = _make_client(eng, bars)

    async def open_on_first(c: TopstepXSimClient, b: Bar) -> list[OrderEvent]:
        if b is bars[0]:
            ev = await c.place_order(_intent_at(b.timestamp, side="BUY", coid="open"))
            return [ev]
        return []

    async def close_on_last(c: TopstepXSimClient, b: Bar) -> list[OrderEvent]:
        if b is bars[-1]:
            ev = await c.place_order(_intent_at(b.timestamp, side="SELL", coid="close"))
            return [ev]
        return []

    return Scenario(
        name="efa_payout_flow_50k",
        engine=eng,
        client=client,
        bars=bars,
        actions=[open_on_first, close_on_last],
        terminal_stage="efa_payout",
    )


def efa_consistency_breach() -> Scenario:
    """Produce a sequence of closed trades where best_day = 60% of total net."""
    # Day 1: +$600 (1 MNQ x 300 pts x $2/pt). Day 2: +$400 (200 pts).
    # best_day=600, net=1000 → 60% > 40% threshold → policy denies payout.
    base = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    day1 = _bars([18_000.0, 18_300.0], start=base)
    day2 = _bars(
        [18_300.0, 18_500.0],
        start=base + timedelta(days=1),
    )
    bars = day1 + day2
    eng = _make_engine(stage="efa_active")
    client = _make_client(eng, bars)

    async def day1_open(c: TopstepXSimClient, b: Bar) -> list[OrderEvent]:
        if b is day1[0]:
            return [await c.place_order(_intent_at(b.timestamp, side="BUY", coid="d1-o"))]
        return []

    async def day1_close(c: TopstepXSimClient, b: Bar) -> list[OrderEvent]:
        if b is day1[-1]:
            return [await c.place_order(_intent_at(b.timestamp, side="SELL", coid="d1-c"))]
        return []

    async def day2_open(c: TopstepXSimClient, b: Bar) -> list[OrderEvent]:
        if b is day2[0]:
            return [await c.place_order(_intent_at(b.timestamp, side="BUY", coid="d2-o"))]
        return []

    async def day2_close(c: TopstepXSimClient, b: Bar) -> list[OrderEvent]:
        if b is day2[-1]:
            return [await c.place_order(_intent_at(b.timestamp, side="SELL", coid="d2-c"))]
        return []

    return Scenario(
        name="efa_consistency_breach",
        engine=eng,
        client=client,
        bars=bars,
        actions=[day1_open, day1_close, day2_open, day2_close],
    )


def hard_flat_at_1510_ct() -> Scenario:
    """Strategy submits an opener at 15:11 CT → engine rejects HARD_FLAT_CLOCK.

    15:11 CT in May (CDT, UTC-5) = 20:11 UTC.
    """
    cutoff_plus_one = datetime(2026, 5, 22, 20, 11, tzinfo=UTC)
    bars = _bars([18_000.0, 18_001.0], start=cutoff_plus_one)
    eng = _make_engine(start_clock=cutoff_plus_one)
    client = _make_client(eng, bars)

    async def open_post_cutoff(c: TopstepXSimClient, b: Bar) -> list[OrderEvent]:
        if b is bars[0]:
            return [await c.place_order(_intent_at(b.timestamp, side="BUY", coid="late"))]
        return []

    return Scenario(
        name="hard_flat_at_1510_ct",
        engine=eng,
        client=client,
        bars=bars,
        actions=[open_post_cutoff],
    )


# ---- Driver -----------------------------------------------------------------

async def run_scenario(scenario: Scenario) -> ScenarioResult:
    """Walk the scenario's bars, marking-to-market + dispatching actions.

    Per-bar steps:
      1. Advance the engine clock to the bar's timestamp.
      2. tick() the engine with the bar's close.
      3. Invoke each action callback; collect any OrderEvents.
      4. Track per-day P&L for the consistency report.

    After the loop, apply `terminal_stage` if set (mirrors the real Topstep
    backend's once-per-day promotion).
    """
    all_events: list[OrderEvent] = []
    # day_key (UTC date) -> realized P&L delta on that day
    per_day_pnl: dict[object, float] = {}
    prev_realized = scenario.engine.account.realized_pnl

    for bar in scenario.bars:
        scenario.engine.set_now(bar.timestamp)
        acc = scenario.engine.tick(mid_price=bar.close, symbol=bar.symbol)
        if acc.stage in ("combine_failed", "efa_failed"):
            break

        for action in scenario.actions:
            events = await action(scenario.client, bar)
            all_events.extend(events)

        # Track per-day realized P&L delta after this bar's actions.
        day = bar.timestamp.date()
        delta = scenario.engine.account.realized_pnl - prev_realized
        per_day_pnl[day] = per_day_pnl.get(day, 0.0) + delta
        prev_realized = scenario.engine.account.realized_pnl

    if (
        scenario.terminal_stage is not None
        and scenario.engine.account.stage != scenario.terminal_stage
    ):
        scenario.engine.set_account(
            advance_stage(scenario.engine.account, scenario.terminal_stage),
        )

    best_day = max(per_day_pnl.values(), default=0.0)
    net = scenario.engine.account.realized_pnl
    return ScenarioResult(
        name=scenario.name,
        account=scenario.engine.account,
        events=all_events,
        best_day_pnl=best_day,
        net_pnl=net,
    )


# ---- Scenario registry ------------------------------------------------------

SCENARIOS: Final[dict[str, Callable[[], Scenario]]] = {
    "combine_pass_50k": combine_pass_50k,
    "combine_fail_mll_50k": combine_fail_mll_50k,
    "combine_fail_max_position": combine_fail_max_position,
    "efa_payout_flow_50k": efa_payout_flow_50k,
    "efa_consistency_breach": efa_consistency_breach,
    "hard_flat_at_1510_ct": hard_flat_at_1510_ct,
}
