"""FirstRateDataLoader.load(): parquet → Bar iterator."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _setup_ingested(tmp_path: Path) -> Path:
    """Helper: ingest the clean fixture into tmp_path/parquet and return parquet_root."""
    from bot.data.firstratedata import FirstRateDataLoader
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    (raw_root / "NQ_2023Z_1min.csv").write_text(
        (_FIXTURES / "nq_2023z_clean.csv").read_text()
    )
    parquet_root = tmp_path / "parquet"
    FirstRateDataLoader(raw_root, parquet_root).ingest(symbol="NQ")
    return parquet_root


def test_load_returns_bars_in_order(tmp_path) -> None:
    from bot.data.firstratedata import FirstRateDataLoader
    parquet_root = _setup_ingested(tmp_path)
    loader = FirstRateDataLoader(raw_root=tmp_path / "raw", parquet_root=parquet_root)
    bars = list(loader.load(
        symbol="NQ", contract="2023Z",
        start=datetime(2023, 12, 15, 0, 0, tzinfo=UTC),
        end=datetime(2023, 12, 16, 0, 0, tzinfo=UTC),
    ))
    assert len(bars) == 3
    # Monotonic timestamps
    assert all(bars[i].timestamp < bars[i + 1].timestamp for i in range(len(bars) - 1))
    # Symbol matches request
    assert all(b.symbol == "NQ" for b in bars)
    # Interval populated
    assert all(b.interval == "1m" for b in bars)


def test_load_respects_time_window(tmp_path) -> None:
    """Loading a tight window returns only matching bars."""
    from bot.data.firstratedata import FirstRateDataLoader
    parquet_root = _setup_ingested(tmp_path)
    loader = FirstRateDataLoader(raw_root=tmp_path / "raw", parquet_root=parquet_root)
    # 09:31-09:32 ET window. Fixture has 09:30, 09:31, 09:32 ET.
    # ET is UTC-5 in Dec, so 09:31 ET = 14:31 UTC.
    bars = list(loader.load(
        symbol="NQ", contract="2023Z",
        start=datetime(2023, 12, 15, 14, 31, tzinfo=UTC),
        end=datetime(2023, 12, 15, 14, 32, tzinfo=UTC),
    ))
    assert len(bars) == 1
    assert bars[0].open == 16505.00
