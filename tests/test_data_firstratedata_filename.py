"""FirstRateData filename parser. Spec 01 §3.1."""
from __future__ import annotations

import pytest


def test_parse_canonical_filename() -> None:
    from bot.data.firstratedata import parse_firstratedata_filename

    info = parse_firstratedata_filename("NQ_2023Z_1min.csv")
    assert info.symbol == "NQ"
    assert info.contract == "2023Z"
    assert info.interval == "1min"


def test_parse_mnq_filename() -> None:
    from bot.data.firstratedata import parse_firstratedata_filename

    info = parse_firstratedata_filename("MNQ_2024H_1min.csv")
    assert info.symbol == "MNQ"
    assert info.contract == "2024H"


def test_parse_filename_with_path() -> None:
    """Accepts full paths and just basenames."""
    from pathlib import Path

    from bot.data.firstratedata import parse_firstratedata_filename

    info = parse_firstratedata_filename(Path("/x/y/NQ_2023Z_1min.csv"))
    assert info.symbol == "NQ"


def test_parse_filename_rejects_malformed() -> None:
    from bot.data.firstratedata import parse_firstratedata_filename

    with pytest.raises(ValueError, match="does not match"):
        parse_firstratedata_filename("garbage.csv")
    with pytest.raises(ValueError, match="does not match"):
        parse_firstratedata_filename("NQ_2023X_1min.csv")  # bad month code
    with pytest.raises(ValueError, match="does not match"):
        parse_firstratedata_filename("NQ_2023Z_5min.csv")  # we don't support 5-min input
