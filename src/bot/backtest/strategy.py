"""Strategy Protocol + PlaceholderStrategy (no signals, used for harness tests).

Lifecycle hooks (Plan 21 + 22):
  - `setup()` is optional — strategies that need a background pump (e.g.
    SignalStrategy → Discord) implement it and FleetRuntime calls it via
    `hasattr` BEFORE the LiveTradingLoop starts.
  - `teardown()` is optional — symmetric to setup. FleetRuntime calls it
    via `hasattr` AFTER the LiveTradingLoop completes (normal or exceptional)
    so strategies can clean up their resources. Failures are logged and
    swallowed — a misbehaving teardown does NOT crash the fleet.

Strategies that only implement `on_bar` (the Plan 11 baseline) are unaffected;
hasattr() returns False and the runtime moves on.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from bot.types import AccountState, Bar, OrderIntent


@runtime_checkable
class Strategy(Protocol):
    """Backtest + live shared interface. on_bar(bar, state) -> intent stream."""

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]: ...


class PlaceholderStrategy:
    """Emits no intents. Used by harness tests + smoke runs."""

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        return []
