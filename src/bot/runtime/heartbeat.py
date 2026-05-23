"""Heartbeat writer — proves the loop is alive to external monitors.

`launchd` (Plan 9) and any external monitor reads the mtime / contents of the
heartbeat file to detect a stalled bot. The file is written via tmp + atomic
rename so a crash mid-write can never leave a partial-truncate that a reader
might mistake for valid content.

Cadence is the LiveTradingLoop's concern, not Heartbeat's — write_now() is
a single-shot side effect; the loop calls it once per bar (T3 wiring) and
gates by elapsed time using `should_write_at(ts)`.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

# 30s cadence per Plan 10 spec.
_DEFAULT_MIN_INTERVAL: Final[timedelta] = timedelta(seconds=30)


class Heartbeat:
    """Atomic-rename heartbeat file writer.

    `write_now(ts)` is unconditional; cadence-gating happens in
    `should_write_at(ts)` so the loop can do:

        if hb.should_write_at(bar.timestamp):
            hb.write_now(bar.timestamp)
    """

    def __init__(
        self, path: Path, *, min_interval: timedelta = _DEFAULT_MIN_INTERVAL,
    ) -> None:
        self._path = path
        self._tmp = path.with_name(path.name + ".tmp")
        self._min_interval = min_interval
        self._last_write_ts: datetime | None = None

    def should_write_at(self, ts: datetime) -> bool:
        """True iff `ts` is at least `min_interval` past the last successful
        write (or no write has happened yet)."""
        if self._last_write_ts is None:
            return True
        return (ts - self._last_write_ts) >= self._min_interval

    def write_now(self, ts: datetime) -> None:
        """Write `ts.isoformat()` to the heartbeat path via tmp + atomic rename.

        Creates the parent directory if it doesn't exist.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._tmp.write_text(ts.isoformat(), encoding="utf-8")
        # os.replace is atomic on POSIX and on NTFS; required so a reader
        # never sees a partial truncate.
        os.replace(self._tmp, self._path)
        self._last_write_ts = ts
