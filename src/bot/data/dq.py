"""DataQualityMonitor — detects anomalies in incoming Bar streams.

Spec: 01-data-pipeline.md §3.7. Issues are FLAGGED for downstream logging /
quarantine; this module does NOT decide whether to drop. The driver
(historical-load or live-feed) consults the issues and chooses policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from bot.types import Bar

DQReason = Literal[
    "BAR_GAP",
    "OUT_OF_ORDER",
    "WEEKEND",
    "STALE_REPEAT",
    "OHLC_INCONSISTENT",
]


@dataclass(frozen=True)
class DQIssue:
    """A single data-quality issue. Immutable for journaling."""
    reason: DQReason
    bar: Bar
    detail: str


_INTERVAL_TO_DELTA: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
}


class DataQualityMonitor:
    """Stateful monitor that emits DQIssues on a per-bar basis.

    State tracked: last 2 (close, volume) tuples for STALE_REPEAT detection.
    """

    def __init__(self, interval: str) -> None:
        if interval not in _INTERVAL_TO_DELTA:
            raise ValueError(f"Unsupported interval: {interval!r}")
        self._interval = interval
        self._delta = _INTERVAL_TO_DELTA[interval]
        self._recent_close_vol: list[tuple[float, int]] = []

    def check_bar(self, prev: Bar | None, new: Bar) -> list[DQIssue]:
        issues: list[DQIssue] = []

        # Weekend
        if new.timestamp.weekday() in (5, 6):
            issues.append(DQIssue("WEEKEND", new, f"Bar on weekday {new.timestamp.weekday()}"))

        # OHLC consistency
        if not (new.low <= new.open <= new.high and
                new.low <= new.close <= new.high and
                new.low <= new.high):
            issues.append(DQIssue(
                "OHLC_INCONSISTENT", new,
                f"OHLC: O={new.open} H={new.high} L={new.low} C={new.close}",
            ))

        if prev is not None:
            # Out-of-order
            if new.timestamp <= prev.timestamp:
                issues.append(DQIssue(
                    "OUT_OF_ORDER", new,
                    f"new.timestamp={new.timestamp} <= prev.timestamp={prev.timestamp}",
                ))
            else:
                # Gap detection
                expected = prev.timestamp + self._delta
                if new.timestamp != expected:
                    missing = (new.timestamp - expected) // self._delta
                    issues.append(DQIssue(
                        "BAR_GAP", new,
                        f"Expected {expected}, got {new.timestamp}; ~{missing} missing bars",
                    ))

        # Stale repeat: 3 consecutive identical (close, volume)
        self._recent_close_vol.append((new.close, new.volume))
        if len(self._recent_close_vol) > 3:
            self._recent_close_vol.pop(0)
        if (len(self._recent_close_vol) == 3 and
                self._recent_close_vol[0] == self._recent_close_vol[1] == self._recent_close_vol[2]):
            issues.append(DQIssue(
                "STALE_REPEAT", new,
                f"3 consecutive bars with close={new.close}, volume={new.volume}",
            ))

        return issues
