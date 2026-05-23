"""FirstRateData ingest: CSV → parquet. Spec 01 §3.1."""
from __future__ import annotations

from pathlib import Path

import pytest

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_ingest_clean_csv_writes_parquet(tmp_path) -> None:
    """A clean CSV produces a parquet partition with the expected row count."""
    from bot.data.firstratedata import FirstRateDataLoader
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    src = raw_root / "NQ_2023Z_1min.csv"
    src.write_text((_FIXTURES / "nq_2023z_clean.csv").read_text())

    loader = FirstRateDataLoader(raw_root=raw_root, parquet_root=tmp_path / "parquet")
    summary = loader.ingest(symbol="NQ")

    partition = tmp_path / "parquet" / "symbol=NQ" / "contract=2023Z" / "year=2023" / "month=12"
    assert partition.exists()
    parquet_files = list(partition.glob("*.parquet"))
    assert len(parquet_files) == 1
    assert summary.rows_written == 3
    assert summary.rows_quarantined == 0


def test_ingest_quarantines_bad_ohlc(tmp_path) -> None:
    from bot.data.firstratedata import FirstRateDataLoader
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    src = raw_root / "NQ_2023Z_1min.csv"
    src.write_text((_FIXTURES / "nq_2023z_bad_ohlc.csv").read_text())

    loader = FirstRateDataLoader(raw_root=raw_root, parquet_root=tmp_path / "parquet")
    summary = loader.ingest(symbol="NQ")
    assert summary.rows_written == 1
    assert summary.rows_quarantined == 1
    quarantine_root = tmp_path / "parquet" / "_quarantine"
    quarantine_files = list(quarantine_root.rglob("*.csv"))
    assert len(quarantine_files) >= 1


def test_ingest_fails_loud_when_high_quarantine_rate(tmp_path) -> None:
    """If >0.1% of rows quarantine, ingest raises (vendor regression signal)."""
    from bot.data.firstratedata import FirstRateDataLoader, IngestQualityError
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    src = raw_root / "NQ_2023Z_1min.csv"
    src.write_text((_FIXTURES / "nq_2023z_bad_ohlc.csv").read_text())

    loader = FirstRateDataLoader(raw_root=raw_root, parquet_root=tmp_path / "parquet")
    with pytest.raises(IngestQualityError, match="quarantine rate"):
        loader.ingest(symbol="NQ", quarantine_rate_threshold=0.001)


def test_ingest_idempotent_re_run_no_op(tmp_path) -> None:
    """Re-running ingest on same input is a no-op (parquet already present)."""
    from bot.data.firstratedata import FirstRateDataLoader
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    src = raw_root / "NQ_2023Z_1min.csv"
    src.write_text((_FIXTURES / "nq_2023z_clean.csv").read_text())

    loader = FirstRateDataLoader(raw_root=raw_root, parquet_root=tmp_path / "parquet")
    summary1 = loader.ingest(symbol="NQ")
    summary2 = loader.ingest(symbol="NQ")
    assert summary1.rows_written == 3
    assert summary2.rows_written == 0
    assert summary2.files_skipped == 1
