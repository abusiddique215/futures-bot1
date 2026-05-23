"""ContinuousAdjuster — ratio-adjusted roll for NQ/MNQ futures.

Spec: 01-data-pipeline.md §3.2.

Roll on the third Friday of each contract month. Scale all OHLC of the
expiring contract (and recursively all older ones) by C_new/C_old so the
series equals the front-month price at every seam. Volume is unscaled.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path

import pyarrow.dataset as ds

from bot.data.contract_calendar import parse_contract_code


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
