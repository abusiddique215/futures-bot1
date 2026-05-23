# Plan 2 — Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`. Steps use `- [ ]` syntax.

**Goal:** Ship `bot.data` — CSV→parquet ingest, ratio-adjusted continuous-contract roll, local `BarAggregator`, IB live-stream skeleton, and a conformance contract that proves backtest and live emit byte-identical `Bar` streams.

**Architecture:** Synthetic-fixture-driven TDD throughout. Code is verifiable WITHOUT purchasing FirstRateData (~$200) — real backfill is a one-command later step. Per-contract parquet partitions are immutable; continuous parquet is regenerated on every roll. `BarAggregator` emits closed bars event-driven (never wall-clock). IB live stream ships as a SKELETON; full reconnect + 30s-disconnect→force-flatten lives in Plan 6 (IB Paper).

**Tech Stack:** Adds to Plan 1: `nautilus-trader>=1.227,<1.228`, `ib-async>=1.0.3`, `pyarrow>=16.0` (pyarrow.dataset for partition-pruned parquet scans).

**Scope notes:**
- v1: ingest + roll + aggregator. NO live-feed reconnection logic (that's Plan 6).
- NO real FirstRateData files needed — synthetic 3-row CSV fixtures cover all code paths.
- Plan ships the IB live-stream Protocol-style interface but the connect/reconnect machinery is stubbed; Plan 6 fills it in.
- DataQualityMonitor lives here. Quarantine sink writes to `data/quarantine/...` per spec 01 §3.7; in v1 that's just `print()` + skip — full SQLite/Telegram integration is Plan 7.

**Deliverable verification:**
- `pytest -q` ≥ 70 (Plan 1) + ~50 (Plan 2 tests) ≈ 120 passing.
- `mypy src/ tests/` strict clean.
- `ruff check src/ tests/` clean.
- `python -m bot.data.ingest --symbol MNQ --raw-root <path>` runs against synthetic fixtures and writes parquet partitions.
- Conformance test passes: identical `Bar` sequence from historical-replay path + mocked-IB live path.

---

## File Structure

```
src/bot/data/
├── __init__.py
├── dq.py                    # DQIssue dataclass + reasons enum + DataQualityMonitor
├── contract_calendar.py     # third_friday() + roll_calendar(); pure functions, no I/O
├── firstratedata.py         # FirstRateDataLoader (CSV→parquet, parquet→Bar iter)
├── continuous.py            # RollEvent + ContinuousAdjuster (ratio-adjusted)
├── aggregator.py            # BarAggregator (Tick/sub-Bar → 1m/5m Bar)
├── live_ib.py               # IBLiveBarStream SKELETON; full impl Plan 6
└── ingest.py                # CLI entry point: python -m bot.data.ingest --symbol MNQ ...

tests/
├── fixtures/                # synthetic CSVs + parquet snippets
│   ├── nq_2023z_3rows.csv
│   ├── nq_2023z_clean.csv         # full month, no anomalies
│   ├── nq_2023z_with_outlier.csv  # one 5σ outlier row
│   └── mnq_roll_pair.csv          # 2 contract files for roll test
├── test_data_dq.py
├── test_data_contract_calendar.py
├── test_data_firstratedata_filename.py
├── test_data_firstratedata_ingest.py
├── test_data_firstratedata_load.py
├── test_data_continuous_compute_ratios.py
├── test_data_continuous_adjust.py
├── test_data_continuous_roundtrip.py        # ingest → roll → continuous → byte-identical replay
├── test_data_aggregator.py
├── test_data_live_ib_skeleton.py
├── test_data_conformance.py                 # the non-negotiable §3.6 gate
└── test_data_ingest_cli.py
```

---

## Tasks

### Task 1: Bump deps (nautilus-trader, ib-async, pyarrow)

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit `[project] dependencies` block in pyproject.toml**

Find the existing `dependencies = [...]` block and replace it with:

```toml
dependencies = [
    # Plan 1 deps
    "pydantic>=2.7",
    "pyyaml>=6.0",
    # Plan 2 deps
    "nautilus-trader>=1.227,<1.228",  # pre-Plan-1 verification confirmed Py3.12/3.13 wheels exist
    "ib-async>=1.0.3",                # for IB live data feed (skeleton here; full impl Plan 6)
    "pyarrow>=16.0",                  # partitioned-parquet scans for backtest
]
```

- [ ] **Step 2: Install new deps**

```bash
source ~/.venvs/topstep-bot/bin/activate
cd "/Users/abusiddique/Library/Mobile Documents/com~apple~CloudDocs/projects/algo trade training"
pip install -e ".[dev]"
```

Expected: nautilus-trader installs (wheel, no Rust toolchain needed per pre-Plan-1 verification). ~30 sec.

- [ ] **Step 3: Verify imports + tooling**

```bash
python -c "import nautilus_trader; import ib_async; import pyarrow; print(nautilus_trader.__version__, ib_async.__version__, pyarrow.__version__)"
ruff check src/ tests/
mypy src/ tests/
pytest -q
```

Expected: prints three versions, all three checks clean, 70 tests pass (Plan 1 unaffected).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore(deps): nautilus-trader + ib-async + pyarrow for data pipeline"
```

---

### Task 2: `bot/data/` package skeleton

**Files:**
- Create: `src/bot/data/__init__.py` (content: `""\n`)
- Create: `tests/fixtures/` directory

- [ ] **Step 1: Create package marker**

Write `src/bot/data/__init__.py` with content: `""\n`

- [ ] **Step 2: Create fixtures dir**

```bash
mkdir -p tests/fixtures
touch tests/fixtures/.gitkeep
```

- [ ] **Step 3: Commit**

```bash
git add src/bot/data/__init__.py tests/fixtures/.gitkeep
git commit -m "feat(data): package skeleton"
```

---

### Task 3: `DQIssue` dataclass + `DataQualityMonitor`

**Files:**
- Create: `src/bot/data/dq.py`
- Create: `tests/test_data_dq.py`

Source: spec `01-data-pipeline.md §3.7`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_data_dq.py
"""DataQualityMonitor tests. Spec 01-data-pipeline.md §3.7."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bot.types import Bar


def _bar(t: datetime, **kw) -> Bar:
    defaults = dict(symbol="MNQ", open=100.0, high=101.0, low=99.5,
                    close=100.5, volume=10, timestamp=t, interval="1m")
    defaults.update(kw)
    return Bar(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def t0() -> datetime:
    return datetime(2026, 5, 22, 14, 30, 0, tzinfo=timezone.utc)


def test_dq_clean_bars_no_issues(t0) -> None:
    from bot.data.dq import DataQualityMonitor
    m = DataQualityMonitor(interval="1m")
    issues_a = m.check_bar(prev=None, new=_bar(t0))
    issues_b = m.check_bar(prev=_bar(t0), new=_bar(t0 + timedelta(minutes=1)))
    assert issues_a == []
    assert issues_b == []


def test_dq_detects_gap(t0) -> None:
    """Prev at t0; new at t0+5min when interval is 1m → gap of 4 missing bars."""
    from bot.data.dq import DataQualityMonitor
    m = DataQualityMonitor(interval="1m")
    prev = _bar(t0)
    new = _bar(t0 + timedelta(minutes=5))
    issues = m.check_bar(prev=prev, new=new)
    reasons = [i.reason for i in issues]
    assert "BAR_GAP" in reasons


def test_dq_detects_out_of_order(t0) -> None:
    """new.timestamp <= prev.timestamp is corrupt."""
    from bot.data.dq import DataQualityMonitor
    m = DataQualityMonitor(interval="1m")
    prev = _bar(t0 + timedelta(minutes=5))
    new = _bar(t0)  # earlier than prev
    issues = m.check_bar(prev=prev, new=new)
    reasons = [i.reason for i in issues]
    assert "OUT_OF_ORDER" in reasons


def test_dq_detects_weekend(t0) -> None:
    """Saturday 14:00 UTC is a weekend bar (Globex closed weekend daytime)."""
    from bot.data.dq import DataQualityMonitor
    m = DataQualityMonitor(interval="1m")
    sat = datetime(2026, 5, 23, 14, 0, 0, tzinfo=timezone.utc)  # Saturday
    issues = m.check_bar(prev=None, new=_bar(sat))
    reasons = [i.reason for i in issues]
    assert "WEEKEND" in reasons


def test_dq_detects_stale_repeat(t0) -> None:
    """3 consecutive bars with identical close + volume → stale feed."""
    from bot.data.dq import DataQualityMonitor
    m = DataQualityMonitor(interval="1m")
    same = dict(close=100.0, volume=5)
    b1 = _bar(t0, **same)
    b2 = _bar(t0 + timedelta(minutes=1), **same)
    b3 = _bar(t0 + timedelta(minutes=2), **same)
    m.check_bar(prev=None, new=b1)
    m.check_bar(prev=b1, new=b2)
    issues = m.check_bar(prev=b2, new=b3)
    reasons = [i.reason for i in issues]
    assert "STALE_REPEAT" in reasons


def test_dq_issue_carries_bar_ref(t0) -> None:
    """Issues hold a pointer to the offending bar for downstream logging."""
    from bot.data.dq import DataQualityMonitor
    m = DataQualityMonitor(interval="1m")
    sat = _bar(datetime(2026, 5, 23, 14, 0, 0, tzinfo=timezone.utc))
    issues = m.check_bar(prev=None, new=sat)
    assert issues[0].bar is sat
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest tests/test_data_dq.py -v
```

Expected: ModuleNotFoundError for `bot.data.dq`.

- [ ] **Step 3: Write `src/bot/data/dq.py`**

```python
# src/bot/data/dq.py
"""DataQualityMonitor — detects anomalies in incoming Bar streams.

Spec: 01-data-pipeline.md §3.7. Issues are FLAGGED for downstream logging /
quarantine; this module does NOT decide whether to drop. The driver
(historical-load or live-feed) consults the issues and chooses policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from bot.types import Bar


DQReason = Literal[
    "BAR_GAP",
    "OUT_OF_ORDER",
    "WEEKEND",
    "STALE_REPEAT",
    "OHLC_INCONSISTENT",
]


@dataclass(frozen=True)
class DQIssue:
    """A single data-quality issue. Immutable for journaling."""
    reason: DQReason
    bar: Bar
    detail: str


_INTERVAL_TO_DELTA: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
}


class DataQualityMonitor:
    """Stateful monitor that emits DQIssues on a per-bar basis.

    State tracked: last 2 (close, volume) tuples for STALE_REPEAT detection.
    """

    def __init__(self, interval: str) -> None:
        if interval not in _INTERVAL_TO_DELTA:
            raise ValueError(f"Unsupported interval: {interval!r}")
        self._interval = interval
        self._delta = _INTERVAL_TO_DELTA[interval]
        self._recent_close_vol: list[tuple[float, int]] = []

    def check_bar(self, prev: Bar | None, new: Bar) -> list[DQIssue]:
        issues: list[DQIssue] = []

        # Weekend
        if new.timestamp.weekday() in (5, 6):
            issues.append(DQIssue("WEEKEND", new, f"Bar on weekday {new.timestamp.weekday()}"))

        # OHLC consistency
        if not (new.low <= new.open <= new.high and
                new.low <= new.close <= new.high and
                new.low <= new.high):
            issues.append(DQIssue(
                "OHLC_INCONSISTENT", new,
                f"OHLC: O={new.open} H={new.high} L={new.low} C={new.close}",
            ))

        if prev is not None:
            # Out-of-order
            if new.timestamp <= prev.timestamp:
                issues.append(DQIssue(
                    "OUT_OF_ORDER", new,
                    f"new.timestamp={new.timestamp} <= prev.timestamp={prev.timestamp}",
                ))
            else:
                # Gap detection
                expected = prev.timestamp + self._delta
                if new.timestamp != expected:
                    missing = (new.timestamp - expected) // self._delta
                    issues.append(DQIssue(
                        "BAR_GAP", new,
                        f"Expected {expected}, got {new.timestamp}; ~{missing} missing bars",
                    ))

        # Stale repeat: 3 consecutive identical (close, volume)
        self._recent_close_vol.append((new.close, new.volume))
        if len(self._recent_close_vol) > 3:
            self._recent_close_vol.pop(0)
        if (len(self._recent_close_vol) == 3 and
                self._recent_close_vol[0] == self._recent_close_vol[1] == self._recent_close_vol[2]):
            issues.append(DQIssue(
                "STALE_REPEAT", new,
                f"3 consecutive bars with close={new.close}, volume={new.volume}",
            ))

        return issues
```

- [ ] **Step 4: Verify**

```bash
pytest tests/test_data_dq.py -v
ruff check src/ tests/
mypy src/ tests/
```

Expected: 6 passed; clean.

- [ ] **Step 5: Commit**

```bash
git add src/bot/data/dq.py tests/test_data_dq.py
git commit -m "feat(data): DataQualityMonitor with 5 anomaly detectors"
```

---

### Task 4: `contract_calendar.py` — third-Friday roll dates

**Files:**
- Create: `src/bot/data/contract_calendar.py`
- Create: `tests/test_data_contract_calendar.py`

Source: spec `01-data-pipeline.md §3.2` (CME H/M/U/Z, third Friday).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_data_contract_calendar.py
"""contract_calendar: roll dates for NQ/MNQ. Spec 01 §3.2."""
from __future__ import annotations

from datetime import date


def test_third_friday_known_dates() -> None:
    from bot.data.contract_calendar import third_friday
    # Known historical roll dates
    assert third_friday(2023, 12) == date(2023, 12, 15)
    assert third_friday(2024, 3)  == date(2024, 3, 15)
    assert third_friday(2024, 6)  == date(2024, 6, 21)
    assert third_friday(2024, 9)  == date(2024, 9, 20)
    assert third_friday(2026, 3)  == date(2026, 3, 20)


def test_third_friday_when_month_starts_on_friday() -> None:
    """November 2024 starts on a Friday; third Friday is the 15th."""
    from bot.data.contract_calendar import third_friday
    assert third_friday(2024, 11) == date(2024, 11, 15)


def test_contract_code_to_month() -> None:
    from bot.data.contract_calendar import CONTRACT_MONTHS
    assert CONTRACT_MONTHS == {"H": 3, "M": 6, "U": 9, "Z": 12}


def test_roll_calendar_quarterly() -> None:
    from bot.data.contract_calendar import roll_calendar
    dates = roll_calendar(start_year=2023, end_year=2024)
    # 8 quarterly dates: 2023 H/M/U/Z + 2024 H/M/U/Z
    assert len(dates) == 8
    assert dates[0] == date(2023, 3, 17)   # 2023H
    assert dates[-1] == date(2024, 12, 20)  # 2024Z


def test_parse_contract_code() -> None:
    from bot.data.contract_calendar import parse_contract_code
    assert parse_contract_code("2023Z") == (2023, 12)
    assert parse_contract_code("2024H") == (2024, 3)
    assert parse_contract_code("2025U") == (2025, 9)


def test_parse_contract_code_rejects_bad_input() -> None:
    import pytest
    from bot.data.contract_calendar import parse_contract_code
    with pytest.raises(ValueError):
        parse_contract_code("2023X")  # X is not a valid CME month code
    with pytest.raises(ValueError):
        parse_contract_code("23Z")     # year must be 4 digits
```

- [ ] **Step 2: Run + verify failure**

Expected: `ModuleNotFoundError: No module named 'bot.data.contract_calendar'`

- [ ] **Step 3: Write implementation**

```python
# src/bot/data/contract_calendar.py
"""CME quarterly contract calendar for NQ/MNQ.

H=Mar, M=Jun, U=Sep, Z=Dec. Roll on third Friday of contract month.
Spec: 01-data-pipeline.md §3.2.
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Final


CONTRACT_MONTHS: Final[dict[str, int]] = {"H": 3, "M": 6, "U": 9, "Z": 12}
_MONTH_TO_CODE: Final[dict[int, str]] = {v: k for k, v in CONTRACT_MONTHS.items()}


def third_friday(year: int, month: int) -> date:
    """Return the third Friday of the given month.

    Algorithm: Find the first Friday, add 14 days. Friday is weekday() == 4.
    """
    first_of_month = date(year, month, 1)
    first_friday_offset = (4 - first_of_month.weekday()) % 7
    return date(year, month, 1 + first_friday_offset + 14)


def roll_calendar(start_year: int, end_year: int) -> list[date]:
    """All quarterly roll dates between [start_year, end_year], inclusive."""
    dates: list[date] = []
    for year in range(start_year, end_year + 1):
        for month in (3, 6, 9, 12):
            dates.append(third_friday(year, month))
    return dates


def parse_contract_code(code: str) -> tuple[int, int]:
    """Parse a FirstRateData contract suffix like "2023Z" → (2023, 12).

    Raises ValueError on malformed input.
    """
    if len(code) != 5:
        raise ValueError(f"Contract code must be 5 chars (YYYY+M), got {code!r}")
    year_str, month_code = code[:4], code[4]
    try:
        year = int(year_str)
    except ValueError as e:
        raise ValueError(f"Year part of {code!r} not an integer") from e
    if month_code not in CONTRACT_MONTHS:
        raise ValueError(f"Month code {month_code!r} not in {sorted(CONTRACT_MONTHS)}")
    return (year, CONTRACT_MONTHS[month_code])


def format_contract_code(year: int, month: int) -> str:
    """Inverse of parse_contract_code: (2023, 12) → "2023Z"."""
    if month not in _MONTH_TO_CODE:
        raise ValueError(f"Month {month} not a quarterly contract month")
    return f"{year}{_MONTH_TO_CODE[month]}"
```

- [ ] **Step 4: Verify**

```bash
pytest tests/test_data_contract_calendar.py -v
ruff check src/ tests/
mypy src/ tests/
```

Expected: 6 passed; clean.

- [ ] **Step 5: Commit**

```bash
git add src/bot/data/contract_calendar.py tests/test_data_contract_calendar.py
git commit -m "feat(data): contract_calendar (third-Friday roll, parse_contract_code)"
```

---

### Task 5: FirstRateData filename parser

**Files:**
- Create: `src/bot/data/firstratedata.py` (initial — just filename parsing)
- Create: `tests/test_data_firstratedata_filename.py`

Source: spec `01-data-pipeline.md §3.1` (filename convention).

- [ ] **Step 1: Failing tests**

```python
# tests/test_data_firstratedata_filename.py
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
    with pytest.raises(ValueError):
        parse_firstratedata_filename("garbage.csv")
    with pytest.raises(ValueError):
        parse_firstratedata_filename("NQ_2023X_1min.csv")  # bad month code
    with pytest.raises(ValueError):
        parse_firstratedata_filename("NQ_2023Z_5min.csv")  # we don't support 5-min input
```

- [ ] **Step 2: Failure check**

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implementation**

```python
# src/bot/data/firstratedata.py
"""FirstRateData CSV loader.

Filename convention: `<SYMBOL>_<YYYY><M>_1min.csv` (spec 01 §3.1).
This module is the only one that knows the FirstRateData on-disk format;
downstream (continuous adjuster, backtest) sees only Bar instances.
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
```

- [ ] **Step 4: Verify**

```bash
pytest tests/test_data_firstratedata_filename.py -v
ruff check src/ tests/
mypy src/ tests/
```

Expected: 4 passed; clean.

- [ ] **Step 5: Commit**

```bash
git add src/bot/data/firstratedata.py tests/test_data_firstratedata_filename.py
git commit -m "feat(data): FirstRateData filename parser"
```

---

### Task 6: FirstRateData CSV → parquet ingest

**Files:**
- Modify: `src/bot/data/firstratedata.py` (add `FirstRateDataLoader`)
- Create: `tests/fixtures/nq_2023z_clean.csv` (synthetic; 3 rows)
- Create: `tests/fixtures/nq_2023z_bad_ohlc.csv` (synthetic; 1 bad row)
- Create: `tests/test_data_firstratedata_ingest.py`

Source: spec `01-data-pipeline.md §3.1` (schema validation + parquet layout).

- [ ] **Step 1: Create synthetic fixture CSVs**

Write `tests/fixtures/nq_2023z_clean.csv`:

```csv
timestamp,open,high,low,close,volume
2023-12-15 09:30:00,16500.00,16510.00,16498.00,16505.00,1200
2023-12-15 09:31:00,16505.00,16515.00,16503.00,16512.00,800
2023-12-15 09:32:00,16512.00,16518.00,16510.00,16515.00,950
```

Write `tests/fixtures/nq_2023z_bad_ohlc.csv`:

```csv
timestamp,open,high,low,close,volume
2023-12-15 09:30:00,16500.00,16510.00,16498.00,16505.00,1200
2023-12-15 09:31:00,16505.00,16490.00,16503.00,16512.00,800
```

(Row 2 has high=16490 < open=16505 — OHLC inconsistent.)

- [ ] **Step 2: Failing tests**

```python
# tests/test_data_firstratedata_ingest.py
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

    # Verify partition exists
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
    # Quarantine sidecar should exist
    quarantine_root = tmp_path / "parquet" / "_quarantine"
    quarantine_files = list(quarantine_root.rglob("*.csv"))
    assert len(quarantine_files) >= 1


def test_ingest_fails_loud_when_high_quarantine_rate(tmp_path) -> None:
    """If >0.1% of rows quarantine, ingest raises (vendor regression signal)."""
    from bot.data.firstratedata import FirstRateDataLoader, IngestQualityError
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    src = raw_root / "NQ_2023Z_1min.csv"
    # 2 rows, 1 bad = 50% quarantine rate. Well above 0.1%.
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
    assert summary2.rows_written == 0  # no new rows; already ingested
    assert summary2.files_skipped == 1
```

- [ ] **Step 3: Failure check**

Expected: ImportError for `FirstRateDataLoader`.

- [ ] **Step 4: Implementation**

Append to `src/bot/data/firstratedata.py`:

```python


# ---- Loader ----------------------------------------------------------------

import csv
from dataclasses import field
from datetime import datetime
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq


class IngestQualityError(Exception):
    """Raised when ingest quarantine rate exceeds threshold."""


@dataclass(frozen=True)
class IngestSummary:
    rows_written: int
    rows_quarantined: int
    files_processed: int
    files_skipped: int


_ET = ZoneInfo("America/New_York")
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
        o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        v = int(row["volume"])
    except (KeyError, ValueError) as e:
        return False, f"malformed numeric field: {e}"
    if not (o > 0 and h > 0 and l > 0 and c > 0):
        return False, "non-positive price"
    if not (l <= o <= h and l <= c <= h and l <= h):
        return False, f"OHLC inconsistent: O={o} H={h} L={l} C={c}"
    if v < 0:
        return False, f"negative volume: {v}"
    return True, ""


def _row_to_record(row: dict[str, str]) -> dict[str, object]:
    """Parse a validated row into a record with UTC timestamp."""
    ts_et = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_ET)
    return {
        "timestamp": ts_et.astimezone(ZoneInfo("UTC")),
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
        quarantine_rate_threshold: float = 0.001,  # 0.1%
    ) -> IngestSummary:
        """Walk raw_root for {symbol}_*.csv, validate, write parquet partitions.

        Idempotent: existing per-month partitions are skipped (not re-validated).
        Loud failure: quarantine rate > threshold → IngestQualityError.
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

            # Check if partition already exists for this contract; skip if so.
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
                    key = (ts.year, ts.month)  # type: ignore[union-attr]
                    records_by_month.setdefault(key, []).append(rec)

            # Quality gate per file
            if total > 0 and (bad / total) > quarantine_rate_threshold:
                raise IngestQualityError(
                    f"{csv_path.name}: quarantine rate {bad / total:.2%} > threshold "
                    f"{quarantine_rate_threshold:.2%} — likely vendor regression"
                )

            # Write per-month parquet partitions
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
                pq.write_table(table, part_dir / "part-0.parquet")
                rows_written += len(recs)
            rows_quarantined += bad

        return IngestSummary(
            rows_written=rows_written,
            rows_quarantined=rows_quarantined,
            files_processed=files_processed,
            files_skipped=files_skipped,
        )

    def _write_quarantine(self, src: Path, row: dict[str, str], reason: str) -> None:
        """Append the bad row to a per-reason quarantine CSV under _quarantine/."""
        # Reason as folder-safe slug
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
```

- [ ] **Step 5: Verify**

```bash
pytest tests/test_data_firstratedata_ingest.py -v
ruff check src/ tests/
mypy src/ tests/
```

Expected: 4 passed; clean. (If ruff flags unused imports from the new module, re-order or remove as needed.)

- [ ] **Step 6: Commit**

```bash
git add src/bot/data/firstratedata.py tests/fixtures/nq_2023z_clean.csv \
        tests/fixtures/nq_2023z_bad_ohlc.csv tests/test_data_firstratedata_ingest.py
git commit -m "feat(data): FirstRateDataLoader.ingest with quarantine + quality gate"
```

---

### Task 7: FirstRateData parquet → Bar iterator (`.load()`)

**Files:**
- Modify: `src/bot/data/firstratedata.py` (add `load` method)
- Create: `tests/test_data_firstratedata_load.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_data_firstratedata_load.py
"""FirstRateDataLoader.load(): parquet → Bar iterator."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _setup_ingested(tmp_path) -> Path:
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
        start=datetime(2023, 12, 15, 0, 0, tzinfo=timezone.utc),
        end=datetime(2023, 12, 16, 0, 0, tzinfo=timezone.utc),
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
        start=datetime(2023, 12, 15, 14, 31, tzinfo=timezone.utc),
        end=datetime(2023, 12, 15, 14, 32, tzinfo=timezone.utc),
    ))
    assert len(bars) == 1
    assert bars[0].open == 16505.00
