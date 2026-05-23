# 01 — Data Pipeline

**Project**: Topstep Futures Trading Bot
**Date**: 2026-05-22
**Status**: Spec
**Reads**: `00-architecture-overview.md`, `../research/futures-data-sources.md`
**Read-by**: `02-execution-clients.md`, `03-strategies.md`, `05-backtest-harness.md`

---

## 1. Purpose

Deliver one canonical bar/tick stream of NQ/MNQ futures data to the Strategy, identical in shape whether sourced from historical FirstRateData CSVs (backtest), an IB live WebSocket (paper), or — eventually — a TopstepX feed (live). The pipeline owns three responsibilities: (a) load and validate historical per-expiration data, (b) stitch it into a single ratio-adjusted continuous series, and (c) emit a real-time stream that conforms to the same `Bar`/`Tick` schema so the Strategy cannot detect which rail it is on. Backtest-to-live parity is the only product feature this file exists to deliver; everything else is plumbing for it.

## 2. Inherited decisions

From `00-architecture-overview.md`:

- **D9** Historical data: **FirstRateData** NQ + MNQ 1-min bars (~$200 one-time, 15+ years on NQ from 2008, MNQ from May 2019).
- **D10** Live data: **IB US Futures Value Bundle** (~$10/mo, waived at $30/mo commissions), top-of-book snapshots ≈4/sec, accessed via `ib_async`.
- **D11** Continuous-contract roll method: **ratio-adjusted (proportional)**. Non-negotiable that research and live use the same method; Panama vs ratio diverge 5–15% on NQ over 5 yrs (`futures-data-sources.md` §4.3).

This file is the canonical implementation reference for D11. If anything here contradicts another spec, this file wins for data-pipeline concerns and the other spec is wrong.

## 3. Design

### 3.1 Historical data ingestion (FirstRateData)

**Input shape**. FirstRateData ships ZIPs of CSVs, one CSV per contract month (per-expiration), plus optional pre-built continuous variants which we **ignore** (we roll ourselves so research = live). Expected CSV layout per row:

```
timestamp,open,high,low,close,volume
2023-09-15 09:30:00,15234.25,15240.50,15232.00,15238.75,4821
```

Timestamps are exchange-local (ET) per FirstRateData's docs; we treat them as `America/New_York` on ingest and immediately convert to UTC for storage.

**Filename convention** (FirstRateData scheme): `NQ_<YYYY><M>_1min.csv` where `<M>` is the CME contract-month code (`H` Mar, `M` Jun, `U` Sep, `Z` Dec). Example: `NQ_2023Z_1min.csv` is the Dec-2023 NQ contract. MNQ analogous: `MNQ_2023Z_1min.csv`.

**On-disk storage layout** (post-ingest):

```
data/
  raw/firstratedata/                  # untouched original CSVs (audit trail)
    NQ_2008H_1min.csv
    ...
  parquet/                            # normalized, validated, partitioned
    symbol=NQ/
      contract=2023Z/
        year=2023/month=09/part-0.parquet
        year=2023/month=10/part-0.parquet
        year=2023/month=11/part-0.parquet
        year=2023/month=12/part-0.parquet
    symbol=MNQ/
      contract=2023Z/
        ...
    continuous/                       # output of ContinuousAdjuster (§3.2)
      symbol=NQ_c/
        year=2023/month=09/part-0.parquet
        ...
```

Justification for parquet partitioned by `symbol/contract/year/month`:

1. Columnar — Strategy reads `close` and `volume` columns only during backtest scans; ~5× faster than CSV.
2. Partition pruning — a backtest restricted to Q4 2023 reads four files, not the 15-yr corpus.
3. Append-friendly — month boundary is a natural append seam; no rewriting historical partitions.
4. Schema-enforced — column types fixed at write time; type drift becomes a load error, not a silent backtest bug.

**Schema validation on ingest**. Every row must satisfy:

