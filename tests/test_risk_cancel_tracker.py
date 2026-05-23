"""RollingRatioTracker (60-min rolling cancel/fill ratio). Spec 04 §3.2 rule 7."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def test_empty_tracker_ratio_is_zero() -> None:
    from bot.risk.cancel_tracker import RollingRatioTracker
    t = RollingRatioTracker(window_minutes=60)
    assert t.ratio(now=datetime(2026, 5, 22, 14, 0, tzinfo=UTC)) == 0.0


def test_one_fill_zero_cancels_ratio_is_zero() -> None:
    from bot.risk.cancel_tracker import RollingRatioTracker
    t = RollingRatioTracker(window_minutes=60)
    now = datetime(2026, 5, 22, 14, 0, tzinfo=UTC)
    t.record_fill(now)
    assert t.ratio(now=now) == 0.0


def test_three_cancels_one_fill_ratio_is_three() -> None:
    from bot.risk.cancel_tracker import RollingRatioTracker
    t = RollingRatioTracker(window_minutes=60)
    now = datetime(2026, 5, 22, 14, 0, tzinfo=UTC)
    t.record_cancel(now)
    t.record_cancel(now)
    t.record_cancel(now)
    t.record_fill(now)
    assert t.ratio(now=now) == pytest.approx(3.0)


def test_zero_fills_one_cancel_returns_infinity_sentinel() -> None:
    """No fills = degenerate; return a large value so rule 7 will trip."""
    from bot.risk.cancel_tracker import RollingRatioTracker
    t = RollingRatioTracker(window_minutes=60)
    now = datetime(2026, 5, 22, 14, 0, tzinfo=UTC)
    t.record_cancel(now)
    assert t.ratio(now=now) == float("inf")


def test_events_outside_window_drop() -> None:
    """Events older than window_minutes are excluded."""
    from bot.risk.cancel_tracker import RollingRatioTracker
    t = RollingRatioTracker(window_minutes=60)
    now = datetime(2026, 5, 22, 14, 0, tzinfo=UTC)
    old = now - timedelta(minutes=120)
    t.record_cancel(old)  # outside window
    t.record_cancel(old)  # outside window
    t.record_fill(now)
    assert t.ratio(now=now) == 0.0
