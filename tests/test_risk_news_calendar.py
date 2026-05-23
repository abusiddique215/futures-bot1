"""YAMLNewsCalendar tests. Spec 04 §3.8."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_news_calendar_loads_events() -> None:
    from bot.risk.news import YAMLNewsCalendar
    cal = YAMLNewsCalendar(path=_FIXTURES / "news_calendar_sample.yml")
    assert cal.max_position_during_window() == 1


def test_news_calendar_in_window_at_event() -> None:
    from bot.risk.news import YAMLNewsCalendar
    cal = YAMLNewsCalendar(path=_FIXTURES / "news_calendar_sample.yml")
    # CPI is 2026-06-12 08:30 CT = 2026-06-12 13:30 UTC
    cpi_utc = datetime(2026, 6, 12, 13, 30, tzinfo=UTC)
    assert cal.in_window(cpi_utc)
    assert cal.in_window(cpi_utc - timedelta(minutes=3))   # within T-5
    assert cal.in_window(cpi_utc + timedelta(minutes=10))  # within T+15


def test_news_calendar_out_of_window_far_before() -> None:
    from bot.risk.news import YAMLNewsCalendar
    cal = YAMLNewsCalendar(path=_FIXTURES / "news_calendar_sample.yml")
    cpi_utc = datetime(2026, 6, 12, 13, 30, tzinfo=UTC)
    assert not cal.in_window(cpi_utc - timedelta(minutes=10))   # before T-5
    assert not cal.in_window(cpi_utc + timedelta(minutes=20))   # after T+15


def test_news_calendar_low_impact_events_ignored() -> None:
    """Only high-impact events trigger windows."""
    from bot.risk.news import YAMLNewsCalendar
    cal = YAMLNewsCalendar(path=_FIXTURES / "news_calendar_sample.yml")
    low_utc = datetime(2026, 7, 4, 15, 0, tzinfo=UTC)  # 10:00 ET = 15:00 UTC
    assert not cal.in_window(low_utc)
