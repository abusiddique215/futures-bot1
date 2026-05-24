"""Schedule Protocol + AlwaysOn / MarketHours / CustomWindows."""
from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from bot.runtime.fleet.schedule import AlwaysOn, CustomWindows, MarketHours, Schedule

_CT = ZoneInfo("America/Chicago")


def test_always_on_is_a_schedule() -> None:
    assert isinstance(AlwaysOn(), Schedule)


def test_always_on_true_at_3am_and_9pm_utc() -> None:
    sch = AlwaysOn()
    assert sch.should_trade(datetime(2026, 5, 22, 3, 0, tzinfo=UTC))
    assert sch.should_trade(datetime(2026, 5, 22, 21, 0, tzinfo=UTC))


def test_market_hours_true_inside_window() -> None:
    sch = MarketHours()  # defaults 08:30 -> 15:10 CT
    # 14:00 CT == 19:00 UTC during CDT (May)
    inside = datetime(2026, 5, 22, 19, 0, tzinfo=UTC)
    assert sch.should_trade(inside)


def test_market_hours_false_after_close() -> None:
    sch = MarketHours()
    # 16:00 CT == 21:00 UTC during CDT
    after = datetime(2026, 5, 22, 21, 0, tzinfo=UTC)
    assert not sch.should_trade(after)


def test_market_hours_false_before_open() -> None:
    sch = MarketHours()
    # 03:00 CT == 08:00 UTC during CDT
    before = datetime(2026, 5, 22, 8, 0, tzinfo=UTC)
    assert not sch.should_trade(before)


def test_market_hours_inclusive_at_open() -> None:
    sch = MarketHours(open_ct=time(8, 30), close_ct=time(15, 10))
    # 08:30 CT == 13:30 UTC during CDT
    at_open = datetime(2026, 5, 22, 13, 30, tzinfo=UTC)
    assert sch.should_trade(at_open)


def test_custom_windows_two_sessions() -> None:
    sch = CustomWindows(
        windows=[(time(8, 30), time(11, 30)), (time(13, 30), time(15, 0))],
        tz=_CT,
    )
    # 09:00 CT inside first window
    ts_in_first = datetime(2026, 5, 22, 14, 0, tzinfo=UTC)
    assert sch.should_trade(ts_in_first)
    # 12:00 CT outside both
    ts_gap = datetime(2026, 5, 22, 17, 0, tzinfo=UTC)
    assert not sch.should_trade(ts_gap)
    # 14:30 CT inside second window
    ts_in_second = datetime(2026, 5, 22, 19, 30, tzinfo=UTC)
    assert sch.should_trade(ts_in_second)


def test_custom_windows_empty_returns_false() -> None:
    sch = CustomWindows(windows=[], tz=_CT)
    assert not sch.should_trade(datetime(2026, 5, 22, 14, 0, tzinfo=UTC))


# ---- Overnight-spanning windows (Gold Bot's 23:00-01:30 Asian session) ------


def test_custom_windows_overnight_inside_before_midnight() -> None:
    """A window 23:00-01:30 ET trades at 23:30 ET (= 03:30 UTC during EDT)."""
    et = ZoneInfo("America/New_York")
    sch = CustomWindows(windows=[(time(23, 0), time(1, 30))], tz=et)
    # 2026-05-22 23:30 EDT = 2026-05-23 03:30 UTC
    ts = datetime(2026, 5, 23, 3, 30, tzinfo=UTC)
    assert sch.should_trade(ts)


def test_custom_windows_overnight_inside_after_midnight() -> None:
    """A window 23:00-01:30 ET trades at 00:15 ET — the load-bearing case."""
    et = ZoneInfo("America/New_York")
    sch = CustomWindows(windows=[(time(23, 0), time(1, 30))], tz=et)
    # 2026-05-23 00:15 EDT = 2026-05-23 04:15 UTC
    ts = datetime(2026, 5, 23, 4, 15, tzinfo=UTC)
    assert sch.should_trade(ts)


def test_custom_windows_overnight_false_in_dead_zone() -> None:
    """The same window does NOT trade at 02:00 ET (after end)."""
    et = ZoneInfo("America/New_York")
    sch = CustomWindows(windows=[(time(23, 0), time(1, 30))], tz=et)
    # 2026-05-23 02:00 EDT = 2026-05-23 06:00 UTC
    ts = datetime(2026, 5, 23, 6, 0, tzinfo=UTC)
    assert not sch.should_trade(ts)


def test_custom_windows_overnight_false_pre_window() -> None:
    """The same window does NOT trade at 22:00 ET (before start)."""
    et = ZoneInfo("America/New_York")
    sch = CustomWindows(windows=[(time(23, 0), time(1, 30))], tz=et)
    # 2026-05-22 22:00 EDT = 2026-05-23 02:00 UTC
    ts = datetime(2026, 5, 23, 2, 0, tzinfo=UTC)
    assert not sch.should_trade(ts)


def test_custom_windows_overnight_at_exact_start_and_end() -> None:
    """Endpoints are inclusive on both sides of midnight."""
    et = ZoneInfo("America/New_York")
    sch = CustomWindows(windows=[(time(23, 0), time(1, 30))], tz=et)
    # 23:00 EDT
    assert sch.should_trade(datetime(2026, 5, 23, 3, 0, tzinfo=UTC))
    # 01:30 EDT
    assert sch.should_trade(datetime(2026, 5, 23, 5, 30, tzinfo=UTC))


def test_custom_windows_mixed_normal_and_overnight() -> None:
    """Real Gold Bot shape: 08:30-15:00 normal + 23:00-01:30 overnight."""
    et = ZoneInfo("America/New_York")
    sch = CustomWindows(
        windows=[(time(8, 30), time(15, 0)), (time(23, 0), time(1, 30))],
        tz=et,
    )
    # 09:00 EDT → first window
    assert sch.should_trade(datetime(2026, 5, 22, 13, 0, tzinfo=UTC))
    # 00:15 EDT → second window (overnight)
    assert sch.should_trade(datetime(2026, 5, 23, 4, 15, tzinfo=UTC))
    # 18:00 EDT → neither
    assert not sch.should_trade(datetime(2026, 5, 22, 22, 0, tzinfo=UTC))