- `timestamp` is parseable, timezone-aware UTC after conversion, monotonically increasing within file.
- `open, high, low, close > 0`, `low ≤ open,close ≤ high`, `low ≤ high`.
- `volume ≥ 0` (zero is allowed during halts; negative is corrupt).
- No duplicate timestamps within file. Cross-file dedup (same bar appearing in two CSVs) prefers the row with higher volume, on the assumption it's the corrected version; conflict logged.

Rows failing validation are written to `data/quarantine/<date>/<reason>.csv` and **excluded** from the parquet output. Ingest fails loudly (non-zero exit) if quarantine rate exceeds 0.1% of any single contract-month, on the heuristic that a healthy file has near-zero malformed rows and anything else is a vendor-side regression worth a human look.

### 3.2 Continuous-contract roll method (ratio-adjusted)

**Roll calendar**. NQ and MNQ expire on the **third Friday** of the contract month. CME-listed contract months for NQ/MNQ are H (Mar), M (Jun), U (Sep), Z (Dec) — quarterly. We roll **on the third Friday close** of the expiring contract. This is one trading day inside the official last-trade window (NQ last-trade is the morning of the third Friday for current rules; we use the *prior* session close as the roll seam to avoid intraday rollover ambiguity). Documented choice — restated in §6.

**Roll math**. Given:

- `old` = expiring contract (e.g., NQ_2023Z), close on roll date `D`: `C_old`.
- `new` = next-quarter contract (e.g., NQ_2024H), close on the same date `D`: `C_new`.
- `ratio = C_old / C_new`.

For all bars of `old` **strictly before** `D` (inclusive of `D` itself for `old`), multiply `open`, `high`, `low`, `close` by `1/ratio = C_new / C_old`. Equivalently: scale the *older* series to align with the *newer* series at the seam. Volume is **not** scaled (volume is a count, not a price). All older older-than-D rolls compound multiplicatively: if you have contracts `c1 → c2 → c3 → ...` with ratios `r12, r23, r34, ...`, then bars in `c1` are scaled by `(C_c2/C_c1) * (C_c3/C_c2) * (C_c4/C_c3) * ...` = `C_latest / C_c1_at_first_roll`, which simplifies to "scale every older contract forward in time, never the current one."

We always scale **backward** (adjust history to match present), so the most recent bar in the continuous series equals the most recent bar of the live front-month contract. This means historical bar values change every quarter as new rolls are appended — `data/parquet/continuous/` is rewritten on every roll, and the raw per-contract parquet partitions in `data/parquet/symbol=NQ/contract=*/` are the immutable source of truth.

**Worked example**. Suppose on the 2023-12-15 close:

```
C_NQ_2023Z = 16500.00   (Dec 2023, the expiring one)
C_NQ_2024H = 16600.00   (Mar 2024, the new front)
ratio = 16500.00 / 16600.00 ≈ 0.99398
scale_factor_applied_to_2023Z_and_older = 1/ratio = 16600.00/16500.00 ≈ 1.00606
```

Every bar in NQ_2023Z (and all prior contracts, recursively) has OHLC multiplied by `1.00606`. A 2008 NQ bar at $1,800 becomes ~$1,800 × (product of all forward roll factors from 2008 to 2024). The continuous series at 2023-12-15 close therefore equals 16,600.00 — the new front month — and the Strategy sees a single smooth price history with no overnight gap at the seam.

**Where the seam lives**. The seam is at the *bar boundary* between the last bar of the old contract and the first bar of the new contract on roll date `D`. Both bars are present (the last bar of `old` is scaled; the first bar of `new` is unscaled). No bar is dropped, no synthetic bar inserted. The seam is queryable from a sidecar table:

```python
@dataclass
class RollEvent:
    symbol: str                    # "NQ"
    roll_date: date                # 2023-12-15
    old_contract: str              # "2023Z"
    new_contract: str              # "2024H"
    c_old_close: float
    c_new_close: float
    ratio: float                   # c_old / c_new
    cumulative_scale: float        # product of (c_new/c_old) for this and all later rolls
```

This is written to `data/parquet/continuous/roll_events.parquet` and is the audit trail. Replaying a backtest from raw + roll_events must reproduce the continuous series byte-for-byte.

