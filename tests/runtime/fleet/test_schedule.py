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
