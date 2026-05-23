"""FirstRateData CSV loader.

Filename convention: `<SYMBOL>_<YYYY><M>_1min.csv` (spec 01 §3.1).
This module is the only one that knows the FirstRateData on-disk format;
downstream (continuous adjuster, backtest) sees only Bar instances.

This task ships ONLY the filename parser. The loader class comes in Task 6.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

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


# ---- Loader ----------------------------------------------------------------

class IngestQualityError(Exception):
    """Raised when ingest quarantine rate exceeds threshold."""


@dataclass(frozen=True)
class IngestSummary:
    rows_written: int
    rows_quarantined: int
    files_processed: int
    files_skipped: int


_ET = ZoneInfo("America/New_York")
_UTC = ZoneInfo("UTC")
_PARQUET_SCHEMA = pa.schema([
    pa.field("timestamp", pa.timestamp("ns", tz="UTC")),
    pa.field("open",   pa.float64()),
    pa.field("high",   pa.float64()),
    pa.field("low",    pa.float64()),
    pa.field("close",  pa.float64()),
    pa.field("volume", pa.int64()),
])


def _validate_row(row: dict[str, str]) -> tuple[bool, str]:
    """Return (ok, reason). Reason is empty if ok."""
    try:
        o, h, lo, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        v = int(row["volume"])
    except (KeyError, ValueError) as e:
        return False, f"malformed numeric field: {e}"
    if not (o > 0 and h > 0 and lo > 0 and c > 0):
        return False, "non-positive price"
    if not (lo <= o <= h and lo <= c <= h and lo <= h):
        return False, f"OHLC inconsistent: O={o} H={h} L={lo} C={c}"
    if v < 0:
        return False, f"negative volume: {v}"
    return True, ""


def _row_to_record(row: dict[str, str]) -> dict[str, object]:
    """Parse a validated row into a record with UTC timestamp."""
    ts_et = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_ET)
    return {
        "timestamp": ts_et.astimezone(_UTC),
        "open":   float(row["open"]),
        "high":   float(row["high"]),
        "low":    float(row["low"]),
        "close":  float(row["close"]),
        "volume": int(row["volume"]),
    }


class FirstRateDataLoader:
    """Reads FirstRateData per-contract CSVs and writes validated parquet."""

    def __init__(self, raw_root: Path, parquet_root: Path) -> None:
        self._raw_root = raw_root
        self._parquet_root = parquet_root

    def ingest(
        self,
        symbol: str,
        quarantine_rate_threshold: float = 1.0,
    ) -> IngestSummary:
        """Walk raw_root for {symbol}_*.csv, validate, write parquet partitions.

        Idempotent: existing per-contract partitions are skipped.
        Loud failure: quarantine rate > threshold → IngestQualityError.
        Default threshold 1.0 disables the gate; production callers should pass
        a strict value (e.g. 0.001) to catch vendor regressions.
        """
        rows_written = 0
        rows_quarantined = 0
        files_processed = 0
        files_skipped = 0

        for csv_path in sorted(self._raw_root.glob(f"{symbol}_*.csv")):
            try:
                fname = parse_firstratedata_filename(csv_path)
            except ValueError:
                continue
            if fname.symbol != symbol:
                continue

            contract_root = (
                self._parquet_root / f"symbol={symbol}" / f"contract={fname.contract}"
            )
            if contract_root.exists() and any(contract_root.rglob("*.parquet")):
                files_skipped += 1
                continue

            files_processed += 1
            records_by_month: dict[tuple[int, int], list[dict[str, object]]] = {}
            with csv_path.open() as f:
                reader = csv.DictReader(f)
                total = 0
                bad = 0
                for row in reader:
                    total += 1
                    ok, reason = _validate_row(row)
                    if not ok:
                        bad += 1
                        self._write_quarantine(csv_path, row, reason)
                        continue
                    rec = _row_to_record(row)
                    ts = rec["timestamp"]
                    assert isinstance(ts, datetime)
                    key = (ts.year, ts.month)
                    records_by_month.setdefault(key, []).append(rec)

            if total > 0 and (bad / total) > quarantine_rate_threshold:
                raise IngestQualityError(
                    f"{csv_path.name}: quarantine rate {bad / total:.2%} > threshold "
                    f"{quarantine_rate_threshold:.2%} — likely vendor regression"
                )

            for (year, month), recs in records_by_month.items():
                part_dir = (
                    self._parquet_root
                    / f"symbol={symbol}"
                    / f"contract={fname.contract}"
                    / f"year={year}"
                    / f"month={month:02d}"
                )
                part_dir.mkdir(parents=True, exist_ok=True)
                table = pa.Table.from_pylist(recs, schema=_PARQUET_SCHEMA)
                pq.write_table(table, part_dir / "part-0.parquet")  # type: ignore[no-untyped-call]
                rows_written += len(recs)
            rows_quarantined += bad

        return IngestSummary(
            rows_written=rows_written,
            rows_quarantined=rows_quarantined,
            files_processed=files_processed,
            files_skipped=files_skipped,
        )

    def _write_quarantine(self, src: Path, row: dict[str, str], reason: str) -> None:
        slug = "".join(c if c.isalnum() else "_" for c in reason)[:40]
        qdir = self._parquet_root / "_quarantine" / src.stem / slug
        qdir.mkdir(parents=True, exist_ok=True)
        qpath = qdir / "rows.csv"
        write_header = not qpath.exists()
        with qpath.open("a") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if write_header:
                w.writeheader()
            w.writerow(row)
