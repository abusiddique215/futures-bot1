"""IBExecutionClient — Interactive Brokers paper-trading adapter via ib_async.

Implements the ExecutionClient Protocol. Connects to IB Gateway on
localhost:7497 (paper) and resolves MNQ front-month contracts on demand.

Dependency injection: tests pass `ib_factory=lambda: FakeIB()` to swap out
the real `ib_async.IB` for an in-memory fake. No CI test touches the
network — the real broker only runs in nightly @pytest.mark.live_paper
fixtures (deferred).

Spec: 02-execution-clients.md §3.3 (reconnect), §3.5 (bracket-translation),
§3.8 (idempotency cache), §3.9 (conformance contract).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from bot.types import OrderEvent

if TYPE_CHECKING:
    from ib_async import IB, Contract


def _default_ib_factory() -> IB:
    """Lazy import so importing this module doesn't require ib_async at parse time."""
    from ib_async import IB
    return IB()


class IBExecutionClient:
    """ExecutionClient backed by ib_async against IB Gateway (paper).

    Constructor takes connection parameters and (optionally) an ib_factory
    callable that returns an IB-shaped object. Tests pass a fake-IB factory;
    production lets the default ib_async.IB() be used.
    """

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        ib_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self._ib_factory: Callable[[], Any] = ib_factory or _default_ib_factory
        self._ib: Any | None = None
        self._contracts: dict[str, Contract] = {}
        self._recent: dict[str, OrderEvent] = {}