**Strategy view**. The Strategy receives bars with `symbol="NQ"` (no contract suffix). It never sees raw per-contract bars in v1. If a v2 strategy needs to know about roll-aware behavior (calendar spreads, etc.), expose the roll_events table via a separate query API — do not pollute the bar stream.

### 3.3 IB live data subscription

**Connection**. `ib_async.IB()` connects to a running TWS or IB Gateway (paper account: port 7497; live: 7496 — but live IB is not used for Topstep money). Connection lifecycle:

1. `ib.connectAsync(host, port, clientId)` — `clientId` must be stable across restarts to retain order-state continuity (`02-execution-clients.md` §reconnect).
2. Resolve the **current front-month MNQ contract** via `IB.reqContractDetails(Future(symbol="MNQ", exchange="CME"))` filtered to the contract with the nearest non-expired `lastTradeDateOrContractMonth`. Refresh contract definitions on every reconnect (do not cache across days — the front month can roll while you slept).
3. `ib.reqRealTimeBars(contract, barSize=5, whatToShow="TRADES", useRTH=False)` — IB's smallest real-time bar is **5 seconds**; we explicitly request 5s and build 1m and 5m locally (§3.4). `useRTH=False` because futures trade Globex hours; ORB strategy still windows itself to 09:30–09:35 ET in `03-strategies.md`.

**Reconnect strategy**. Exponential backoff with cap:

```
attempt n: sleep min(2^n, 60) seconds, then retry
```

After 5 consecutive failed reconnects (~2 minutes elapsed), the pipeline emits a `DataFeedDegraded` event and the RiskEngine (`04-risk-engine.md` §hard-flatten) decides whether to force-flatten. The default policy is: **force-flatten if disconnected for >30s while a position is open, regardless of strategy state.** Live trading without a live feed is a known way to blow Topstep accounts.

**Gap detection on incoming bars**. For 5-sec bars, every bar should be exactly 5 seconds after the previous one (Globex is essentially 24/5 with brief daily halts at 17:00 ET; gaps during the daily-halt window 17:00–18:00 ET are expected and excluded from the gap-detector).

```python
expected_next = prev.timestamp + timedelta(seconds=5)
if abs((new.timestamp - expected_next).total_seconds()) > 1.0:
    emit BarGap(prev, new)   # warning-level; quarantined to log; may trigger reconnect
```

A gap > 30 seconds during RTH triggers a forced reconnect. A gap > 60 seconds during RTH triggers `DataFeedDegraded`. Gaps during the daily-halt window are silent.

### 3.4 Bar aggregation (build locally, do not trust the broker)

**Why locally**. IB's own 1-min and 5-min bars are produced server-side and have undocumented rounding rules at session boundaries; FirstRateData's bars are aggregated client-side from tick data and may differ by ±1 tick at the bar close. If we trust the broker for live bars and trust FirstRateData for historical bars, a strategy that fires on `bar.high == open_range_high` will fire on different bars in backtest vs live — silently. The fix: aggregate **both** rails from the same code path. Backtest replay produces 1m bars from FirstRateData's raw 1-min input (passthrough, no resample). Live aggregation produces 1m and 5m bars from IB's 5-sec bars using the local `BarAggregator`. The Strategy sees the output of `BarAggregator` only.

**Closed-bar semantics**. A bar is **closed** the instant its `[start, start+interval)` window elapses. The aggregator emits the closed bar on the *next* incoming tick/sub-bar that crosses the boundary (event-driven, not wall-clock); this prevents missing-bar phantom emits when the feed pauses momentarily. A separate `clock.set_time_alert` watchdog (see `04-risk-engine.md` §hard-flatten) checks that the last-emitted-bar timestamp is fresh.

**Bar timestamp convention: bar OPEN time**. Restated from the `Bar` dataclass: `timestamp` is the open time of the bar, timezone-aware UTC. Justification — see §6 Q3. All comparisons of "is bar at 09:30?" use the open time. Strategies that need close time compute `close_time = timestamp + interval`.

### 3.5 Time zone handling

