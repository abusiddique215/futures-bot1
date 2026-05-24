"""MARKETS registry — 6 entries (NQ, MNQ, GC, MGC, ES, MES) + lookup helpers.

Tick values, multipliers, contract months, and roll rules verified via CME
contract-spec pages (see docs/superpowers/research/2026-05-23-cme-comex-contract-specs.md).
"""
from __future__ import annotations

import pytest


def test_registry_has_six_markets() -> None:
    from bot.markets.registry import MARKETS
    assert set(MARKETS.keys()) == {"NQ", "MNQ", "GC", "MGC", "ES", "MES"}


# ---- tick values (verified against CME contractSpecs pages) ---------------

@pytest.mark.parametrize(
    ("root", "tick_value"),
    [
        ("NQ",  5.00),    # 0.25 pt * $20/pt
        ("MNQ", 0.50),    # 0.25 pt * $2/pt
        ("ES",  12.50),   # 0.25 pt * $50/pt
        ("MES", 1.25),    # 0.25 pt * $5/pt
        ("GC",  10.00),   # $0.10/oz * 100 oz
        ("MGC", 1.00),    # $0.10/oz * 10 oz
    ],
)
def test_tick_value_per_market(root: str, tick_value: float) -> None:
    from bot.markets.registry import MARKETS
    assert MARKETS[root].tick_value == pytest.approx(tick_value)


@pytest.mark.parametrize(
    ("root", "tick_size"),
    [
        ("NQ",  0.25),
        ("MNQ", 0.25),
        ("ES",  0.25),
        ("MES", 0.25),
        ("GC",  0.10),
        ("MGC", 0.10),
    ],
)
def test_tick_size_per_market(root: str, tick_size: float) -> None:
    from bot.markets.registry import MARKETS
    assert MARKETS[root].tick_size == pytest.approx(tick_size)


@pytest.mark.parametrize(
    ("root", "multiplier"),
    [
        ("NQ",  20.0),
        ("MNQ", 2.0),
        ("ES",  50.0),
        ("MES", 5.0),
        ("GC",  100.0),
        ("MGC", 10.0),
    ],
)
def test_multiplier_per_market(root: str, multiplier: float) -> None:
    from bot.markets.registry import MARKETS
    assert MARKETS[root].multiplier == pytest.approx(multiplier)


def test_tick_value_equals_tick_size_times_multiplier() -> None:
    """Internal consistency: tick_value = tick_size * multiplier for every market."""
    from bot.markets.registry import MARKETS
    for spec in MARKETS.values():
        assert spec.tick_value == pytest.approx(spec.tick_size * spec.multiplier)


# ---- exchange + IB fields --------------------------------------------------

@pytest.mark.parametrize(
    ("root", "exchange"),
    [
        ("NQ",  "CME"),
        ("MNQ", "CME"),
        ("ES",  "CME"),
        ("MES", "CME"),
        ("GC",  "COMEX"),
        ("MGC", "COMEX"),
    ],
)
def test_exchange_per_market(root: str, exchange: str) -> None:
    from bot.markets.registry import MARKETS
    assert MARKETS[root].exchange == exchange


def test_all_markets_use_fut_secType_and_usd() -> None:
    from bot.markets.registry import MARKETS
    for spec in MARKETS.values():
        assert spec.ib_sec_type == "FUT"
        assert spec.ib_currency == "USD"


# ---- micro pairings --------------------------------------------------------

@pytest.mark.parametrize(
    ("full", "micro"),
    [("NQ", "MNQ"), ("ES", "MES"), ("GC", "MGC")],
)
def test_full_markets_point_to_their_micro(full: str, micro: str) -> None:
    from bot.markets.registry import MARKETS
    assert MARKETS[full].micro_root == micro


@pytest.mark.parametrize("micro", ["MNQ", "MES", "MGC"])
def test_micro_markets_have_no_micro_of_their_own(micro: str) -> None:
    from bot.markets.registry import MARKETS
    assert MARKETS[micro].micro_root is None