```

- [ ] **Step 2: Failure check** — `AttributeError: ... 'load'`

- [ ] **Step 3: Add `.load()` to `FirstRateDataLoader`**

Append the following method INSIDE the `FirstRateDataLoader` class body (after `_write_quarantine`):

```python

    def load(
        self,
        symbol: str,
        contract: str | None,
        start: datetime,
        end: datetime,
    ) -> "Iterator[Bar]":
        """Yield Bars in [start, end] for the given symbol+contract.

        If contract is None, loads from continuous parquet (written by
        ContinuousAdjuster, task 12). For now (task 7), contract is required.
        """
        from bot.types import Bar
        import pyarrow.dataset as ds

        if contract is None:
            raise NotImplementedError(
                "Continuous-series loading needs ContinuousAdjuster (task 12)"
            )
        root = self._parquet_root / f"symbol={symbol}" / f"contract={contract}"
        if not root.exists():
            return  # nothing ingested for this contract; yield nothing

        dataset = ds.dataset(str(root), format="parquet")
        table = dataset.to_table(
            filter=(ds.field("timestamp") >= pa.scalar(start)) &
                   (ds.field("timestamp") <= pa.scalar(end)),
        )
        # Sort by timestamp (partitions are by year/month but within partition may shuffle)
        table = table.sort_by([("timestamp", "ascending")])
        for row in table.to_pylist():
            yield Bar(
                symbol=symbol,
                open=row["open"], high=row["high"], low=row["low"],
                close=row["close"], volume=row["volume"],
                timestamp=row["timestamp"], interval="1m",
            )
