"""MARKETS — the single source of truth for per-market parameters.

Six markets are supported as of Plan 14: NQ, MNQ (CME E-mini/Micro Nasdaq-100);
ES, MES (CME E-mini/Micro S&P 500); GC, MGC (COMEX Gold / Micro Gold).

Every per-market constant in this codebase (tick value/size, multiplier,
contract-month codes, roll convention, IB contract construction) flows from
the registry; symbol-startswith branching is forbidden everywhere else.

Verification of every value below: see
`docs/superpowers/research/2026-05-23-cme-comex-contract-specs.md` for citation
URLs and the WebSearch transcripts.
"""
from __future__ import annotations

from typing import Final

from bot.markets.spec import MarketSpec

# ---- registry entries -----------------------------------------------------
#
# Citations (CME contractSpecs pages, fetched 2026-05-23):
#   NQ  : https://www.cmegroup.com/markets/equities/nasdaq/e-mini-nasdaq-100.contractSpecs.html
#   MNQ : https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html
#   ES  : https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.contractSpecs.html
#   MES : https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp-500.contractSpecs.html
#   GC  : https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html
#   MGC : https://www.cmegroup.com/markets/metals/precious/e-micro-gold.contractSpecs.html
#
# Equity-index roll convention: third Friday of contract month (H/M/U/Z).
# Gold roll convention: third-last business day of the month preceding
#                       delivery month, applied to G/J/M/Q/V/Z months.

MARKETS: Final[dict[str, MarketSpec]] = {
    "NQ": MarketSpec(
        root="NQ",
        name="E-mini Nasdaq-100",
        exchange="CME",
        tick_size=0.25,
        tick_value=5.00,         # 0.25 pt x $20/pt
        multiplier=20.0,
        micro_root="MNQ",
        micro_to_full_ratio=10,
        contract_months=("H", "M", "U", "Z"),
        roll_day_rule="third_friday_of_contract_month",
        ib_sec_type="FUT",
        ib_currency="USD",
    ),
    "MNQ": MarketSpec(
        root="MNQ",
        name="Micro E-mini Nasdaq-100",
        exchange="CME",
        tick_size=0.25,
        tick_value=0.50,         # 0.25 pt x $2/pt
        multiplier=2.0,
        micro_root=None,
        micro_to_full_ratio=10,
        contract_months=("H", "M", "U", "Z"),
        roll_day_rule="third_friday_of_contract_month",
        ib_sec_type="FUT",
        ib_currency="USD",
    ),
    "ES": MarketSpec(
        root="ES",
        name="E-mini S&P 500",
        exchange="CME",
        tick_size=0.25,
        tick_value=12.50,        # 0.25 pt x $50/pt
        multiplier=50.0,
        micro_root="MES",
        micro_to_full_ratio=10,
        contract_months=("H", "M", "U", "Z"),
        roll_day_rule="third_friday_of_contract_month",
        ib_sec_type="FUT",
        ib_currency="USD",
    ),
    "MES": MarketSpec(
        root="MES",
        name="Micro E-mini S&P 500",
        exchange="CME",
        tick_size=0.25,
        tick_value=1.25,         # 0.25 pt x $5/pt
        multiplier=5.0,
        micro_root=None,
        micro_to_full_ratio=10,
        contract_months=("H", "M", "U", "Z"),
        roll_day_rule="third_friday_of_contract_month",
        ib_sec_type="FUT",
        ib_currency="USD",
    ),
    "GC": MarketSpec(
        root="GC",
        name="Gold",
        exchange="COMEX",
        tick_size=0.10,          # $0.10 per troy ounce
        tick_value=10.00,        # $0.10 x 100 oz
        multiplier=100.0,        # 100 troy ounces / point
        micro_root="MGC",
        micro_to_full_ratio=10,
        contract_months=("G", "J", "M", "Q", "V", "Z"),
        roll_day_rule="third_last_business_day_of_prev_month",
        ib_sec_type="FUT",
        ib_currency="USD",
    ),
    "MGC": MarketSpec(
        root="MGC",
        name="Micro Gold",
        exchange="COMEX",
        tick_size=0.10,
        tick_value=1.00,         # $0.10 x 10 oz
        multiplier=10.0,
        micro_root=None,
        micro_to_full_ratio=10,
        contract_months=("G", "J", "M", "Q", "V", "Z"),
        roll_day_rule="third_last_business_day_of_prev_month",
        ib_sec_type="FUT",
        ib_currency="USD",
    ),
}


# ---- lookup helpers --------------------------------------------------------
#
# Symbols on the wire come in two shapes:
#   - bare root, e.g., "NQ", "MGC" — used in tests and most call sites.
#   - root + contract suffix, e.g., "NQH26", "MGCG26" — IB / TopstepX style.
#
# The roots are 2-3 characters; the suffix is exactly 3 chars (one letter +
# two digits). The 3-char roots (MNQ, MES, MGC) MUST be matched before the
# 2-char roots (NQ, ES, GC) to avoid mis-classifying "MNQH26" as "NQ".

# Sorted longest-root-first so prefix matching prefers MNQ over NQ etc.
_ROOTS_LONGEST_FIRST: Final[tuple[str, ...]] = tuple(
    sorted(MARKETS.keys(), key=len, reverse=True)
)


def _extract_root(symbol: str) -> str:
    """Return the registry root prefix of `symbol`, or "" if none matches."""
    for root in _ROOTS_LONGEST_FIRST:
        if symbol == root or symbol.startswith(root):
            return root
    return ""


def get_market(symbol: str) -> MarketSpec:
    """Look up the MarketSpec for `symbol`. Bare roots and root+contract both work.

    Raises KeyError if no registered market matches the symbol's prefix.
    """
    root = _extract_root(symbol)
    if not root:
        raise KeyError(f"No registered market for symbol {symbol!r}")
    return MARKETS[root]


def is_micro(symbol: str) -> bool:
    """True iff `symbol` belongs to a micro market (MNQ/MES/MGC)."""
    return get_market(symbol).micro_root is None and _extract_root(symbol).startswith("M")


def full_root_for(symbol: str) -> str:
    """Return the full (non-micro) root for `symbol`.

    For a micro market symbol, returns the corresponding full root (MNQ→NQ,
    MES→ES, MGC→GC). For a full symbol, returns its own root.
    """
    market = get_market(symbol)
    if market.micro_root is not None:
        # Already a full market.
        return market.root
    # Micro market — strip the leading "M".
    return market.root[1:]


def all_markets() -> list[MarketSpec]:
    """Return all six registered MarketSpec instances."""
    return list(MARKETS.values())
