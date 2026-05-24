"""Schedule Protocol + AlwaysOn / MarketHours / CustomWindows.

Per-bot schedules let the fleet run a 24/7 maintenance bot alongside a
RTH-only ORB bot alongside a Gold bot with a handful of session windows.
LiveTradingLoop consults `schedule.should_trade(bar.timestamp)` per bar
before pumping intents through the gate (mark-to-market still runs).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, tzinfo
from typing import Final, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

_CT: Final[ZoneInfo] = ZoneInfo("America/Chicago")


@runtime_checkable
class Schedule(Protocol):
    """Per-bot trading window. Pure function of `now`; no state."""

    def should_trade(self, now: datetime) -> bool: ...


@dataclass(frozen=True)
class AlwaysOn:
    """24/7 schedule. Used for maintenance bots that never sit out."""

    def should_trade(self, now: datetime) -> bool:
        _ = now
        return True


@dataclass(frozen=True)
class MarketHours:
    """[open, close] in Central Time (Topstep's reference zone).

    Endpoints are inclusive — a bar exactly at `close_ct` still trades.
    """

    open_ct: time = time(8, 30)
    close_ct: time = time(15, 10)

    def should_trade(self, now: datetime) -> bool:
        local = now.astimezone(_CT).time()
        return self.open_ct <= local <= self.close_ct


@dataclass(frozen=True)
class CustomWindows:
    """List of [start, end] windows in a caller-supplied tz.

    Used for bots with multiple intraday sessions (e.g. Gold's seven
    windows around London/NY overlap pockets).
    """

    windows: list[tuple[time, time]] = field(default_factory=list)
    tz: tzinfo = _CT

    def should_trade(self, now: datetime) -> bool:
        local = now.astimezone(self.tz).time()
        return any(start <= local <= end for start, end in self.windows)
