"""Plan 14: IBLiveBarStream constructs IB Futures from MarketSpec, not hardcoded MNQ.

Existing MNQ tests in tests/test_data_live_ib.py stay as regression coverage;
this file checks the multi-market contract-construction surface.
"""
from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("symbol", "expected_root", "expected_exchange", "expected_currency"),
    [
        ("NQ",  "NQ",  "CME",   "USD"),
        ("MNQ", "MNQ", "CME",   "USD"),
        ("ES",  "ES",  "CME",   "USD"),
        ("MES", "MES", "CME",   "USD"),
        ("GC",  "GC",  "COMEX", "USD"),
        ("MGC", "MGC", "COMEX", "USD"),
    ],
)
def test_build_contract_per_market(
    symbol: str, expected_root: str,
    expected_exchange: str, expected_currency: str,
) -> None:
    from bot.data.live_ib import build_contract
    fut = build_contract(symbol)
    assert fut.symbol == expected_root
    assert fut.exchange == expected_exchange
    assert fut.currency == expected_currency
    assert fut.secType == "FUT"


def test_build_contract_unknown_symbol_raises_keyerror() -> None:
    """Symbols outside the registry (e.g., CL) raise KeyError loudly."""
    from bot.data.live_ib import build_contract
    with pytest.raises(KeyError):
        build_contract("CL")