- **Storage**: UTC. All parquet files store `timestamp` as `timestamp[ns, UTC]`.
- **Exchange operations** (session open/close, FOMC times if equity-tied): `America/New_York`. Use `zoneinfo.ZoneInfo("America/New_York")`.
- **Topstep flat-by, daily-loss boundary**: `America/Chicago`. Use `zoneinfo.ZoneInfo("America/Chicago")`. The Topstep day boundary is 17:00 CT to 16:00 CT, encoded in `04-risk-engine.md`.
- **All `datetime` instances in Python must be timezone-aware.** Naive datetimes are a `TypeError` at the pipeline boundary. The `Bar` and `Tick` dataclasses' `timestamp` fields are validated on construction (`__post_init__`) to reject `tzinfo is None`.
- **DST**: `zoneinfo` handles US DST automatically. Code must never apply fixed UTC offsets (no `timedelta(hours=-5)` ever).

### 3.6 Conformance contract (NON-NEGOTIABLE)

The Strategy must not be able to distinguish backtest from live. The contract:

1. Same `Bar` dataclass, same field names, same types, same units (price in dollars, volume in contracts).
2. Same `Tick` dataclass (if a v2 strategy uses ticks).
3. Same `symbol` field — Strategy sees `"MNQ"` (or `"NQ"`), never `"MNQ_2024H"`. Per-contract identity lives below the continuous adjuster.
4. Same bar-close timing semantics (event-driven on close, never wall-clock predicted).
5. Same timezone (UTC on the wire; conversions happen *inside* Strategy if needed).
6. Same sequencing: bars arrive in monotonically increasing `timestamp` order, with no rewinds and no out-of-order emits.

A conformance test suite (§5) injects identical event sequences into the historical replay path and the live mock path and asserts byte-equal bar emission. This test is the gate for any pipeline change — if it fails, the change does not ship.

### 3.7 Data quality checks

Detect and respond to:

| Anomaly | Detection | Response |
|---|---|---|
| Missing bars (gap in expected sequence) | `expected_next != actual.timestamp` for >1 interval | Warn; if live during RTH, escalate (§3.3) |
| Weekend bars | `timestamp.weekday() in (5, 6)` and not during Sunday 17:00 CT Globex open | Quarantine (corruption) |
| After-hours bars during exchange halts | `timestamp` in the 17:00–18:00 ET halt window | Drop silently (expected halt) |
| Outlier prices | bar OHLC moves > 5σ vs rolling 1-hr volatility, or > 3% intra-bar | Flag in `data_quality.parquet`; do **not** drop (could be a real flash event); Strategy can opt-in to filtering |
| Zero-volume bars during RTH | `volume == 0` between 09:30 and 16:00 ET on a weekday | Flag; do not drop (rare but valid in a halt) |
| Stale repeating ticks | same close, same volume, ≥3 consecutive bars | Likely feed freeze; trigger reconnect |
| Out-of-order bars | new bar with `timestamp <= previous.timestamp` | Drop, warn — never rewind the Strategy's clock |

**Quarantine policy**. Rejected rows go to `data/quarantine/<symbol>/<reason>/<yyyy-mm>/part-0.parquet`. Quarantine is append-only. A daily cron summarizes quarantine rates per symbol per reason; >0.5% triggers a Telegram alert (`06-observability.md`). Quarantined data is never auto-restored — operator must inspect and explicitly re-ingest.

## 4. Implementation sketch

Python 3.12, type hints throughout. **Pseudocode — not production. Cross-references to Nautilus extension points noted inline.**

