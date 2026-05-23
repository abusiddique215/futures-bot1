"""ContinuousAdjuster.compute_ratios. Spec 01 §3.2."""
from __future__ import annotations

from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _setup_two_contracts(tmp_path: Path) -> Path:
    """Ingest two roll-pair contracts; return parquet_root."""
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


def test_roll_event_dataclass_shape() -> None:
    from datetime import date

    from bot.data.continuous import RollEvent
    e = RollEvent(symbol="MNQ", roll_date=date(2023, 12, 15),
                  old_contract="2023Z", new_contract="2024H",
                  c_old_close=16500.0, c_new_close=16600.0,
                  ratio=16500.0 / 16600.0, cumulative_scale=1.0)
    assert e.symbol == "MNQ"
    assert e.ratio < 1.0


def test_compute_ratios_two_contracts(tmp_path: Path) -> None:
    """With two ingested contracts, compute_ratios returns one RollEvent."""
    from bot.data.continuous import ContinuousAdjuster
    parquet_root = _setup_two_contracts(tmp_path)
    adj = ContinuousAdjuster(parquet_root=parquet_root)
    events = adj.compute_ratios(symbol="MNQ")
    assert len(events) == 1
    e = events[0]
    assert e.old_contract == "2023Z"
    assert e.new_contract == "2024H"
    assert e.c_old_close == 16500.0
    assert e.c_new_close == 16600.0
    assert e.ratio == 16500.0 / 16600.0


def test_compute_ratios_empty_when_one_contract(tmp_path: Path) -> None:
    """One contract → no rolls."""
    from bot.data.continuous import ContinuousAdjuster
    from bot.data.firstratedata import FirstRateDataLoader
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    (raw_root / "MNQ_2023Z_1min.csv").write_text(
        (_FIXTURES / "mnq_roll_pair_2023z.csv").read_text()
    )
    parquet_root = tmp_path / "parquet"
    FirstRateDataLoader(raw_root, parquet_root).ingest(symbol="MNQ")
    adj = ContinuousAdjuster(parquet_root=parquet_root)
    events = adj.compute_ratios(symbol="MNQ")
    assert events == []
