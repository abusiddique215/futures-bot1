"""Plan 14: FirstRateData filename parser accepts every registered market.

Regression coverage (NQ/MNQ) lives in tests/test_data_firstratedata_filename.py;
this file extends to ES/MES/GC/MGC plus the gold-month codes G/J/M/Q/V/Z.
"""
from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("filename", "symbol", "contract"),
    [
        # Existing equity-index markets.
        ("NQ_2023Z_1min.csv",  "NQ",  "2023Z"),
        ("MNQ_2024H_1min.csv", "MNQ", "2024H"),
        # New equity-index markets.
        ("ES_2026M_1min.csv",  "ES",  "2026M"),
        ("MES_2026U_1min.csv", "MES", "2026U"),
        # Gold markets — even-month codes G/J/M/Q/V/Z.
        ("GC_2026G_1min.csv",  "GC",  "2026G"),
        ("GC_2026J_1min.csv",  "GC",  "2026J"),
        ("GC_2026Q_1min.csv",  "GC",  "2026Q"),
        ("GC_2026V_1min.csv",  "GC",  "2026V"),
        ("MGC_2026Z_1min.csv", "MGC", "2026Z"),
    ],
)
def test_parse_filename_per_market(
    filename: str, symbol: str, contract: str,
) -> None:
    from bot.data.firstratedata import parse_firstratedata_filename
    info = parse_firstratedata_filename(filename)
    assert info.symbol == symbol
    assert info.contract == contract
    assert info.interval == "1min"


def test_mnq_not_misclassified_as_nq() -> None:
    """Regex alternation must prefer the longer 3-char roots (MNQ/MES/MGC)
    over the 2-char roots (NQ/ES/GC). If MNQ_*.csv parsed as symbol=NQ, the
    leftover M would push the contract code off by one character."""
    from bot.data.firstratedata import parse_firstratedata_filename
    info = parse_firstratedata_filename("MNQ_2024H_1min.csv")
    assert info.symbol == "MNQ"
    assert info.contract == "2024H"


def test_parse_filename_rejects_unregistered_root() -> None:
    """CL (crude oil) is not in the Plan-14 registry → ValueError."""
    from bot.data.firstratedata import parse_firstratedata_filename
    with pytest.raises(ValueError, match="does not match"):
        parse_firstratedata_filename("CL_2026M_1min.csv")