```

Also add `from typing import Iterator` near the top of the file if not already present.

- [ ] **Step 4: Verify**

```bash
pytest tests/test_data_firstratedata_load.py -v
ruff check src/ tests/
mypy src/ tests/
```

Expected: 2 passed; clean.

- [ ] **Step 5: Commit**

```bash
git add src/bot/data/firstratedata.py tests/test_data_firstratedata_load.py
git commit -m "feat(data): FirstRateDataLoader.load (parquet → Bar iterator)"
```

---

### Task 8: `RollEvent` dataclass + `ContinuousAdjuster.compute_ratios`

**Files:**
- Create: `src/bot/data/continuous.py`
- Create: `tests/test_data_continuous_compute_ratios.py`
- Create: `tests/fixtures/mnq_roll_pair_2023z.csv` (single row at roll close)
- Create: `tests/fixtures/mnq_roll_pair_2024h.csv` (single row at roll close)

Source: spec `01-data-pipeline.md §3.2` (ratio-adjusted roll math).

- [ ] **Step 1: Fixtures**

`tests/fixtures/mnq_roll_pair_2023z.csv`:

```csv
timestamp,open,high,low,close,volume
2023-12-15 15:59:00,16500.00,16500.00,16500.00,16500.00,1000
```

`tests/fixtures/mnq_roll_pair_2024h.csv`:

```csv
timestamp,open,high,low,close,volume
2023-12-15 15:59:00,16600.00,16600.00,16600.00,16600.00,500
```

(Both contracts have a single bar at the roll close. Old=16500, New=16600. Ratio = 16500/16600 ≈ 0.99398.)

- [ ] **Step 2: Failing tests**

```python
# tests/test_data_continuous_compute_ratios.py
"""ContinuousAdjuster.compute_ratios. Spec 01 §3.2."""
from __future__ import annotations

