"""DataQualityMonitor tests. Spec 01-data-pipeline.md §3.7."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bot.types import Bar


def _bar(t: datetime, **kw) -> Bar:
    defaults = {
        "symbol": "MNQ",
        "open": 100.0,
        "high": 101.0,
        "low": 99.5,
        "close": 100.5,
        "volume": 10,
        "timestamp": t,
        "interval": "1m",
    }
    defaults.update(kw)
    return Bar(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def t0() -> datetime:
    return datetime(2026, 5, 22, 14, 30, 0, tzinfo=UTC)


def test_dq_clean_bars_no_issues(t0) -> None:
    from bot.data.dq import DataQualityMonitor
    m = DataQualityMonitor(interval="1m")
    issues_a = m.check_bar(prev=None, new=_bar(t0))
    issues_b = m.check_bar(prev=_bar(t0), new=_bar(t0 + timedelta(minutes=1)))
    assert issues_a == []
    assert issues_b == []


def test_dq_detects_gap(t0) -> None:
    """Prev at t0; new at t0+5min when interval is 1m → gap of 4 missing bars."""
    from bot.data.dq import DataQualityMonitor
    m = DataQualityMonitor(interval="1m")
    prev = _bar(t0)
    new = _bar(t0 + timedelta(minutes=5))
    issues = m.check_bar(prev=prev, new=new)
    reasons = [i.reason for i in issues]
    assert "BAR_GAP" in reasons


def test_dq_detects_out_of_order(t0) -> None:
    """new.timestamp <= prev.timestamp is corrupt."""
    from bot.data.dq import DataQualityMonitor
    m = DataQualityMonitor(interval="1m")
    prev = _bar(t0 + timedelta(minutes=5))
    new = _bar(t0)  # earlier than prev
    issues = m.check_bar(prev=prev, new=new)
    reasons = [i.reason for i in issues]
    assert "OUT_OF_ORDER" in reasons


def test_dq_detects_weekend(t0) -> None:
    """Saturday 14:00 UTC is a weekend bar (Globex closed weekend daytime)."""
    from bot.data.dq import DataQualityMonitor
    m = DataQualityMonitor(interval="1m")
    sat = datetime(2026, 5, 23, 14, 0, 0, tzinfo=UTC)  # Saturday
    issues = m.check_bar(prev=None, new=_bar(sat))
    reasons = [i.reason for i in issues]
    assert "WEEKEND" in reasons


def test_dq_detects_stale_repeat(t0) -> None:
    """3 consecutive bars with identical close + volume → stale feed."""
    from bot.data.dq import DataQualityMonitor
    m = DataQualityMonitor(interval="1m")
    same = {"close": 100.0, "volume": 5}
    b1 = _bar(t0, **same)
    b2 = _bar(t0 + timedelta(minutes=1), **same)
    b3 = _bar(t0 + timedelta(minutes=2), **same)
    m.check_bar(prev=None, new=b1)
    m.check_bar(prev=b1, new=b2)
    issues = m.check_bar(prev=b2, new=b3)
    reasons = [i.reason for i in issues]
    assert "STALE_REPEAT" in reasons


def test_dq_issue_carries_bar_ref(t0) -> None:
    """Issues hold a pointer to the offending bar for downstream logging."""
    from bot.data.dq import DataQualityMonitor
    m = DataQualityMonitor(interval="1m")
    sat = _bar(datetime(2026, 5, 23, 14, 0, 0, tzinfo=UTC))
    issues = m.check_bar(prev=None, new=sat)
    assert issues[0].bar is sat
