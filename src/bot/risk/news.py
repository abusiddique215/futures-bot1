"""News calendar — high-impact event windows for rule 5.

Spec: 04 §3.8. v1 uses a YAML file maintained manually. v2 candidates
(Trading Economics, FRED ICS) are parked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml


@dataclass(frozen=True)
class NewsEvent:
    time: datetime       # tz-aware
    name: str
    impact: str          # "high" | "medium" | "low"


@runtime_checkable
class NewsCalendar(Protocol):
    def in_window(self, now: datetime) -> bool: ...
    def max_position_during_window(self) -> int: ...


class YAMLNewsCalendar:
    """Loads events from a YAML file. v1 implementation."""

    def __init__(self, path: Path) -> None:
        data = yaml.safe_load(path.read_text())
        self._events: list[NewsEvent] = []
        for raw in data.get("events", []):
            t = raw["time"]
            if isinstance(t, str):
                t = datetime.fromisoformat(t)
            if t.tzinfo is None:
                raise ValueError(f"NewsEvent {raw['name']!r}: time must be tz-aware")
            self._events.append(NewsEvent(time=t, name=raw["name"], impact=raw["impact"]))
        self._before = timedelta(minutes=int(data.get("window_minutes_before", 5)))
        self._after = timedelta(minutes=int(data.get("window_minutes_after", 15)))
        self._cap = int(data.get("max_position_during_window", 1))

    def in_window(self, now: datetime) -> bool:
        return any(
            (e.time - self._before) <= now <= (e.time + self._after)
            for e in self._events
            if e.impact == "high"
        )

    def max_position_during_window(self) -> int:
        return self._cap