from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _setup_two_contracts(tmp_path) -> Path:
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


def test_compute_ratios_two_contracts(tmp_path) -> None:
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
    # Ratio = c_old / c_new
    assert e.ratio == 16500.0 / 16600.0


def test_compute_ratios_empty_when_one_contract(tmp_path) -> None:
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
```

- [ ] **Step 3: Failure check** — ModuleNotFoundError

- [ ] **Step 4: Write `src/bot/data/continuous.py`**

```python
# src/bot/data/continuous.py
"""ContinuousAdjuster — ratio-adjusted roll for NQ/MNQ futures.

Spec: 01-data-pipeline.md §3.2.

Roll on the third Friday of each contract month. Scale all OHLC of the
expiring contract (and recursively all older ones) by C_new/C_old so the
series equals the front-month price at every seam. Volume is unscaled.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pyarrow.dataset as ds

from bot.data.contract_calendar import parse_contract_code


@dataclass(frozen=True)
class RollEvent:
    """Audit trail of a single contract roll."""
    symbol: str
    roll_date: date
    old_contract: str        # "2023Z"
    new_contract: str        # "2024H"
    c_old_close: float
    c_new_close: float
    ratio: float             # c_old / c_new
    cumulative_scale: float  # product of (c_new/c_old) for this roll and all later rolls


def _list_contracts(parquet_root: Path, symbol: str) -> list[str]:
    """List all contract codes ingested for `symbol`, sorted chronologically.

    e.g. ["2023H", "2023M", "2023U", "2023Z", "2024H"].
    """
    sym_root = parquet_root / f"symbol={symbol}"
    if not sym_root.exists():
        return []
    contracts: list[str] = []
    for p in sym_root.iterdir():
        if p.is_dir() and p.name.startswith("contract="):
            contracts.append(p.name.removeprefix("contract="))
    return sorted(contracts, key=parse_contract_code)


def _read_last_bar_close(parquet_root: Path, symbol: str, contract: str) -> tuple[date, float] | None:
    """Read the last (timestamp.date, close) of a contract's parquet partitions."""
    root = parquet_root / f"symbol={symbol}" / f"contract={contract}"
    if not root.exists():
        return None
    dataset = ds.dataset(str(root), format="parquet")
    table = dataset.to_table(columns=["timestamp", "close"]).sort_by(
        [("timestamp", "descending")]
    )
    if table.num_rows == 0:
        return None
    last = table.slice(0, 1).to_pylist()[0]
    return (last["timestamp"].date(), last["close"])


class ContinuousAdjuster:
    """Build a continuous, ratio-adjusted series from per-contract parquet."""

    def __init__(self, parquet_root: Path) -> None:
        self._parquet_root = parquet_root

    def compute_ratios(self, symbol: str) -> list[RollEvent]:
        """For each consecutive contract pair, find roll-day close of both
        and emit a RollEvent. Roll date is the LAST date of the old contract
        in the parquet, OR the contemporaneous date of the new contract —
        we use the old-contract last-bar date as the seam.
        """
        contracts = _list_contracts(self._parquet_root, symbol)
        if len(contracts) < 2:
            return []

        events: list[RollEvent] = []
        for old_code, new_code in zip(contracts[:-1], contracts[1:], strict=True):
            old_close_info = _read_last_bar_close(self._parquet_root, symbol, old_code)
            if old_close_info is None:
                continue
            old_date, c_old = old_close_info

            new_close_info = self._read_close_on_date(symbol, new_code, old_date)
            if new_close_info is None:
                # Fall back: use new contract's first bar close
                new_close_info = self._read_first_bar_close(symbol, new_code)
            if new_close_info is None:
                continue
            c_new = new_close_info

            events.append(RollEvent(
                symbol=symbol,
                roll_date=old_date,
                old_contract=old_code,
                new_contract=new_code,
                c_old_close=c_old,
                c_new_close=c_new,
                ratio=c_old / c_new,
                cumulative_scale=1.0,  # filled in by adjust() (task 9)
            ))
        return events

    def _read_close_on_date(self, symbol: str, contract: str, on: date) -> float | None:
        root = self._parquet_root / f"symbol={symbol}" / f"contract={contract}"
        if not root.exists():
            return None
        dataset = ds.dataset(str(root), format="parquet")
        # Filter: timestamp.date() == on. Easiest done in pyarrow with a partition prune.
        table = dataset.to_table(columns=["timestamp", "close"])
        rows = [r for r in table.to_pylist() if r["timestamp"].date() == on]
        if not rows:
            return None
        # Take the LAST close on that date
        rows.sort(key=lambda r: r["timestamp"])
        return rows[-1]["close"]

    def _read_first_bar_close(self, symbol: str, contract: str) -> float | None:
        root = self._parquet_root / f"symbol={symbol}" / f"contract={contract}"
        if not root.exists():
            return None
        dataset = ds.dataset(str(root), format="parquet")
        table = dataset.to_table(columns=["timestamp", "close"]).sort_by(
            [("timestamp", "ascending")]
        )
        if table.num_rows == 0:
            return None
        return table.slice(0, 1).to_pylist()[0]["close"]
```

- [ ] **Step 5: Verify**

```bash
pytest tests/test_data_continuous_compute_ratios.py -v
ruff check src/ tests/
mypy src/ tests/
```

Expected: 3 passed; clean.

- [ ] **Step 6: Commit**

```bash
git add src/bot/data/continuous.py tests/test_data_continuous_compute_ratios.py \
        tests/fixtures/mnq_roll_pair_2023z.csv tests/fixtures/mnq_roll_pair_2024h.csv
