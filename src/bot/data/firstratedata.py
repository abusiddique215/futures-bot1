"""FirstRateData CSV loader.

Filename convention: `<SYMBOL>_<YYYY><M>_1min.csv` (spec 01 §3.1).
This module is the only one that knows the FirstRateData on-disk format;
downstream (continuous adjuster, backtest) sees only Bar instances.

This task ships ONLY the filename parser. The loader class comes in Task 6.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bot.data.contract_calendar import parse_contract_code

_FILENAME_RE = re.compile(r"^(?P<symbol>NQ|MNQ)_(?P<contract>\d{4}[HMUZ])_(?P<interval>1min)\.csv$")


@dataclass(frozen=True)
class FirstRateDataFilename:
    """Parsed FirstRateData filename."""
    symbol: str          # "NQ" | "MNQ"
    contract: str        # "2023Z"
    interval: str        # "1min" (v1 only supports 1-min input)


def parse_firstratedata_filename(path: Path | str) -> FirstRateDataFilename:
    """Parse a FirstRateData CSV filename. Accepts Path or str.

    Raises ValueError on malformed input or unsupported interval.
    """
    if isinstance(path, str):
        path = Path(path)
    name = path.name
    match = _FILENAME_RE.match(name)
    if not match:
        raise ValueError(
            f"Filename {name!r} does not match FirstRateData convention "
            f"<NQ|MNQ>_<YYYY><HMUZ>_1min.csv"
        )
    contract = match.group("contract")
    parse_contract_code(contract)  # raises ValueError on bad month code
    return FirstRateDataFilename(
        symbol=match.group("symbol"),
        contract=contract,
        interval=match.group("interval"),
    )
