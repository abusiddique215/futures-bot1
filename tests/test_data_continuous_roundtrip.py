"""End-to-end roll roundtrip: ingest two contracts, write continuous, read back."""
from __future__ import annotations

from pathlib import Path

import pytest

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _setup_two(tmp_path: Path) -> Path:
    from bot.data.firstratedata import FirstRateDataLoader
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    (raw_root / "MNQ_2023Z_1min.csv").write_text(
        (_FIXTURES / "mnq_roll_pair_2023z.csv").read_text()
    )
    (raw_root / "MNQ_2024H_1min.csv").write_text(
        (_FIXTURES / "mnq_roll_pair_2024h.csv").read_text()
    )
    parquet_root = tmp_path / "parquet"
    FirstRateDataLoader(raw_root, parquet_root).ingest(symbol="MNQ")
    return parquet_root


def test_write_continuous_creates_parquet_and_roll_events(tmp_path) -> None:
    from bot.data.continuous import ContinuousAdjuster
    parquet_root = _setup_two(tmp_path)
    adj = ContinuousAdjuster(parquet_root=parquet_root)
    adj.write_continuous(symbol="MNQ")

    cont_root = parquet_root / "continuous" / "symbol=MNQ"
    assert cont_root.exists()
    parquet_files = list(cont_root.rglob("*.parquet"))
    assert len(parquet_files) >= 1

    roll_events = parquet_root / "continuous" / "roll_events.parquet"
    assert roll_events.exists()


def test_continuous_seam_equals_new_contract_close(tmp_path) -> None:
    """Spec 01 §3.2: scaled old contract = new contract's price at the seam."""
    import pyarrow.dataset as ds

    from bot.data.continuous import ContinuousAdjuster

    parquet_root = _setup_two(tmp_path)
    adj = ContinuousAdjuster(parquet_root=parquet_root)
    adj.write_continuous(symbol="MNQ")

    cont = ds.dataset(  # type: ignore[no-untyped-call]
        str(parquet_root / "continuous" / "symbol=MNQ"), format="parquet"
    )
    table = cont.to_table().sort_by([("timestamp", "ascending")])
    rows = table.to_pylist()
    # Both fixture rows are at the same timestamp (the seam) — after scaling
    # both should read $16600 (new contract's value).
    # 2024H bar (unscaled): 16600
    # 2023Z bar scaled by 16600/16500: 16500 * (16600/16500) = 16600
    closes = [r["close"] for r in rows]
    assert all(c == pytest.approx(16600.0) for c in closes)