```python
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Iterator, AsyncIterator
from zoneinfo import ZoneInfo

# ---- canonical types (from 00-architecture-overview.md, restated for reference) ----

@dataclass
class Bar:
    symbol: str
    open: float; high: float; low: float; close: float; volume: int
    timestamp: datetime          # bar OPEN time, tz-aware UTC
    interval: str                # "1m", "5m"

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise TypeError("Bar.timestamp must be timezone-aware")

@dataclass
class Tick:
    symbol: str; price: float; size: int; timestamp: datetime

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise TypeError("Tick.timestamp must be timezone-aware")

# ---- historical loader ----

class FirstRateDataLoader:
    """Reads FirstRateData per-contract CSVs from data/raw, writes validated
    parquet partitions to data/parquet, then exposes a Bar iterator."""

    def __init__(self, raw_root: Path, parquet_root: Path): ...

    def ingest(self, symbol: str) -> None:
        """One-shot: walk raw CSVs, validate, dedupe, write parquet partitions.
        Idempotent — re-running on the same input is a no-op."""
        # for each CSV in raw_root/firstratedata/{symbol}_*.csv:
        #     parse, validate, convert ET→UTC, dedupe vs existing partition
        #     write to parquet_root/symbol=<>/contract=<>/year=<>/month=<>/

    def load(self, symbol: str, start: datetime, end: datetime,
             contract: str | None = None) -> Iterator[Bar]:
        """Yield Bars between [start, end]. If contract is None and symbol is
        a continuous code (e.g. 'NQ'), reads from parquet/continuous/.
        Else reads per-contract parquet."""
        # pyarrow.dataset partition-pruned scan; yield Bar per row.

# ---- continuous adjuster ----

class ContinuousAdjuster:
    """Implements §3.2 ratio-adjusted roll."""

    # CME contract-month codes for NQ/MNQ (quarterly)
    CONTRACT_MONTHS = {"H": 3, "M": 6, "U": 9, "Z": 12}

    def __init__(self, parquet_root: Path): ...

    def roll_calendar(self, symbol: str, start_year: int, end_year: int) -> list[date]:
        """Return third-Friday-of-each-quarter dates in range.
        Each date is the seam between expiring contract and the next."""
        # for year in [start, end], for month in (3, 6, 9, 12):
        #     yield third_friday(year, month)

    def compute_ratios(self, symbol: str) -> list["RollEvent"]:
        """Walk per-contract parquet, for each roll date find c_old close and
        c_new close, return RollEvents."""

    def adjust(self, per_contract_bars: list[Bar]) -> list[Bar]:
        """Apply cumulative scale factors backward in time. Scale OHLC,
        leave volume alone."""
        # rolls = self.compute_ratios(symbol)
        # build cumulative_scale lookup keyed by contract
        # for bar in per_contract_bars:
        #     scale = cumulative_scale[bar.contract]
        #     yield bar with (o,h,l,c) * scale

    def write_continuous(self, symbol: str) -> None:
        """Compute + persist data/parquet/continuous/symbol=<>_c/."""
        # also writes roll_events.parquet sidecar

# ---- live feed ----

class IBLiveBarStream:
    """Wraps ib_async; emits Bars conforming to §3.6."""

    def __init__(self, host: str, port: int, client_id: int): ...

    async def connect(self) -> None:
        """Connect with exponential backoff (§3.3); resolve current front-month
        contract; subscribe to 5-sec real-time bars."""

    async def subscribe(self, symbol: str, interval: str) -> AsyncIterator[Bar]:
        """Yield aggregated Bars built from 5-sec IB bars via BarAggregator.
        On disconnect, attempt reconnect; if degraded (§3.3), emit a
        sentinel via a separate channel and let RiskEngine decide."""
        # async for ib_5s_bar in self._ib_realtime_bars():
        #     tick = _ib_bar_to_synthetic_tick(ib_5s_bar)
        #     bar = self._aggregator.feed(tick)
        #     if bar is not None: yield bar

    async def reconnect(self) -> None:
        """Exponential backoff; refresh contract definitions; resubscribe."""

# ---- aggregation ----

class BarAggregator:
    """Build 1m / 5m bars from sub-interval ticks or sub-bars. Closed bars
    emit on the first tick that crosses the boundary."""

    def __init__(self, interval: str, symbol: str):
        self.interval_td = _parse_interval(interval)  # "1m" -> timedelta(minutes=1)
        self.current: Bar | None = None

    def feed(self, t: Tick) -> Bar | None:
        """Returns closed Bar if t crosses the current bar's close boundary,
        else None. Updates internal `current` to a fresh bar."""
        # boundary = floor(t.timestamp, self.interval_td)
        # if self.current is None: start new
        # if boundary > self.current.timestamp:
        #     closed, self.current = self.current, _new_bar(t, boundary)
        #     return closed
        # else: update self.current.{high, low, close, volume}
        # return None

    def flush(self) -> Bar | None:
        """Emit any partially-built bar as closed. Used at backtest end-of-data
        and at clean shutdown. Live feed must NOT call this mid-session — would
        violate §3.6 closed-bar semantics."""

# ---- data quality ----

class DataQualityMonitor:
    def check_bar(self, prev: Bar | None, new: Bar) -> list["DQIssue"]: ...
    def quarantine(self, bar: Bar, issue: "DQIssue") -> None: ...

# ---- Nautilus integration ----
#
# All four classes above live BELOW Nautilus's DataClient extension point.
# Nautilus expects a subclass of nautilus_trader.live.data_client.LiveDataClient
# that implements `_subscribe_bars` / `_unsubscribe_bars` and pushes events via
# `self._handle_data(bar)`. Our IBLiveBarStream + BarAggregator compose into:
#
#     class IBLiveDataClient(LiveDataClient):
#         def __init__(self, ..., stream: IBLiveBarStream): ...
#         async def _subscribe_bars(self, bar_type: BarType) -> None:
#             async for bar in self._stream.subscribe(...):
#                 self._handle_data(_to_nautilus_bar(bar))
#
# For backtest, Nautilus's BacktestEngine consumes a list[Bar]; we provide it
# by chaining FirstRateDataLoader.load() into a generator. The Strategy
# subclass (03-strategies.md) is identical in both cases.
```