git commit -m "feat(data): ContinuousAdjuster.compute_ratios + RollEvent"
```

---

### Task 9: `ContinuousAdjuster.adjust` — apply cumulative scales

**Files:**
- Modify: `src/bot/data/continuous.py`
- Create: `tests/test_data_continuous_adjust.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_data_continuous_adjust.py
"""ContinuousAdjuster.adjust — cumulative ratio application. Spec 01 §3.2 worked example."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from bot.types import Bar

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _bar(contract: str, ts: datetime, close: float, volume: int = 1000) -> Bar:
    return Bar(symbol="MNQ", open=close, high=close, low=close, close=close,
               volume=volume, timestamp=ts, interval="1m")


def test_adjust_single_roll_scales_old_contract() -> None:
    """Worked example: c_old=16500, c_new=16600 → scale OLD bars by 16600/16500."""
    from bot.data.continuous import ContinuousAdjuster, RollEvent
    from datetime import date

    rolls = [RollEvent(symbol="MNQ", roll_date=date(2023, 12, 15),
                       old_contract="2023Z", new_contract="2024H",
                       c_old_close=16500.0, c_new_close=16600.0,
                       ratio=16500.0 / 16600.0,
                       cumulative_scale=16600.0 / 16500.0)]

    bars_by_contract = {
        "2023Z": [_bar("2023Z", datetime(2023, 12, 15, 14, 30, tzinfo=timezone.utc), 16300.0)],
        "2024H": [_bar("2024H", datetime(2024, 3, 15, 14, 30, tzinfo=timezone.utc), 17000.0)],
    }

    adjusted = list(ContinuousAdjuster.adjust_with_rolls(bars_by_contract, rolls))
    # 2023Z bar at 16300 × (16600/16500) ≈ 16398.79
    z_bar = next(b for b in adjusted if b.timestamp.year == 2023)
    h_bar = next(b for b in adjusted if b.timestamp.year == 2024)
    assert z_bar.close == pytest.approx(16300.0 * 16600.0 / 16500.0, rel=1e-6)
    # Current contract (2024H) bars are UNSCALED
    assert h_bar.close == 17000.0
    # Volume is unchanged for both
    assert z_bar.volume == 1000
    assert h_bar.volume == 1000


def test_adjust_multi_roll_cumulative_scaling() -> None:
    """Three contracts c1→c2→c3 with two rolls. c1 bars scaled by (c2/c1)*(c3/c2)."""
    from bot.data.continuous import ContinuousAdjuster, RollEvent
    from datetime import date

    # Rolls (newest first when computing cumulative_scale, but we list oldest first here)
    rolls = [
        RollEvent(symbol="MNQ", roll_date=date(2023, 9, 15),
                  old_contract="2023U", new_contract="2023Z",
                  c_old_close=14000.0, c_new_close=15000.0,
                  ratio=14000.0 / 15000.0,
                  cumulative_scale=(15000.0 / 14000.0) * (16600.0 / 16500.0)),
        RollEvent(symbol="MNQ", roll_date=date(2023, 12, 15),
                  old_contract="2023Z", new_contract="2024H",
                  c_old_close=16500.0, c_new_close=16600.0,
                  ratio=16500.0 / 16600.0,
                  cumulative_scale=16600.0 / 16500.0),
    ]

    bars_by_contract = {
        "2023U": [_bar("2023U", datetime(2023, 9, 15, 14, 30, tzinfo=timezone.utc), 13000.0)],
        "2023Z": [_bar("2023Z", datetime(2023, 12, 15, 14, 30, tzinfo=timezone.utc), 16300.0)],
        "2024H": [_bar("2024H", datetime(2024, 3, 15, 14, 30, tzinfo=timezone.utc), 17000.0)],
    }

    adjusted = list(ContinuousAdjuster.adjust_with_rolls(bars_by_contract, rolls))
    u_bar = next(b for b in adjusted if b.timestamp.year == 2023 and b.timestamp.month == 9)
    z_bar = next(b for b in adjusted if b.timestamp.year == 2023 and b.timestamp.month == 12)
    # u_bar scaled by (15000/14000) * (16600/16500)
    expected_u = 13000.0 * (15000.0 / 14000.0) * (16600.0 / 16500.0)
    assert u_bar.close == pytest.approx(expected_u, rel=1e-6)
    # z_bar scaled by (16600/16500)
    expected_z = 16300.0 * (16600.0 / 16500.0)
    assert z_bar.close == pytest.approx(expected_z, rel=1e-6)


def test_volume_not_scaled() -> None:
    from bot.data.continuous import ContinuousAdjuster, RollEvent
    from datetime import date

    rolls = [RollEvent(symbol="MNQ", roll_date=date(2023, 12, 15),
                       old_contract="2023Z", new_contract="2024H",
                       c_old_close=16500.0, c_new_close=16600.0,
                       ratio=16500.0 / 16600.0,
                       cumulative_scale=16600.0 / 16500.0)]
    bars_by_contract = {
        "2023Z": [_bar("2023Z", datetime(2023, 12, 15, 14, 30, tzinfo=timezone.utc),
                       16300.0, volume=42)],
        "2024H": [_bar("2024H", datetime(2024, 3, 15, 14, 30, tzinfo=timezone.utc),
                       17000.0, volume=99)],
    }
    adjusted = list(ContinuousAdjuster.adjust_with_rolls(bars_by_contract, rolls))
    z_vol = next(b for b in adjusted if b.timestamp.year == 2023).volume
    h_vol = next(b for b in adjusted if b.timestamp.year == 2024).volume
    assert z_vol == 42
    assert h_vol == 99
```

- [ ] **Step 2: Failure check**

Expected: `AttributeError: ... 'adjust_with_rolls'` or class-level missing.

- [ ] **Step 3: Add `adjust_with_rolls` to `ContinuousAdjuster`**

Append inside `ContinuousAdjuster` class:

```python

    @staticmethod
    def adjust_with_rolls(
        bars_by_contract: dict[str, list[Bar]],
        rolls: list[RollEvent],
    ) -> "Iterator[Bar]":
        """Apply each roll's cumulative_scale to its old_contract bars.

        rolls must be sorted oldest-first. cumulative_scale of the newest roll
        is `c_new/c_old` of that roll alone; older rolls multiply their own
        ratio inverse on top. The newest contract's bars are unscaled.

        Yields adjusted Bars in chronological order across all contracts.
        """
        # Build a per-contract scale factor lookup.
        # Newest contract has scale = 1.0.
        # Old contract of the newest roll has scale = newest_roll.cumulative_scale.
        # Old contract of the 2nd-newest roll has scale = 2nd-newest.cumulative_scale.
        # etc.
        contract_scale: dict[str, float] = {}
        if rolls:
            # Newest contract is `rolls[-1].new_contract`
            contract_scale[rolls[-1].new_contract] = 1.0
            for r in rolls:
                contract_scale[r.old_contract] = r.cumulative_scale
        else:
            for c in bars_by_contract:
                contract_scale[c] = 1.0

        # Yield in chronological order across all contracts
        all_bars: list[Bar] = []
        for contract, bars in bars_by_contract.items():
            scale = contract_scale.get(contract, 1.0)
            for b in bars:
                if scale == 1.0:
                    all_bars.append(b)
                else:
                    # Replace OHLC; volume unchanged
                    all_bars.append(Bar(
                        symbol=b.symbol,
                        open=b.open * scale,
                        high=b.high * scale,
                        low=b.low * scale,
                        close=b.close * scale,
                        volume=b.volume,
                        timestamp=b.timestamp,
                        interval=b.interval,
                    ))
        all_bars.sort(key=lambda b: b.timestamp)
        yield from all_bars
```

Also import `Bar` and `Iterator` at the top of `continuous.py`:

```python
from typing import Iterator

from bot.types import Bar
```

- [ ] **Step 4: Verify**

```bash
pytest tests/test_data_continuous_adjust.py -v
ruff check src/ tests/
mypy src/ tests/
```

Expected: 3 passed; clean.

- [ ] **Step 5: Commit**

```bash
git add src/bot/data/continuous.py tests/test_data_continuous_adjust.py
git commit -m "feat(data): ContinuousAdjuster.adjust_with_rolls (cumulative ratio scaling)"
```

---

### Task 10: ContinuousAdjuster.write_continuous (parquet + roll_events sidecar)

**Files:**
- Modify: `src/bot/data/continuous.py`
- Create: `tests/test_data_continuous_roundtrip.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_data_continuous_roundtrip.py
"""End-to-end roll roundtrip: ingest two contracts, write continuous, read back."""
from __future__ import annotations

from pathlib import Path

import pytest

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _setup_two(tmp_path) -> Path:
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


def test_continuous_at_seam_equals_new_contract_close(tmp_path) -> None:
    """Spec 01 §3.2: 'the most recent bar in the continuous series equals
    the most recent bar of the live front-month contract'."""
    from bot.data.continuous import ContinuousAdjuster
    from bot.data.firstratedata import FirstRateDataLoader
    from datetime import datetime, timezone

    parquet_root = _setup_two(tmp_path)
    adj = ContinuousAdjuster(parquet_root=parquet_root)
    adj.write_continuous(symbol="MNQ")

    loader = FirstRateDataLoader(raw_root=tmp_path / "raw", parquet_root=parquet_root)
    # Read continuous via load() with contract=None? Or directly?
    # For now: read from parquet directly to verify the file.
    import pyarrow.dataset as ds
    cont = ds.dataset(str(parquet_root / "continuous" / "symbol=MNQ"), format="parquet")
    table = cont.to_table().sort_by([("timestamp", "ascending")])
    rows = table.to_pylist()
    # Newest contract's bar = $16600 (unscaled)
    assert rows[-1]["close"] == pytest.approx(16600.0)
    # Older contract's bar scaled by 16600/16500 → 16500 * (16600/16500) = 16600
    # (since this fixture has BOTH old and new at the seam at the same price after scaling)
    assert rows[0]["close"] == pytest.approx(16500.0 * (16600.0 / 16500.0))
