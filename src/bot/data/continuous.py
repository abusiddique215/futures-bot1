"""ContinuousAdjuster — ratio-adjusted roll for NQ/MNQ futures.

Spec: 01-data-pipeline.md §3.2.

Roll on the third Friday of each contract month. Scale all OHLC of the
expiring contract (and recursively all older ones) by C_new/C_old so the
series equals the front-month price at every seam. Volume is unscaled.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from bot.data.contract_calendar import parse_contract_code
from bot.data.firstratedata import FirstRateDataLoader
from bot.types import Bar


@dataclass(frozen=True)
class RollEvent:
    """Audit trail of a single contract roll."""
    symbol: str
    roll_date: date
    old_contract: str
    new_contract: str
    c_old_close: float
    c_new_close: float
    ratio: float             # c_old / c_new
    cumulative_scale: float  # product of (c_new/c_old) for this roll and all later rolls


def _list_contracts(parquet_root: Path, symbol: str) -> list[str]:
    """List all contract codes ingested for `symbol`, sorted chronologically."""
    sym_root = parquet_root / f"symbol={symbol}"
    if not sym_root.exists():
        return []
    contracts: list[str] = []
    for p in sym_root.iterdir():
        if p.is_dir() and p.name.startswith("contract="):
            contracts.append(p.name.removeprefix("contract="))
    return sorted(contracts, key=parse_contract_code)


def _read_last_bar_close(
    parquet_root: Path, symbol: str, contract: str,
) -> tuple[date, float] | None:
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
        """For each consecutive contract pair, emit a RollEvent.

        Roll date is taken from the LAST bar of the old contract.
        cumulative_scale is filled in here as 1.0 placeholder; the
        write_continuous task (T10) computes the real cumulative product.
        """
        contracts = _list_contracts(self._parquet_root, symbol)
        if len(contracts) < 2:
            return []

        events: list[RollEvent] = []
        for old_code, new_code in pairwise(contracts):
            old_close_info = _read_last_bar_close(self._parquet_root, symbol, old_code)
            if old_close_info is None:
                continue
            old_date, c_old = old_close_info

            new_close_info = self._read_close_on_date(symbol, new_code, old_date)
            if new_close_info is None:
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
                cumulative_scale=1.0,  # placeholder; filled by T10
            ))
        return events

    def _read_close_on_date(
        self, symbol: str, contract: str, on: date,
    ) -> float | None:
        root = self._parquet_root / f"symbol={symbol}" / f"contract={contract}"
        if not root.exists():
            return None
        dataset = ds.dataset(str(root), format="parquet")
        table = dataset.to_table(columns=["timestamp", "close"])
        rows = [r for r in table.to_pylist() if r["timestamp"].date() == on]
        if not rows:
            return None
        rows.sort(key=lambda r: r["timestamp"])
        return rows[-1]["close"]  # type: ignore[no-any-return]

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
        return table.slice(0, 1).to_pylist()[0]["close"]  # type: ignore[no-any-return]

    @staticmethod
    def adjust_with_rolls(
        bars_by_contract: dict[str, list[Bar]],
        rolls: list[RollEvent],
    ) -> Iterator[Bar]:
        """Apply each roll's cumulative_scale to its old_contract bars.

        rolls must be sorted oldest-first. cumulative_scale of the newest roll
        is `c_new/c_old` of that roll alone; older rolls multiply their own
        inverse ratio on top. The newest contract's bars are unscaled.

        Yields adjusted Bars in chronological order across all contracts.
        Volume is NEVER scaled (volume is a count, not a price).
        """
        contract_scale: dict[str, float] = {}
        if rolls:
            # Newest contract (rolls[-1].new_contract) has scale = 1.0
            contract_scale[rolls[-1].new_contract] = 1.0
            for r in rolls:
                contract_scale[r.old_contract] = r.cumulative_scale
        else:
            for c in bars_by_contract:
                contract_scale[c] = 1.0

        all_bars: list[Bar] = []
        for contract, bars in bars_by_contract.items():
            scale = contract_scale.get(contract, 1.0)
            for b in bars:
                if scale == 1.0:
                    all_bars.append(b)
                else:
                    all_bars.append(Bar(
                        symbol=b.symbol,
                        open=b.open * scale,
                        high=b.high * scale,
                        low=b.low * scale,
                        close=b.close * scale,
                        volume=b.volume,  # NEVER scaled
                        timestamp=b.timestamp,
                        interval=b.interval,
                    ))
        all_bars.sort(key=lambda b: b.timestamp)
        yield from all_bars

    def write_continuous(self, symbol: str) -> None:
        """Compute rolls, apply adjustments, write to `continuous/symbol=<>/`.

        Also writes a `roll_events.parquet` sidecar for audit.
        """
        from datetime import UTC, datetime

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
        loader = FirstRateDataLoader(
            raw_root=self._parquet_root,  # not used by load()
            parquet_root=self._parquet_root,
        )
        for c in contracts:
            bars = list(loader.load(
                symbol=symbol, contract=c,
                start=datetime(1970, 1, 1, tzinfo=UTC),
                end=datetime(2099, 12, 31, tzinfo=UTC),
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

        # Sidecar: roll_events.parquet (always written, even if empty rolls list)
        (self._parquet_root / "continuous").mkdir(parents=True, exist_ok=True)
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
        recs = [{
            "symbol": r.symbol, "roll_date": r.roll_date,
            "old_contract": r.old_contract, "new_contract": r.new_contract,
            "c_old_close": r.c_old_close, "c_new_close": r.c_new_close,
            "ratio": r.ratio, "cumulative_scale": r.cumulative_scale,
        } for r in rolls]
        table = pa.Table.from_pylist(recs, schema=roll_schema)
        pq.write_table(
            table,
            self._parquet_root / "continuous" / "roll_events.parquet",
        )