## 5. Testing strategy

The pipeline ships with four categories of test, plus a conformance gate.

**5.1 Determinism (replay equivalence).** Given a fixed FirstRateData CSV fixture (1 trading day, NQ_2023Z), `FirstRateDataLoader.load(...)` produces the same byte-for-byte `Bar` sequence on every run. Hashed comparison. Catches: non-deterministic dict iteration order, time-of-day-dependent code paths.

**5.2 Roll-adjustment unit test.** Hand-built fixture:

```
NQ_2023Z bars on 2023-12-15 close at C_old = 16500.00
NQ_2024H bars on 2023-12-15 close at C_new = 16600.00
NQ_2023Z bar at 2023-12-15 09:30 has close = 16300.00
```

Assert: after `ContinuousAdjuster.adjust(...)`, the 2023-12-15 09:30 continuous bar has close = `16300.00 * (16600.00 / 16500.00) ≈ 16398.79`. Repeat with multi-roll fixtures (3 contracts, 2 rolls) to verify cumulative scaling. Verify that volume is **not** scaled.

**5.3 IB reconnect test.** Mock `ib_async.IB` that disconnects at random points in a 1-hour synthetic feed. Run `IBLiveBarStream` across the disconnects; assert:

- No `Bar` is emitted twice.
- No `Bar` is dropped (the 5-sec bars produce a known 720-bars-per-hour count for the 1m aggregator's input; output count must be 60).
- Reconnect honors exponential backoff (timing tolerances).
- `DataFeedDegraded` fires after 5 consecutive reconnect failures.

**5.4 Live-vs-historical schema conformance.** A single fixture (1 trading day of MNQ 1m bars) is fed through both:

- The historical path: `FirstRateDataLoader.load()` → `Bar` stream.
- The live mock path: a synthetic IB feed that emits 5-sec bars derived from the same fixture → `IBLiveBarStream` → `BarAggregator` → `Bar` stream.

Assert: both `Bar` streams have identical field values for every field, in order. This is the **conformance gate** for §3.6 — if it fails, no pipeline change ships.

**5.5 Data quality assertions** (per `DataQualityMonitor`). Synthetic fixtures with planted anomalies (weekend bar, OHLC inconsistency, gap, outlier) — assert each is flagged or quarantined per §3.7.

**5.6 Time-zone audit.** A property-based test (Hypothesis) generates random naive datetimes and asserts the pipeline rejects them at construction. A second test asserts that ET-stored historical inputs convert to the correct UTC after DST transitions.

## 6. Open questions

**Q1 (parked).** Does FirstRateData publish exchange-traded volume or only print volume?
The ORB strategy in `03-strategies.md` uses opening-range volume as a confirmation filter. If FirstRateData volume is print-only (i.e., only the trades that printed to the consolidated tape) and not exchange-aggregated, the volume number is correct for direction but undercounted in absolute magnitude. **Mitigation**: the ORB filter uses *relative* volume (this OR vs 20-day OR average) which is robust to a consistent undercount, but introduces a risk if the underreporting rate is non-stationary (e.g., FirstRateData changed methodology in 2018). **Action**: spot-check 1 week of 2023 MNQ 1-min volume from FirstRateData against IB live aggregate volume during the same hour; if within 5%, accept. Otherwise consider Databento OHLCV-1m for volume only.

**Q2 (parked).** Backup historical source if FirstRateData has gaps?
FirstRateData provides per-contract CSVs; if a particular contract month is corrupt or missing, the continuous series for that period is broken. The Databento free $125 credit covers a few years of OHLCV-1m on NQ which we can use as a fallback for backfill on specific bad windows. **Action**: defer until we observe FirstRateData gap rate > 0.1% on any year of the corpus; reach for Databento backfill at that point.

**Q3 (RESOLVED — bar timestamp convention).** Bars use **open time**, timezone-aware UTC. Justification:

- Most academic and vendor data (FirstRateData included) uses open time.
- Event-driven open-time tagging matches "the bar that opened at 09:30" — natural for ORB and time-of-day filters.
- Close-time tagging causes off-by-one confusion at session boundaries (the 09:34 bar's close time is 09:35, but it's "the 09:34 bar" colloquially).
- Trade-off accepted: live aggregator must defer emit until the *next* tick after close — otherwise the emit time precedes the bar's labeled time. Acceptable; documented in `BarAggregator.feed` semantics.

**Q4 (parked).** Per-contract storage of MNQ pre-launch (May 2019). MNQ did not exist before 2019-05-06 (`futures-data-sources.md` §4.6). Continuous MNQ for periods earlier than that does not exist as real market data. **Decision**: do not synthesize MNQ from NQ/10 — accept that backtests on MNQ before May 2019 are empty, and run pre-2019 backtests on NQ instead. The Strategy is parameterized on tick value (`02-execution-clients.md`) so backtesting on NQ but with MNQ tick-value sizing is well-defined.

**Q5 (parked).** Roll-on-last-day vs roll-on-volume-crossover. The current method (`§3.2`) rolls on the third Friday of contract month, deterministic and calendar-only. CME futures generally see volume migrate to the next contract about a week before expiration. A volume-crossover roll would be more realistic to "what a trader would actually do." **Tradeoff**: deterministic calendar roll is easier to reproduce and explain; volume-crossover roll matches reality better but requires per-contract volume series available at roll-decision time. **Decision for v1**: stick with calendar roll. Reassess after first walk-forward backtest if cumulative drift between rolled and live front-month exceeds 0.5%.

## 7. References

- `00-architecture-overview.md` — locked decisions D9, D10, D11; canonical `Bar`/`Tick` types.
- `../research/futures-data-sources.md` — FirstRateData and IB data source profiles; §4 watch-outs (especially #3 on continuous-roll method).
- `02-execution-clients.md` — consumes this pipeline's output; tick-value constants per symbol.
- `03-strategies.md` — Strategy subscribes to `Bar` events emitted here; ORB depends on §3.4 closed-bar semantics.
- `04-risk-engine.md` — receives `DataFeedDegraded` events from §3.3; force-flatten on prolonged disconnect.
- `05-backtest-harness.md` — drives `FirstRateDataLoader` + `ContinuousAdjuster` for replay.
- CME contract-month codes: `H/M/U/Z` = Mar/Jun/Sep/Dec quarterly cycle (CME Group spec).
- `zoneinfo` (Python stdlib 3.9+) — IANA tz database, DST-aware.
- `ib_async` — Python async wrapper for IB API.
- `pyarrow.dataset` — partition-pruned parquet scans.
