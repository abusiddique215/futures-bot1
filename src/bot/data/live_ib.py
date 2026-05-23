"""IBLiveBarStream — live MNQ bars from Interactive Brokers.

PLAN 2: SKELETON ONLY. The constructor + class shape land here; Plan 6 (IB Paper)
adds the real ib_async.IB().connectAsync() + reconnect machinery, the 5-sec
real-time bar subscription, the per-tick BarAggregator wiring, and the 30s
disconnect → force-flatten handoff to 04-risk-engine.

Spec: 01-data-pipeline.md §3.3.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from bot.types import Bar


class IBLiveBarStream:
    """Skeleton interface. Plan 6 implements the body."""

    def __init__(self, host: str, port: int, client_id: int) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id

    async def connect(self) -> None:
        """Establish ib_async connection. Implemented in Plan 6."""
        raise NotImplementedError(
            "IBLiveBarStream.connect is implemented in Plan 6 (IB Paper Execution). "
            "Plan 2 ships only the class shape so the conformance test can target it."
        )

    async def subscribe(self, symbol: str, interval: str) -> AsyncIterator[Bar]:
        """Yield aggregated Bars. Implemented in Plan 6."""
        msg = (
            "IBLiveBarStream.subscribe is implemented in Plan 6. "
            "Yields Bars from a 5-sec IB feed via local BarAggregator."
        )
        raise NotImplementedError(msg)
        # Unreachable yield for type checking (never executed).
        yield  # type: ignore[unreachable]
