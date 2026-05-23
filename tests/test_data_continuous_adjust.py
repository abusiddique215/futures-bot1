"""ContinuousAdjuster.adjust_with_rolls — cumulative ratio application. Spec 01 §3.2."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.types import Bar


def _bar(contract: str, ts: datetime, close: float, volume: int = 1000) -> Bar:
    return Bar(symbol="MNQ", open=close, high=close, low=close, close=close,
               volume=volume, timestamp=ts, interval="1m")


def test_adjust_single_roll_scales_old_contract() -> None:
    """Worked example: c_old=16500, c_new=16600 → scale OLD bars by 16600/16500."""
    from datetime import date

    from bot.data.continuous import ContinuousAdjuster, RollEvent

    rolls = [RollEvent(symbol="MNQ", roll_date=date(2023, 12, 15),
                       old_contract="2023Z", new_contract="2024H",
                       c_old_close=16500.0, c_new_close=16600.0,
                       ratio=16500.0 / 16600.0,
                       cumulative_scale=16600.0 / 16500.0)]

    bars_by_contract = {
        "2023Z": [_bar("2023Z", datetime(2023, 12, 15, 14, 30, tzinfo=UTC), 16300.0)],
        "2024H": [_bar("2024H", datetime(2024, 3, 15, 14, 30, tzinfo=UTC), 17000.0)],
    }

    adjusted = list(ContinuousAdjuster.adjust_with_rolls(bars_by_contract, rolls))
    z_bar = next(b for b in adjusted if b.timestamp.year == 2023)
    h_bar = next(b for b in adjusted if b.timestamp.year == 2024)
    assert z_bar.close == pytest.approx(16300.0 * 16600.0 / 16500.0, rel=1e-6)
    assert h_bar.close == 17000.0  # newest contract unscaled
    assert z_bar.volume == 1000
    assert h_bar.volume == 1000


def test_adjust_multi_roll_cumulative_scaling() -> None:
    """Three contracts c1→c2→c3 with two rolls. c1 bars scaled by (c2/c1)*(c3/c2)."""
    from datetime import date

    from bot.data.continuous import ContinuousAdjuster, RollEvent

    rolls = [
        RollEvent(symbol="MNQ", roll_date=date(2023, 9, 15),
                  old_contract="2023U", new_contract="2023Z",
                  c_old_close=14000.0, c_new_close=15000.0,
                  ratio=14000.0 / 15000.0,
                  cumulative_scale=(15000.0 / 14000.0) * (16600.0 / 16500.0)),
        RollEvent(symbol="MNQ", roll_date=date(2023, 12, 15),
                  old_contract="2023Z", new_contract="2024H",
                  c_old_close=16500.0, c_new_close=16600.0,
                  ratio=16500.0 / 16600.0,
                  cumulative_scale=16600.0 / 16500.0),
    ]

    bars_by_contract = {
        "2023U": [_bar("2023U", datetime(2023, 9, 15, 14, 30, tzinfo=UTC), 13000.0)],
        "2023Z": [_bar("2023Z", datetime(2023, 12, 15, 14, 30, tzinfo=UTC), 16300.0)],
        "2024H": [_bar("2024H", datetime(2024, 3, 15, 14, 30, tzinfo=UTC), 17000.0)],
    }

    adjusted = list(ContinuousAdjuster.adjust_with_rolls(bars_by_contract, rolls))
    u_bar = next(b for b in adjusted if b.timestamp.year == 2023 and b.timestamp.month == 9)
    z_bar = next(b for b in adjusted if b.timestamp.year == 2023 and b.timestamp.month == 12)
    expected_u = 13000.0 * (15000.0 / 14000.0) * (16600.0 / 16500.0)
    assert u_bar.close == pytest.approx(expected_u, rel=1e-6)
    expected_z = 16300.0 * (16600.0 / 16500.0)
    assert z_bar.close == pytest.approx(expected_z, rel=1e-6)


def test_volume_not_scaled() -> None:
    from datetime import date

    from bot.data.continuous import ContinuousAdjuster, RollEvent

    rolls = [RollEvent(symbol="MNQ", roll_date=date(2023, 12, 15),
                       old_contract="2023Z", new_contract="2024H",
                       c_old_close=16500.0, c_new_close=16600.0,
                       ratio=16500.0 / 16600.0,
                       cumulative_scale=16600.0 / 16500.0)]
    bars_by_contract = {
        "2023Z": [_bar("2023Z", datetime(2023, 12, 15, 14, 30, tzinfo=UTC),
                       16300.0, volume=42)],
        "2024H": [_bar("2024H", datetime(2024, 3, 15, 14, 30, tzinfo=UTC),
                       17000.0, volume=99)],
    }
    adjusted = list(ContinuousAdjuster.adjust_with_rolls(bars_by_contract, rolls))
    z_vol = next(b for b in adjusted if b.timestamp.year == 2023).volume
    h_vol = next(b for b in adjusted if b.timestamp.year == 2024).volume
    assert z_vol == 42
    assert h_vol == 99
