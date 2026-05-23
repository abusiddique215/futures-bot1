"""Strategy Protocol + PlaceholderStrategy (no signals, used for harness tests)."""
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