def test_micro_to_full_ratio_is_10_for_all_six() -> None:
    from bot.markets.registry import MARKETS
    for spec in MARKETS.values():
        assert spec.micro_to_full_ratio == 10


# ---- contract months -------------------------------------------------------

@pytest.mark.parametrize(
    ("root", "months"),
    [
        ("NQ",  ("H", "M", "U", "Z")),
        ("MNQ", ("H", "M", "U", "Z")),
        ("ES",  ("H", "M", "U", "Z")),
        ("MES", ("H", "M", "U", "Z")),
        ("GC",  ("G", "J", "M", "Q", "V", "Z")),
        ("MGC", ("G", "J", "M", "Q", "V", "Z")),
    ],
)
def test_contract_months_per_market(root: str, months: tuple[str, ...]) -> None:
    from bot.markets.registry import MARKETS
    assert MARKETS[root].contract_months == months


# ---- roll rules ------------------------------------------------------------

@pytest.mark.parametrize(
    ("root", "rule"),
    [
        ("NQ",  "third_friday_of_contract_month"),
        ("MNQ", "third_friday_of_contract_month"),
        ("ES",  "third_friday_of_contract_month"),
        ("MES", "third_friday_of_contract_month"),
        ("GC",  "third_last_business_day_of_prev_month"),
        ("MGC", "third_last_business_day_of_prev_month"),
    ],
)
def test_roll_day_rule_per_market(root: str, rule: str) -> None:
    from bot.markets.registry import MARKETS
    assert MARKETS[root].roll_day_rule == rule


# ---- helpers ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("symbol", "expected_root"),
    [
        ("NQ",       "NQ"),
        ("NQH26",    "NQ"),
        ("MNQ",      "MNQ"),
        ("MNQZ25",   "MNQ"),
        ("ES",       "ES"),
        ("ESM26",    "ES"),
        ("MES",      "MES"),
        ("MESH26",   "MES"),
        ("GC",       "GC"),
        ("GCZ25",    "GC"),
        ("MGC",      "MGC"),
        ("MGCG26",   "MGC"),
    ],
)
def test_get_market_extracts_root_from_full_symbol(symbol: str, expected_root: str) -> None:
    from bot.markets.registry import get_market
    assert get_market(symbol).root == expected_root


def test_get_market_unknown_raises_keyerror() -> None:
    from bot.markets.registry import get_market
    with pytest.raises(KeyError, match="UNKNOWN"):
        get_market("UNKNOWN")


def test_get_market_empty_string_raises_keyerror() -> None:
    from bot.markets.registry import get_market
    with pytest.raises(KeyError):
        get_market("")


@pytest.mark.parametrize(
    ("symbol", "is_micro"),
    [
        ("NQ",     False),
        ("NQH26",  False),
        ("MNQ",    True),
        ("MNQH26", True),
        ("ES",     False),
        ("MES",    True),
        ("GC",     False),
        ("MGC",    True),
    ],
)
def test_is_micro(symbol: str, is_micro: bool) -> None:
    from bot.markets.registry import is_micro as is_micro_fn
    assert is_micro_fn(symbol) is is_micro


@pytest.mark.parametrize(
    ("symbol", "full_root"),
    [
        ("MNQ",    "NQ"),
        ("MNQH26", "NQ"),
        ("NQ",     "NQ"),
        ("MES",    "ES"),
        ("ES",     "ES"),
        ("MGC",    "GC"),
        ("GC",     "GC"),
    ],
)
def test_full_root_for(symbol: str, full_root: str) -> None:
    from bot.markets.registry import full_root_for
    assert full_root_for(symbol) == full_root


def test_all_markets_returns_six_specs() -> None:
    from bot.markets.registry import all_markets
    specs = all_markets()
    assert len(specs) == 6
    roots = {s.root for s in specs}
    assert roots == {"NQ", "MNQ", "GC", "MGC", "ES", "MES"}