```

- [ ] **Step 2: Failure check** — `AttributeError` on `write_continuous`

- [ ] **Step 3: Add `write_continuous`**

Append inside `ContinuousAdjuster`:

```python

    def write_continuous(self, symbol: str) -> None:
        """Compute rolls, apply adjustments, write to continuous/symbol=<>/.

        Also writes a roll_events.parquet sidecar for audit.
        """
        import pyarrow as pa
        import pyarrow.parquet as pq

        rolls_raw = self.compute_ratios(symbol)
        # Compute cumulative_scale: newest roll has cs = c_new/c_old.
        # Older rolls multiply their inverse-ratio on top.
        rolls: list[RollEvent] = []
        cumulative = 1.0
        for r in reversed(rolls_raw):
            cumulative *= (r.c_new_close / r.c_old_close)
            rolls.append(RollEvent(
                symbol=r.symbol, roll_date=r.roll_date,
                old_contract=r.old_contract, new_contract=r.new_contract,
                c_old_close=r.c_old_close, c_new_close=r.c_new_close,
                ratio=r.ratio, cumulative_scale=cumulative,
            ))
        rolls.reverse()  # back to oldest-first

        # Load all per-contract bars for this symbol
        bars_by_contract: dict[str, list[Bar]] = {}
        contracts = _list_contracts(self._parquet_root, symbol)
        for c in contracts:
            from bot.data.firstratedata import FirstRateDataLoader
            from datetime import datetime, timezone
            loader = FirstRateDataLoader(
                raw_root=self._parquet_root,  # not used by load()
                parquet_root=self._parquet_root,
            )
            bars = list(loader.load(
                symbol=symbol, contract=c,
                start=datetime(1970, 1, 1, tzinfo=timezone.utc),
                end=datetime(2099, 12, 31, tzinfo=timezone.utc),
            ))
            bars_by_contract[c] = bars

        # Apply adjustments
        adjusted = list(self.adjust_with_rolls(bars_by_contract, rolls))

        # Write continuous parquet, partitioned by year/month
        cont_root = self._parquet_root / "continuous" / f"symbol={symbol}"
        bars_by_ym: dict[tuple[int, int], list[Bar]] = {}
        for b in adjusted:
            key = (b.timestamp.year, b.timestamp.month)
            bars_by_ym.setdefault(key, []).append(b)
        schema = pa.schema([
            pa.field("timestamp", pa.timestamp("ns", tz="UTC")),
            pa.field("open",   pa.float64()),
            pa.field("high",   pa.float64()),
            pa.field("low",    pa.float64()),
            pa.field("close",  pa.float64()),
            pa.field("volume", pa.int64()),
        ])
        for (year, month), bars in bars_by_ym.items():
            part_dir = cont_root / f"year={year}" / f"month={month:02d}"
            part_dir.mkdir(parents=True, exist_ok=True)
            recs = [{
                "timestamp": b.timestamp,
                "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                "volume": b.volume,
            } for b in bars]
            table = pa.Table.from_pylist(recs, schema=schema)
            pq.write_table(table, part_dir / "part-0.parquet")

        # Sidecar: roll_events.parquet
        roll_schema = pa.schema([
            pa.field("symbol", pa.string()),
            pa.field("roll_date", pa.date32()),
            pa.field("old_contract", pa.string()),
            pa.field("new_contract", pa.string()),
            pa.field("c_old_close", pa.float64()),
            pa.field("c_new_close", pa.float64()),
            pa.field("ratio", pa.float64()),
            pa.field("cumulative_scale", pa.float64()),
        ])
        if rolls:
            recs = [{
                "symbol": r.symbol, "roll_date": r.roll_date,
                "old_contract": r.old_contract, "new_contract": r.new_contract,
                "c_old_close": r.c_old_close, "c_new_close": r.c_new_close,
                "ratio": r.ratio, "cumulative_scale": r.cumulative_scale,
            } for r in rolls]
            table = pa.Table.from_pylist(recs, schema=roll_schema)
            (self._parquet_root / "continuous").mkdir(parents=True, exist_ok=True)
            pq.write_table(
                table,
                self._parquet_root / "continuous" / "roll_events.parquet",
            )
```

- [ ] **Step 4: Verify**

```bash
pytest tests/test_data_continuous_roundtrip.py -v
ruff check src/ tests/
mypy src/ tests/
```

Expected: 2 passed; clean.

- [ ] **Step 5: Commit**

```bash
git add src/bot/data/continuous.py tests/test_data_continuous_roundtrip.py
git commit -m "feat(data): ContinuousAdjuster.write_continuous + roll_events audit"
```

---

### Task 11: `BarAggregator`

**Files:**
- Create: `src/bot/data/aggregator.py`
- Create: `tests/test_data_aggregator.py`

Source: spec `01-data-pipeline.md §3.4` (closed-bar semantics, event-driven emit).

- [ ] **Step 1: Failing tests**

```python
# tests/test_data_aggregator.py
"""BarAggregator: aggregate sub-bars into 1m/5m. Spec 01 §3.4."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bot.types import Tick


def _tick(t: datetime, price: float, size: int = 1) -> Tick:
    return Tick(symbol="MNQ", price=price, size=size, timestamp=t)


@pytest.fixture
def t0() -> datetime:
    return datetime(2026, 5, 22, 14, 30, 0, tzinfo=timezone.utc)


def test_first_tick_starts_bar_no_emit(t0) -> None:
    from bot.data.aggregator import BarAggregator
    agg = BarAggregator(interval="1m", symbol="MNQ")
    out = agg.feed(_tick(t0, 100.0))
    assert out is None  # first tick opens the bar; no closed bar yet


def test_tick_within_bar_no_emit(t0) -> None:
    from bot.data.aggregator import BarAggregator
    agg = BarAggregator(interval="1m", symbol="MNQ")
    agg.feed(_tick(t0, 100.0))
    out = agg.feed(_tick(t0 + timedelta(seconds=30), 101.0))
    assert out is None


def test_tick_crossing_boundary_emits_closed_bar(t0) -> None:
    """Tick at t0+60s closes the [t0, t0+60s) bar."""
    from bot.data.aggregator import BarAggregator
    agg = BarAggregator(interval="1m", symbol="MNQ")
    agg.feed(_tick(t0, 100.0))                              # open
    agg.feed(_tick(t0 + timedelta(seconds=30), 102.0))      # higher
    agg.feed(_tick(t0 + timedelta(seconds=45), 99.5))       # lower
    closed = agg.feed(_tick(t0 + timedelta(seconds=60), 101.0))
    assert closed is not None
    assert closed.timestamp == t0
    assert closed.open == 100.0
    assert closed.high == 102.0
    assert closed.low == 99.5
    assert closed.close == 99.5  # last in-window close
    assert closed.interval == "1m"


def test_volume_accumulates(t0) -> None:
    from bot.data.aggregator import BarAggregator
    agg = BarAggregator(interval="1m", symbol="MNQ")
    agg.feed(_tick(t0, 100.0, size=2))
    agg.feed(_tick(t0 + timedelta(seconds=30), 101.0, size=3))
    closed = agg.feed(_tick(t0 + timedelta(seconds=60), 102.0, size=1))
    assert closed is not None
    assert closed.volume == 5  # 2 + 3, NOT including the boundary-crossing tick


def test_flush_emits_partial_bar(t0) -> None:
    """flush() drains the current in-progress bar (used at end-of-data)."""
    from bot.data.aggregator import BarAggregator
    agg = BarAggregator(interval="1m", symbol="MNQ")
    agg.feed(_tick(t0, 100.0))
    agg.feed(_tick(t0 + timedelta(seconds=15), 101.0))
    out = agg.flush()
    assert out is not None
    assert out.open == 100.0
    assert out.close == 101.0
    # Second flush is None (already drained)
    assert agg.flush() is None


def test_aggregator_rejects_out_of_order_tick(t0) -> None:
    from bot.data.aggregator import BarAggregator
    agg = BarAggregator(interval="1m", symbol="MNQ")
    agg.feed(_tick(t0 + timedelta(seconds=30), 100.0))
    with pytest.raises(ValueError, match="out of order"):
        agg.feed(_tick(t0, 99.0))
```

- [ ] **Step 2: Failure check** — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/bot/data/aggregator.py`**

```python
# src/bot/data/aggregator.py
"""BarAggregator — build 1m/5m bars from sub-interval ticks/sub-bars.

