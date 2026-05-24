"""SignalEvent + SignalSource Protocol.

A `SignalSource` is anything that asynchronously yields `SignalEvent`s. Two
concrete implementations ship in this package:

- `FixtureSignalSource` — replays a list of pre-built events; for tests +
  the runtime `--check` smoke path.
- `DiscordSignalSource` — subscribes to one or more Discord channels via
  discord.py; parses each posted message via `parse_signal_message`.

Signal message format (the canonical shape `parse_signal_message` aims for):

    BUY NQ @20100 SL=20070 TP=20160
    LONG MNQH26 limit 20100 stop 20070 target 20160
    SHORT 1 NQ at 20100 stop 20130 tp 20040
    🟢 BUY NQ @20100 SL=20070 TP=20160          # emoji prefixes ignored

Tolerant: `parse_signal_message` returns None on unparseable input.
Downstream the SignalStrategy logs and drops those events.

`source_id` lets the downstream journal trace an OrderIntent back to the
original message (Plan 21 dashboard provenance). Discord populates it with
the message ID; FixtureSignalSource lets the test author choose.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

SignalSide = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class SignalEvent:
    """One parsed trade idea from an external source.

    Fields:
      received_at: tz-aware UTC timestamp the source observed the message
      symbol:      market symbol (e.g. "NQ", "MNQH26") — already normalised
      side:        BUY or SELL
      qty:         requested quantity (BEFORE risk-gate cap; gate may deny)
      limit_price: optional limit; None → strategy emits MARKET
      stop_loss:   optional absolute stop price; None → no bracket stop
      take_profit: optional absolute TP price; None → no bracket TP
      raw_text:    the original message text (for journal provenance)
      source_id:   stable id from the source (e.g. Discord message id)
    """

    received_at: datetime
    symbol: str
    side: SignalSide
    qty: int
    limit_price: float | None
    stop_loss: float | None
    take_profit: float | None
    raw_text: str
    source_id: str

    def __post_init__(self) -> None:
        if self.received_at.tzinfo is None:
            raise TypeError("SignalEvent.received_at must be timezone-aware")


@runtime_checkable
class SignalSource(Protocol):
    """Async iterator of `SignalEvent`s.

    Implementations are expected to be cancellable: when the consumer
    stops iterating (e.g. SIGTERM), the source should drop pending state
    and exit cleanly.
    """

    def iter_signals(self) -> AsyncIterator[SignalEvent]: ...
