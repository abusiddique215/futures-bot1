"""MarketSpec — frozen+slots dataclass describing one futures market.

Spec: 01-data-pipeline.md (post-Plan-14: MarketSpec is the per-market SoT).
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest


def _make_nq_spec():
    from bot.markets.spec import MarketSpec
    return MarketSpec(
        root="NQ",
        name="E-mini Nasdaq-100",
        exchange="CME",
        tick_size=0.25,
        tick_value=5.00,
        multiplier=20.0,
        micro_root="MNQ",
        micro_to_full_ratio=10,
        contract_months=("H", "M", "U", "Z"),
        roll_day_rule="third_friday_prev_month",
        ib_sec_type="FUT",
        ib_currency="USD",
    )


def test_market_spec_constructs_with_all_fields() -> None:
    s = _make_nq_spec()
    assert s.root == "NQ"
    assert s.name == "E-mini Nasdaq-100"
    assert s.exchange == "CME"
    assert s.tick_size == pytest.approx(0.25)
    assert s.tick_value == pytest.approx(5.00)
    assert s.multiplier == pytest.approx(20.0)
    assert s.micro_root == "MNQ"
    assert s.micro_to_full_ratio == 10
    assert s.contract_months == ("H", "M", "U", "Z")
    assert s.roll_day_rule == "third_friday_prev_month"
    assert s.ib_sec_type == "FUT"
    assert s.ib_currency == "USD"


def test_market_spec_is_frozen() -> None:
    s = _make_nq_spec()
    with pytest.raises(FrozenInstanceError):
        s.tick_value = 99.0  # type: ignore[misc]


def test_market_spec_uses_slots() -> None:
    """slots=True means __dict__ does not exist; attribute assignment of new
    names is rejected even ignoring frozen."""
    s = _make_nq_spec()
    assert not hasattr(s, "__dict__")


def test_market_spec_micro_root_optional() -> None:
    """A market without a micro variant uses micro_root=None."""
    from bot.markets.spec import MarketSpec
    s = MarketSpec(
        root="ZB",
        name="30-Year US Treasury Bond",
        exchange="CBOT",
        tick_size=1 / 32,
        tick_value=31.25,
        multiplier=1000.0,
        micro_root=None,
        micro_to_full_ratio=1,
        contract_months=("H", "M", "U", "Z"),
        roll_day_rule="third_friday_prev_month",
        ib_sec_type="FUT",
        ib_currency="USD",
    )
    assert s.micro_root is None


def test_market_spec_equality_uses_field_values() -> None:
    a = _make_nq_spec()
    b = _make_nq_spec()
    assert a == b
    assert hash(a) == hash(b)