Spec: 01-data-pipeline.md §3.4. Closed-bar semantics: a bar closes when a tick
arrives crossing its [start, start+interval) boundary. The crossing tick
belongs to the NEXT bar.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from bot.types import Bar, Tick


_INTERVAL_TO_DELTA: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
}


def _floor_to_interval(t: datetime, interval: timedelta) -> datetime:
    """Round t down to the nearest interval boundary."""
    # We assume interval divides evenly into the day (true for 1m, 5m)
    epoch = datetime(1970, 1, 1, tzinfo=t.tzinfo)
    delta_seconds = (t - epoch).total_seconds()
    interval_seconds = interval.total_seconds()
    floored_seconds = (int(delta_seconds) // int(interval_seconds)) * int(interval_seconds)
    return epoch + timedelta(seconds=floored_seconds)


class BarAggregator:
    """Stateful aggregator. One instance per (symbol, interval)."""

    def __init__(self, interval: str, symbol: str) -> None:
        if interval not in _INTERVAL_TO_DELTA:
            raise ValueError(f"Unsupported interval: {interval!r}")
        self._interval_str = interval
        self._interval = _INTERVAL_TO_DELTA[interval]
        self._symbol = symbol
        self._current: Bar | None = None
        self._last_tick_ts: datetime | None = None

    def feed(self, t: Tick) -> Bar | None:
        """Process a tick; return the just-closed bar, or None."""
        if self._last_tick_ts is not None and t.timestamp <= self._last_tick_ts:
            raise ValueError(
                f"Tick out of order: {t.timestamp} <= last {self._last_tick_ts}"
            )
        self._last_tick_ts = t.timestamp

        bar_start = _floor_to_interval(t.timestamp, self._interval)

        if self._current is None:
            self._current = Bar(
                symbol=self._symbol,
                open=t.price, high=t.price, low=t.price, close=t.price,
                volume=t.size,
                timestamp=bar_start, interval=self._interval_str,
            )
            return None

        if bar_start > self._current.timestamp:
            # Bar closes; the crossing tick opens the next bar.
            closed = self._current
            self._current = Bar(
                symbol=self._symbol,
                open=t.price, high=t.price, low=t.price, close=t.price,
                volume=t.size,
                timestamp=bar_start, interval=self._interval_str,
            )
            return closed

        # Tick is within the current bar — update OHLC + volume
        cur = self._current
        self._current = Bar(
            symbol=cur.symbol,
            open=cur.open,
            high=max(cur.high, t.price),
            low=min(cur.low, t.price),
            close=t.price,
            volume=cur.volume + t.size,
            timestamp=cur.timestamp,
            interval=cur.interval,
        )
        return None

    def flush(self) -> Bar | None:
        """Drain the in-progress bar (end-of-data only)."""
        out = self._current
        self._current = None
        return out
```

- [ ] **Step 4: Verify**

```bash
pytest tests/test_data_aggregator.py -v
ruff check src/ tests/
mypy src/ tests/
```

Expected: 6 passed; clean.

- [ ] **Step 5: Commit**

```bash
git add src/bot/data/aggregator.py tests/test_data_aggregator.py
git commit -m "feat(data): BarAggregator (event-driven closed-bar semantics)"
```

---

### Task 12: `IBLiveBarStream` skeleton

**Files:**
- Create: `src/bot/data/live_ib.py`
- Create: `tests/test_data_live_ib_skeleton.py`

Source: spec `01-data-pipeline.md §3.3`. SKELETON only — connect/reconnect machinery lives in Plan 6.

- [ ] **Step 1: Failing tests**

```python
# tests/test_data_live_ib_skeleton.py
"""IBLiveBarStream skeleton. Spec 01 §3.3.

Plan 2 ships only the class shape + constructor + a 'not implemented' connect.
Full ib_async integration + reconnect logic lives in Plan 6.
"""
from __future__ import annotations

import pytest


def test_ib_live_bar_stream_constructs() -> None:
    from bot.data.live_ib import IBLiveBarStream
    s = IBLiveBarStream(host="127.0.0.1", port=4002, client_id=7)
    assert s.host == "127.0.0.1"
    assert s.port == 4002
    assert s.client_id == 7


@pytest.mark.asyncio
async def test_connect_raises_not_implemented_in_plan_2() -> None:
    """Plan 2 ships a stub; Plan 6 implements the real connect()."""
    from bot.data.live_ib import IBLiveBarStream
    s = IBLiveBarStream(host="127.0.0.1", port=4002, client_id=7)
    with pytest.raises(NotImplementedError, match="Plan 6"):
        await s.connect()
```

- [ ] **Step 2: Failure check** — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/bot/data/live_ib.py`**

```python
# src/bot/data/live_ib.py
"""IBLiveBarStream — live MNQ bars from Interactive Brokers (Globex via IB Gateway).

PLAN 2: SKELETON ONLY. The constructor + class shape land here; Plan 6 (IB Paper)
adds the real ib_async.IB().connectAsync() + reconnect machinery, the 5-sec
real-time bar subscription, the per-tick BarAggregator wiring, and the 30s
disconnect → force-flatten handoff to 04-risk-engine.

Spec: 01-data-pipeline.md §3.3.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from bot.types import Bar


class IBLiveBarStream:
    """Skeleton interface. Plan 6 implements the body."""

    def __init__(self, host: str, port: int, client_id: int) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id

    async def connect(self) -> None:
        """Establish ib_async connection. Implemented in Plan 6."""
        raise NotImplementedError(
            "IBLiveBarStream.connect is implemented in Plan 6 (IB Paper Execution). "
            "Plan 2 ships only the class shape so the conformance test can target it."
        )

    async def subscribe(self, symbol: str, interval: str) -> AsyncIterator[Bar]:
        """Yield aggregated Bars. Implemented in Plan 6."""
        raise NotImplementedError(
            "IBLiveBarStream.subscribe is implemented in Plan 6. "
            "Yields Bars from a 5-sec IB feed via local BarAggregator."
        )
        if False:  # pragma: no cover — make this an async generator for typing
            yield Bar(symbol="", open=0, high=0, low=0, close=0, volume=0,
                      timestamp=__import__("datetime").datetime.now(
                          __import__("datetime").timezone.utc), interval="")
```

- [ ] **Step 4: Verify**

```bash
pytest tests/test_data_live_ib_skeleton.py -v
ruff check src/ tests/
mypy src/ tests/
```

Expected: 2 passed; clean. (Ruff may flag the `if False:` unreachable code — if so, add `# noqa` or restructure.)

- [ ] **Step 5: Commit**

```bash
git add src/bot/data/live_ib.py tests/test_data_live_ib_skeleton.py
git commit -m "feat(data): IBLiveBarStream skeleton (Plan 6 will implement connect)"
```

---

### Task 13: Conformance test (backtest ↔ live mock identical Bar streams)

**Files:**
- Create: `tests/test_data_conformance.py`
- Create: `tests/fixtures/conformance_5sec_ticks.csv` (synthetic 5-second sub-bars)

Source: spec `01-data-pipeline.md §3.6` (the NON-NEGOTIABLE conformance contract).

- [ ] **Step 1: Create the fixture**

`tests/fixtures/conformance_5sec_ticks.csv`:

```csv
timestamp,price,size
2026-05-22 14:30:00,100.00,1
2026-05-22 14:30:05,101.00,2
2026-05-22 14:30:10,99.50,1
2026-05-22 14:30:15,100.50,3
2026-05-22 14:30:20,102.00,1
2026-05-22 14:30:25,101.50,2
2026-05-22 14:30:30,100.00,1
2026-05-22 14:30:35,99.00,4
2026-05-22 14:30:40,99.50,1
2026-05-22 14:30:45,100.00,2
2026-05-22 14:30:50,100.50,1
2026-05-22 14:30:55,101.00,1
2026-05-22 14:31:00,101.50,1
```

(Twelve 5-sec ticks span 14:30:00 to 14:31:00 = one full 1-min bar. The 14:31:00 tick crosses the boundary, closing the bar.)

- [ ] **Step 2: Write the conformance test**

```python
# tests/test_data_conformance.py
"""§3.6 conformance contract: backtest and live emit byte-identical Bar streams.

Both paths feed the SAME fixture data through:
- "Backtest path": one synthetic 1-min Bar built directly from the OHLCV of the
  ticks (mimicking what FirstRateData would have produced).
- "Live path": ticks fed one-by-one through BarAggregator.

Assert: closed Bar from the live path equals the historical bar field-by-field.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from bot.data.aggregator import BarAggregator
from bot.types import Bar, Tick

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_ticks() -> list[Tick]:
    ticks: list[Tick] = []
    with (_FIXTURES / "conformance_5sec_ticks.csv").open() as f:
        for row in csv.DictReader(f):
            ts_naive = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
            ts = ts_naive.replace(tzinfo=timezone.utc)
            ticks.append(Tick(symbol="MNQ", price=float(row["price"]),
                              size=int(row["size"]), timestamp=ts))
    return ticks


def _backtest_path() -> Bar:
    """What FirstRateData-style 1-min OHLCV looks like, computed from the same ticks."""
    ticks = _load_ticks()
    # The bar covers [14:30:00, 14:31:00). The 14:31:00 tick is EXCLUDED.
    in_bar = [t for t in ticks if t.timestamp < datetime(
        2026, 5, 22, 14, 31, tzinfo=timezone.utc)]
    return Bar(
        symbol="MNQ",
        open=in_bar[0].price,
        high=max(t.price for t in in_bar),
        low=min(t.price for t in in_bar),
        close=in_bar[-1].price,
        volume=sum(t.size for t in in_bar),
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=timezone.utc),
        interval="1m",
    )


def _live_path() -> Bar:
    """Live aggregation: feed each tick to BarAggregator; the boundary-crossing
    tick (14:31:00) closes the [14:30, 14:31) bar."""
    ticks = _load_ticks()
    agg = BarAggregator(interval="1m", symbol="MNQ")
    closed: Bar | None = None
    for t in ticks:
        result = agg.feed(t)
        if result is not None:
            closed = result
            break
    assert closed is not None, "expected a closed bar after the boundary tick"
    return closed


def test_conformance_backtest_live_identical_bars() -> None:
    bt = _backtest_path()
    live = _live_path()
    assert bt.symbol == live.symbol
    assert bt.open == live.open
    assert bt.high == live.high
    assert bt.low == live.low
    assert bt.close == live.close
    assert bt.volume == live.volume
    assert bt.timestamp == live.timestamp
    assert bt.interval == live.interval
```

- [ ] **Step 3: Verify**

```bash
pytest tests/test_data_conformance.py -v
ruff check src/ tests/
mypy src/ tests/
```

Expected: 1 passed; clean.

If the test fails, **investigate before patching tests** — the conformance contract is non-negotiable. Likely culprits:
- BarAggregator's volume excludes the boundary-crossing tick (correct per spec; backtest path also excludes it — verify alignment).
- BarAggregator's timestamp uses `_floor_to_interval`, which should produce `14:30:00`.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/conformance_5sec_ticks.csv tests/test_data_conformance.py
git commit -m "test(data): §3.6 conformance gate (backtest ↔ live emit identical Bars)"
```

---

### Task 14: `bot.data.ingest` CLI entry point

**Files:**
- Create: `src/bot/data/ingest.py`
- Create: `tests/test_data_ingest_cli.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_data_ingest_cli.py
"""bot.data.ingest CLI."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_ingest_cli_writes_parquet(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "NQ_2023Z_1min.csv").write_text(
        (_FIXTURES / "nq_2023z_clean.csv").read_text()
    )
    parquet = tmp_path / "parquet"

    result = subprocess.run(
        [sys.executable, "-m", "bot.data.ingest",
         "--symbol", "NQ",
         "--raw-root", str(raw),
         "--parquet-root", str(parquet)],
        cwd=str(_PROJECT_ROOT),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "rows_written=3" in result.stdout
    assert (parquet / "symbol=NQ" / "contract=2023Z").exists()


def test_ingest_cli_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bot.data.ingest", "--help"],
        cwd=str(_PROJECT_ROOT),
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--symbol" in result.stdout
    assert "--raw-root" in result.stdout
```

- [ ] **Step 2: Failure check** — `ModuleNotFoundError: No module named bot.data.ingest`

- [ ] **Step 3: Write the CLI**

```python
# src/bot/data/ingest.py
"""CLI entry point: python -m bot.data.ingest --symbol NQ --raw-root ... --parquet-root ..."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bot.data.firstratedata import FirstRateDataLoader, IngestQualityError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bot.data.ingest")
    parser.add_argument("--symbol", required=True, choices=["NQ", "MNQ"])
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--parquet-root", required=True, type=Path)
    parser.add_argument("--quarantine-threshold", type=float, default=0.001)
    args = parser.parse_args(argv)

    loader = FirstRateDataLoader(raw_root=args.raw_root, parquet_root=args.parquet_root)
    try:
        summary = loader.ingest(
            symbol=args.symbol,
            quarantine_rate_threshold=args.quarantine_threshold,
        )
    except IngestQualityError as e:
        print(f"INGEST_FAILED: {e}", file=sys.stderr)
        return 2

    print(
        f"INGEST_OK symbol={args.symbol} "
        f"rows_written={summary.rows_written} "
        f"rows_quarantined={summary.rows_quarantined} "
        f"files_processed={summary.files_processed} "
        f"files_skipped={summary.files_skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Verify**

```bash
pytest tests/test_data_ingest_cli.py -v
ruff check src/ tests/
mypy src/ tests/
```

Expected: 2 passed; clean.

- [ ] **Step 5: Commit**

```bash
git add src/bot/data/ingest.py tests/test_data_ingest_cli.py
git commit -m "feat(data): bot.data.ingest CLI entry point"
```

---

### Task 15: Final verification + tag

**Files:** (no new files)

- [ ] **Step 1: Tooling sweep**

```bash
source ~/.venvs/topstep-bot/bin/activate
cd "/Users/abusiddique/Library/Mobile Documents/com~apple~CloudDocs/projects/algo trade training"
ruff check src/ tests/
mypy src/ tests/
pytest -v
```

Expected: ruff + mypy clean. Test count = 70 (Plan 1) + Plan 2's ~33 = ~103 passing.

- [ ] **Step 2: Smoke-test the CLI**

```bash
mkdir -p /tmp/p2-smoke/raw
cp tests/fixtures/nq_2023z_clean.csv /tmp/p2-smoke/raw/NQ_2023Z_1min.csv
python -m bot.data.ingest --symbol NQ --raw-root /tmp/p2-smoke/raw --parquet-root /tmp/p2-smoke/parquet
ls -R /tmp/p2-smoke/parquet
```

Expected: prints `INGEST_OK symbol=NQ rows_written=3 ...`, parquet partition exists.

- [ ] **Step 3: Cleanup commit (if needed)**

```bash
git status
# If only intended files are changed, commit; else investigate.
git add -A
git diff --cached
git commit -m "chore: Plan 2 final cleanup" || true   # tolerate empty
```

- [ ] **Step 4: Tag**

```bash
git tag plan-02-data-pipeline-complete
git log --oneline | head -20
```

---

## Self-review (run before declaring Plan 2 done)

1. **Spec coverage**:
   - 01 §3.1 (FirstRateData ingest + parquet) → Tasks 5-7
   - 01 §3.2 (continuous roll) → Tasks 8-10
   - 01 §3.3 (IB live skeleton) → Task 12 (full impl Plan 6)
   - 01 §3.4 (BarAggregator) → Task 11
   - 01 §3.5 (timezone) → enforced in Bar/Tick types from Plan 1
   - 01 §3.6 (conformance gate) → Task 13
   - 01 §3.7 (DQ checks) → Task 3

2. **Type consistency**: Bar/Tick imported from `bot.types`. `RollEvent` defined in `bot.data.continuous`. No type duplication.

3. **No placeholders**: All "TBD"/"TODO" surfaced as `NotImplementedError("Plan 6")` for the IB skeleton — explicit deferral, not a placeholder.

4. **Synthetic-fixture coverage**: every public function tested without needing real FirstRateData.

5. **Idempotency**: `FirstRateDataLoader.ingest` re-run is a no-op (Task 6 test). Backtest replays are deterministic.

---

## Out-of-scope for Plan 2

- ❌ Real ib_async connect/reconnect (Plan 6)
- ❌ 30s-disconnect-with-position → force-flatten (Plan 4 risk gate + Plan 6 IB wiring)
- ❌ Telegram alert on quarantine spike (Plan 7)
- ❌ Real-time DataQualityMonitor wiring into live feed (Plan 6)
- ❌ Database journaling of ingest summaries (Plan 7)
- ❌ Backfill from Databento (parked as fallback)

---

## Notes for the executor

- Estimated wall-clock: 4-6 hours for an LLM agent, 6-8 for a human.
- The pyarrow operations are the most error-prone. Use `pq.write_table(table, path)` with explicit `schema=` to avoid type drift.
- The conformance test (Task 13) is the gate — if it fails, fix the implementation, not the test.
