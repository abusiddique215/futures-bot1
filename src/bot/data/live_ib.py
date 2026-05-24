"""IBLiveBarStream — live MNQ bars from Interactive Brokers via ib_async.

Plan 2 shipped only the class shape. Plan 6 fills in the body:
- connect() opens an ib_async.IB() session and qualifies the MNQ contract
- subscribe() registers a barUpdateEvent handler, converts each 5-sec
  RealTimeBar to a synthetic Tick, feeds the local BarAggregator, and
  yields closed 1m/5m Bar instances

Each RealTimeBar collapses to a single Tick (price=close, size=volume).
Sub-5-sec OHLC is not preserved; that's irrelevant for the 1m / 5m bars
the strategy consumes.

Spec: 01-data-pipeline.md §3.3.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from bot.data.aggregator import BarAggregator
from bot.markets.registry import get_market
from bot.types import Bar, Tick

if TYPE_CHECKING:
    from ib_async import IB
    from ib_async.contract import Future


def _default_ib_factory() -> IB:
    """Lazy import so module import doesn't require ib_async at parse time."""
    from ib_async import IB
    return IB()


def build_contract(symbol: str) -> Future:
    """Construct an `ib_async.Future` from a registered MarketSpec.

    Plan 14: replaces the hardcoded `Future("MNQ", exchange="CME")` so any
    market in `bot.markets.registry.MARKETS` (NQ/MNQ/GC/MGC/ES/MES today)
    builds the right IB contract. KeyError propagates on unknown symbols.
    """
    from ib_async import Future
    market = get_market(symbol)
    return Future(
        symbol=market.root,
        exchange=market.exchange,
        currency=market.ib_currency,
    )


class IBLiveBarStream:
    """Live bar feed backed by ib_async.

    Constructor takes the IB Gateway connection parameters and (optionally)
    an `ib_factory` callable for tests to inject a FakeIB.
    """

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        ib_factory: Callable[[], Any] | None = None,
        symbol: str = "MNQ",
    ) -> None:
        """`symbol` defaults to "MNQ" for back-compat with pre-Plan-14 callers;
        pass any registered root (NQ/MNQ/GC/MGC/ES/MES) for multi-market use.
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.symbol = symbol
        self._ib_factory: Callable[[], Any] = ib_factory or _default_ib_factory
        self._ib: Any | None = None
        self._contract: Any | None = None

    async def connect(self) -> None:
        """Open the IB session and qualify the front-month contract for `self.symbol`."""
        self._ib = self._ib_factory()
        await self._ib.connectAsync(self.host, self.port, self.client_id)
        contract = build_contract(self.symbol)
        qualified = await self._ib.qualifyContractsAsync(contract)
        self._contract = qualified[0]

    async def subscribe(self, symbol: str, interval: str) -> AsyncIterator[Bar]:
        """Yield aggregated `Bar` instances as 5-sec RealTimeBars arrive.

        The 5-sec feed is hooked via ib.barUpdateEvent. Each new RealTimeBar
        is collapsed to a single Tick (price=close, size=volume,
        timestamp=bar.time) and fed to a local BarAggregator. Whenever the
        aggregator closes a bar, it's pushed onto the queue this generator
        drains.
        """
        if self._ib is None or self._contract is None:
            raise RuntimeError(
                "IBLiveBarStream.subscribe() requires connect() first"
            )
        ib = self._ib
        ib.reqRealTimeBars(self._contract, 5, "TRADES", False)

        aggregator = BarAggregator(interval=interval, symbol=symbol)
        queue: asyncio.Queue[Bar] = asyncio.Queue()
        seen_indexes = 0  # how many of the bar-list we've already consumed

        def on_bar_update(bars: list[Any], _has_new_bar: bool) -> None:
            nonlocal seen_indexes
            # Only consume bars we haven't seen yet (ib_async re-emits the
            # whole list on every update).
            new_slice = bars[seen_indexes:]
            seen_indexes = len(bars)
            for rtb in new_slice:
                tick = Tick(
                    symbol=symbol,
                    price=float(rtb.close),
                    size=int(rtb.volume),
                    timestamp=rtb.time,
                )
                closed = aggregator.feed(tick)
                if closed is not None:
                    queue.put_nowait(closed)

        ib.barUpdateEvent += on_bar_update
        try:
            while True:
                bar = await queue.get()
                yield bar
        finally:
            ib.barUpdateEvent -= on_bar_update
