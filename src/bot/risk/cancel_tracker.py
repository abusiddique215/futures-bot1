"""60-minute rolling cancel/fill ratio for rule 7 (HFT defensive cap).

Spec: 04 §3.2 rule 7. We self-impose 5.0/60-min by default since Topstep's
threshold is officially undefined.
"""
from __future__ import annotations

from datetime import datetime, timedelta


class RollingRatioTracker:
    """Stateful rolling tracker; pure functions on append + ratio."""

    def __init__(self, window_minutes: int) -> None:
        self._window = timedelta(minutes=window_minutes)
        self._cancels: list[datetime] = []
        self._fills: list[datetime] = []

    def record_cancel(self, ts: datetime) -> None:
        self._cancels.append(ts)

    def record_fill(self, ts: datetime) -> None:
        self._fills.append(ts)

    def ratio(self, now: datetime) -> float:
        cutoff = now - self._window
        # Prune old entries (idempotent)
        self._cancels = [t for t in self._cancels if t >= cutoff]
        self._fills = [t for t in self._fills if t >= cutoff]
        if not self._fills:
            return float("inf") if self._cancels else 0.0
        return len(self._cancels) / len(self._fills)
