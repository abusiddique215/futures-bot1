"""Parity test: TopstepXSimClient vs SimExecutionClient through TopstepRiskGate.

Same bars + same intents fed through the gate must produce the same approve /
deny decision sequence regardless of which broker sits downstream. This is the
load-bearing guarantee that makes the sim a credible Topstep substitute.

Why this works: AccountState comes from `AccountStateTracker`, which only sees
fills (not broker state). As long as both brokers accept the same intents,
the trackers stay in lock-step and the gate produces identical decisions.

We construct inputs so the sim engine never rejects:
- slippage_ticks=0 (fills exactly at bar.close)
- intent qty 1 (well under 50 MNQ cap)
- all timestamps before 15:10 CT
- small price moves so equity stays well above phantom MLL
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pytest

from bot.backtest.sim_client import SimExecutionClient
from bot.backtest.tracker import AccountStateTracker
from bot.execution.ports import ExecutionClient
from bot.execution.topstepx_sim.account import SimAccount
from bot.execution.topstepx_sim.client import TopstepXSimClient
from bot.execution.topstepx_sim.engine import TopstepSimEngine
from bot.observability.bus import NoopTelemetryBus
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.types import (
    ApprovedOrder,
    Bar,
    Bracket,
    OrderDenied,
    OrderIntent,
)


class _NoopNews:
    def in_window(self, now: datetime) -> bool:
        return False

    def max_position_during_window(self) -> int:
        return 1


def _bars() -> list[Bar]:
    """60 1-minute bars, small oscillation around 18_000. All pre-15:10 CT."""
    start = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)  # 09:30 CT
    closes: list[float] = []
    for i in range(60):
        # +/- $0.50 oscillation; well above MLL floor.
        offset = 0.25 if i % 2 == 0 else -0.25
        closes.append(18_000.0 + offset)
    return [
        Bar(
            symbol="MNQ",
            open=c, high=c, low=c, close=c,
            volume=100,
            timestamp=start + timedelta(minutes=i),
            interval="1m",
        )
        for i, c in enumerate(closes)
    ]


def _intents(bars: list[Bar]) -> dict[int, list[OrderIntent]]:
    """10 intents at fixed bar indices — 5 opens, 5 closes."""
    schedule: dict[int, list[OrderIntent]] = {}
    bracket = Bracket(stop_loss_ticks=20, take_profit_ticks=40)
    for n, i in enumerate([5, 10, 15, 20, 25]):
        schedule[i] = [OrderIntent(
            symbol="MNQ", side="BUY", quantity=1, order_type="MARKET",
            client_order_id=f"open-{n}", timestamp=bars[i].timestamp,
            bracket=bracket,
        )]
    for n, i in enumerate([6, 11, 16, 21, 26]):
        schedule[i] = [OrderIntent(
            symbol="MNQ", side="SELL", quantity=1, order_type="MARKET",
            client_order_id=f"close-{n}", timestamp=bars[i].timestamp,
        )]
    return schedule


def _make_gate(broker: ExecutionClient) -> TopstepRiskGate:
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000.0, 2_000.0, max_mini=5)
    return TopstepRiskGate(
        policy=policy,
        news_calendar=_NoopNews(),
        execution_client=broker,
        telemetry=NoopTelemetryBus(),
        config=cfg,
    )


def _decision_key(d: ApprovedOrder | OrderDenied) -> tuple[str, str]:
    """Stable comparison key: (approved/denied, rule or empty)."""
    if isinstance(d, ApprovedOrder):
        return ("approved", "")
    return ("denied", d.rule)


async def _collect_decisions(
    broker: ExecutionClient,
    bars: list[Bar],
    schedule: dict[int, list[OrderIntent]],
) -> list[ApprovedOrder | OrderDenied]:
    tracker = AccountStateTracker(start_balance=50_000.0, is_combine=True)
    gate = _make_gate(broker)
    out: list[ApprovedOrder | OrderDenied] = []
    for i, bar in enumerate(bars):
        tracker.mark_to_market(bar)
        state = tracker.snapshot(timestamp=bar.timestamp)
        state = gate.on_tick(state)
        for intent in schedule.get(i, []):
            decision = gate.approve_or_deny(intent, state)
            out.append(decision)
            if isinstance(decision, ApprovedOrder):
                await broker.place_order(decision.intent)
                tracker.record_fill(
                    symbol=decision.intent.symbol,
                    signed_qty=decision.intent.signed_qty(),
                    fill_price=bar.close,
                    ts=bar.timestamp,
                )
    return out


def _intents_iterable_count(schedule: dict[int, Iterable[OrderIntent]]) -> int:
    return sum(len(list(v)) for v in schedule.values())


async def test_decision_stream_matches_across_sim_and_topstepx_sim() -> None:
    bars = _bars()
    schedule = _intents(bars)
    assert _intents_iterable_count(schedule) == 10  # sanity

    sim = SimExecutionClient()
    await sim.connect()
    sim_decisions = await _collect_decisions(sim, bars, schedule)

    # Build a TopstepXSimClient whose mid source matches bar.close exactly.
    bar_index_holder = {"i": 0}

    async def mid_source(symbol: str) -> float:
        return bars[bar_index_holder["i"]].close

    engine = TopstepSimEngine(
        account=SimAccount.new(start_balance=50_000.0, mll_amount=2_000.0),
        combine_policy=CombineIntradayDrawdown(50_000.0, 2_000.0, max_mini=5),
        efa_policy=None,
        slippage_ticks=0,
        now=lambda: bars[bar_index_holder["i"]].timestamp,
    )
    topstepx_sim = TopstepXSimClient(engine=engine, mid_price_source=mid_source)
    await topstepx_sim.connect()

    # Run the second collection with the bar-index cursor advancing per bar so
    # mid_source returns the right close. _collect_decisions doesn't expose the
    # cursor, so we wrap the broker to bump the cursor before each place_order.
    class _CursorBroker:
        def __init__(self, inner: TopstepXSimClient, bars: list[Bar]) -> None:
            self._inner = inner
            self._bars = bars

        async def connect(self) -> None:
            await self._inner.connect()

        async def disconnect(self) -> None:
            await self._inner.disconnect()

        async def place_order(self, intent: OrderIntent):  # type: ignore[no-untyped-def]
            # Advance the cursor to the bar whose timestamp == intent.timestamp.
            for idx, b in enumerate(self._bars):
                if b.timestamp == intent.timestamp:
                    bar_index_holder["i"] = idx
                    engine.set_now(b.timestamp)
                    engine.tick(mid_price=b.close, symbol=b.symbol)
                    break
            return await self._inner.place_order(intent)

        async def cancel_order(self, client_order_id: str):  # type: ignore[no-untyped-def]
            return await self._inner.cancel_order(client_order_id)

        async def cancel_all(self, symbol: str):  # type: ignore[no-untyped-def]
            return await self._inner.cancel_all(symbol)

        async def get_positions(self):  # type: ignore[no-untyped-def]
            return await self._inner.get_positions()

        async def get_open_orders(self):  # type: ignore[no-untyped-def]
            return await self._inner.get_open_orders()

        async def get_account(self):  # type: ignore[no-untyped-def]
            return await self._inner.get_account()

    topstepx_decisions = await _collect_decisions(
        _CursorBroker(topstepx_sim, bars), bars, schedule,
    )

    assert len(sim_decisions) == len(topstepx_decisions) == 10
    assert [_decision_key(d) for d in sim_decisions] == [
        _decision_key(d) for d in topstepx_decisions
    ]


async def test_topstepx_sim_broker_actually_filled_each_approval() -> None:
    """Sanity: confirm the parity path actually exercised the engine —
    every approved decision corresponds to a FILLED event from the engine.
    Without this, parity could trivially pass by both brokers being no-ops."""
    bars = _bars()
    schedule = _intents(bars)

    engine = TopstepSimEngine(
        account=SimAccount.new(start_balance=50_000.0, mll_amount=2_000.0),
        combine_policy=CombineIntradayDrawdown(50_000.0, 2_000.0, max_mini=5),
        efa_policy=None,
        slippage_ticks=0,
        now=lambda: bars[0].timestamp,
    )

    async def mid_for_intent(symbol: str) -> float:
        return engine.account.last_mark.get(symbol, bars[0].close)

    client = TopstepXSimClient(engine=engine, mid_price_source=mid_for_intent)

    approved_count = 0
    filled_count = 0
    tracker = AccountStateTracker(start_balance=50_000.0, is_combine=True)
    gate = _make_gate(client)
    for i, bar in enumerate(bars):
        engine.set_now(bar.timestamp)
        engine.tick(mid_price=bar.close, symbol=bar.symbol)
        tracker.mark_to_market(bar)
        state = tracker.snapshot(timestamp=bar.timestamp)
        state = gate.on_tick(state)
        for intent in schedule.get(i, []):
            decision = gate.approve_or_deny(intent, state)
            if isinstance(decision, ApprovedOrder):
                approved_count += 1
                ev = await client.place_order(decision.intent)
                if ev.status == "FILLED":
                    filled_count += 1
                tracker.record_fill(
                    symbol=decision.intent.symbol,
                    signed_qty=decision.intent.signed_qty(),
                    fill_price=bar.close,
                    ts=bar.timestamp,
                )
    assert approved_count > 0
    assert filled_count == approved_count


@pytest.mark.parametrize("seed_iter", [0])
async def test_parity_decision_count_is_stable(seed_iter: int) -> None:
    """Re-running the parity collection twice yields the same decision count.
    Catches accidental shared state between runs."""
    bars = _bars()
    schedule = _intents(bars)
    sim_a = SimExecutionClient()
    await sim_a.connect()
    sim_b = SimExecutionClient()
    await sim_b.connect()
    a = await _collect_decisions(sim_a, bars, schedule)
    b = await _collect_decisions(sim_b, bars, schedule)
    assert [_decision_key(x) for x in a] == [_decision_key(x) for x in b]
