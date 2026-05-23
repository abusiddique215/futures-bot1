# 03 — Strategies

**Owns**: `OpeningRangeBreakoutStrategy` (single Nautilus `Strategy` subclass), `surge.yml`, `maintenance.yml`, v2 candidate registry (documented, not implemented).
**Reads**: `00-architecture-overview.md` (D4, D5, D17), `../research/prop-firm-strategy-literature.md`, `02-execution-clients.md` §4 (`OrderIntent`), `01-data-pipeline.md` §4 (`Bar`).

## 1. Purpose

Define the v1 trading logic that emits `OrderIntent`s into the risk gate. One concrete strategy class, two YAML config profiles (`surge`, `maintenance`) selected at process start. The class is a Nautilus `Strategy` subclass; it never holds a broker reference and never bypasses the `RiskEngine`. Profiles diverge in size, stop/target multiples, time-of-day filter, and per-day trade cap — not in code paths.

This spec freezes v1. It also catalogues v2 candidates so future contributors don't reinvent the literature review; none of them require new architecture, only a new strategy subclass + YAML profile.

## 2. Inherited decisions

From `00-architecture-overview.md`:

- **D4** — Two operating modes (Surge / Maintenance), **one Strategy class** with YAML parameter profiles. No registry, no plugin system, no abstract base class. The two modes are *parameter profiles*, not subclasses.
- **D5** — v1 strategy is the 5-min Opening Range Breakout (Zarattini–Aziz 2023). 40–55% win rate, 1:2 R, no HFT / news-trading dependency. Other candidates (Maróy intraday momentum, Larry Williams volatility breakout, Crabel NR7, VWAP trend-pullback) live in §3.7 as v2 candidates.
- **D17** — Strategy is a Nautilus `Strategy` subclass directly. No separate base-class abstraction in v1. If a non-Nautilus strategy provider materializes later (grammatical evolution, ML signal), introduce the abstraction *then*.

Also load-bearing from §7 of the architecture overview:

- §7.7 — *No multi-strategy registry in v1*. Surge + Maintenance are YAML profiles of the same class. A registry is justified only when a third concrete strategy exists that *cannot* be expressed as a parameter profile of the first.
- §7.3 — Hard flat by 15:10 CT is enforced by the `RiskEngine`, not the strategy. The strategy SHOULD pre-flatten by 15:00 CT to leave a 10-minute margin; the risk engine is the backstop.

## 3. Design

### 3.1 Single class, two YAML profiles

There is exactly one strategy class:

```
OpeningRangeBreakoutStrategy(nautilus_trader.trading.Strategy)
```

It is instantiated with a `profile: dict` parsed from one of:

- `configs/strategies/surge.yml`
- `configs/strategies/maintenance.yml`

Per D4 and the bot-architecture-patterns research, "Surge" and "Maintenance" are not subclasses, modes, or strategy IDs — they are *config profiles loaded into the same class*. The class never branches on `profile["name"]`; it only reads numeric parameters.

Parameters that differ between profiles:

| Parameter | Type | Purpose |
|---|---|---|
| `position_size` | `int` | Number of MNQ contracts per entry |
| `stop_atr_multiplier` | `float` | Stop distance = `mult × ATR(period)` in ticks |
| `take_profit_r_multiple` | `float` | TP = `R × stop_distance` |
| `time_filter_window_et` | `tuple[str, str] \| None` | If set, only enter within this window |
| `max_trades_per_day` | `int` | Hard cap on entries per UTC trading session |
| `max_directions_per_day` | `int` | 1 (one direction only) or 2 (allow long + short) |
| `opening_range_minutes` | `int` | 5 (v1 default) or 15 (sweep candidate) |
| `atr_period` | `int` | 14 default (Wilder) |
| `pre_flatten_time_ct` | `str` | Time to begin flatten, default `15:00:00` |

Parameters that are *fixed* (not profile-tunable in v1):

- Instrument: MNQ
- Opening range anchor: 9:30 ET cash open
- Stop type: stop-market (one bracket leg)
- Take-profit type: limit (other bracket leg)
- Risk-engine hard flat: 15:10 CT (owned by `04-risk-engine.md`)

### 3.2 v1 strategy — 5-min Opening Range Breakout (Zarattini–Aziz 2023)

**Anchor.** First `opening_range_minutes`-minute bar after the **9:30 ET cash equities open** on NQ/MNQ. Default 5 → the 09:30–09:35 ET bar. Alternative 15-min variant (community/futures.io) is parameterized for the backtest sweep in `05-backtest-harness.md`; we do not pick it by default because the Zarattini–Aziz peer-reviewed result is on the 5-min variant.

We anchor on the **cash open**, not the Globex overnight session open, because:

1. The Zarattini–Aziz paper, the QuantMacro independent review, and every credible practitioner reference use cash open.
2. NQ exhibits a documented liquidity / volatility regime change at 9:30 ET when QQQ opens.
3. Globex session open at 17:00 CT is typically low-volume and dominated by Asia overnight, with no statistical breakout edge in the literature.

**Opening range computation.** Once the 09:35 ET bar (or 09:45 ET for 15-min variant) closes:

```
opening_range_high = max(bar.high for bar in opening_range_bars)
opening_range_low  = min(bar.low  for bar in opening_range_bars)
opening_range_set  = True
```

`opening_range_bars` is a list of length 1 (5-min default) or 3 (15-min).

**Long entry.** After `opening_range_set`, on every closed 5-min `Bar`:

```
if bar.high > opening_range_high
    and trades_taken_today < max_trades_per_day
    and (last_direction != "LONG" or max_directions_per_day == 2)
    and within_time_filter(bar.ts):
        emit OrderIntent(side=BUY, quantity=position_size, type=MARKET)
        attach bracket:
            stop_market at (entry_estimate - stop_distance_ticks)
            take_profit at (entry_estimate + tp_distance_ticks)
```

**Short entry.** Symmetric:

```
if bar.low < opening_range_low
    and same guards as long, mirrored
        emit OrderIntent(side=SELL, quantity=position_size, type=MARKET)
        attach bracket:
            stop_market at (entry_estimate + stop_distance_ticks)
            take_profit at (entry_estimate - tp_distance_ticks)
```

Note: `entry_estimate` is `bar.close` of the breakout bar. The actual fill is whatever the broker returns — `on_order_event` reconciles the bracket placement against the realized fill price.

**Stop distance.** ATR-based:

```
stop_distance_ticks = round(stop_atr_multiplier * atr_14 / tick_size)
```

ATR is on 5-min bars over the same session-aware lookback `01-data-pipeline.md` provides. Default `atr_period = 14` (Wilder). MNQ tick size = 0.25; tick value = $0.50.

**Take-profit distance.**

```
tp_distance_ticks = take_profit_r_multiple * stop_distance_ticks
```

Default R = 2.0 (Surge) and 1.5 (Maintenance). The 1:2 R figure matches the Zarattini–Aziz result; 1.5 R is a conservative deviation justified by the consistency-rule pressure on a funded Maintenance account (we'd rather take many small wins than one large win that biases the best-day ratio).

**Max trades per day.** Default 1 per direction. Surge profile allows one long *and* one short on the same session (max 2 entries total). Maintenance profile allows 1 entry total per day.

**End-of-day flatten.**

- Strategy SHOULD emit a flatten `OrderIntent` at `pre_flatten_time_ct` (default 15:00 CT).
- `RiskEngine` MUST emit one at 15:10 CT regardless. The 10-minute gap is the safety buffer.
- If the strategy is flat at 15:00 CT, no action.

### 3.3 Surge profile (`configs/strategies/surge.yml`)

```yaml
name: surge
instrument: MNQ
position_size: 2
opening_range_minutes: 5
atr_period: 14
stop_atr_multiplier: 1.0
take_profit_r_multiple: 2.0
time_filter_window_et: null      # no filter beyond risk-engine hard-flat
max_trades_per_day: 2            # one long + one short allowed
max_directions_per_day: 2
pre_flatten_time_ct: "15:00:00"
```

**Goal**: hit the $3,000 Combine target in 5–10 trading days. With 2 MNQ contracts and a typical 30–60 tick NQ opening-range expansion day, a winner returns $30–60 × 2 = $60–120 net of slippage per contract per win, scaled by R. Expected daily P&L on a winning day: $200–$600. Expected daily loss on a losing day: $50–$150 (capped by ATR stop × 2 MNQ).

**Drawdown sanity**: 2 MNQ × ~25 tick stop × $0.50/tick = $25 max loss per stop-out × 2 trades = $50 worst case from strategy alone. Real-world adverse slippage and gap risk widen this, but the strategy is structurally bounded well inside the $2,000 trailing MLL.

### 3.4 Maintenance profile (`configs/strategies/maintenance.yml`)

```yaml
name: maintenance
instrument: MNQ
position_size: 1
opening_range_minutes: 5
atr_period: 14
stop_atr_multiplier: 0.8         # tighter than Surge
take_profit_r_multiple: 1.5      # more conservative than Surge
time_filter_window_et: ["09:30:00", "11:30:00"]  # opening drive only
max_trades_per_day: 1
max_directions_per_day: 1
pre_flatten_time_ct: "15:00:00"
```

**Goal**: net-positive day on the Funded account, never approach the trailing drawdown, grind toward a monthly payout. The consistency rule (best-day ≤ 50% of total cycle profit) biases toward small consistent wins rather than home-run days — Maintenance directly reflects this.

The 09:30–11:30 ET filter restricts trading to the literature-documented "opening drive" session (see prop-firm-strategy-literature §3.8). This is a *heuristic* in v1 — its empirical justification is the §6 open question to resolve via backtest in `05-backtest-harness.md`.

### 3.5 Strategy lifecycle

Nautilus drives the strategy via callbacks. The strategy implements:

- `on_start()` — load profile, register subscriptions (5-min bars on MNQ), set the 09:35 ET opening-range-built timer, set the `pre_flatten_time_ct` timer.
- `on_bar(bar: Bar)` — primary entry-decision hook. Updates ATR, computes/locks opening range when the 09:35 ET bar arrives, evaluates breakout conditions on every subsequent bar.
- `on_order_event(event)` — track our own bracket fills: on entry fill, record `entry_price` and `entry_ts`; on bracket-leg fill or cancel, update `position_state`.
- `on_position_event(event)` — sync `is_flat`, `position_side`, `position_size_open`. The broker is source of truth (per D12); the strategy never trusts its own bookkeeping over a position event.
- `on_clock(event)` — fires for the pre-flatten timer at `pre_flatten_time_ct`. Emits flatten `OrderIntent` if not already flat.

The strategy **never** calls the broker directly. Every action goes through `self.submit_order(order_intent)` → RiskEngine → ExecutionClient (the chain defined in `00-architecture-overview.md` §4).

### 3.6 Internal state

Per-session (resets at session boundary, defined as the new RTH open in `01-data-pipeline.md`):

| State | Type | Set when | Used for |
|---|---|---|---|
| `opening_range_high` | `float \| None` | After the 09:35 ET bar closes | Long-entry trigger |
| `opening_range_low` | `float \| None` | Same | Short-entry trigger |
| `opening_range_set` | `bool` | Same | Gating subsequent on_bar logic |
| `trades_taken_today` | `int` | On entry fill | Max-trades cap |
| `directions_taken_today` | `set[Side]` | On entry fill | Max-directions cap |
| `pnl_realized_today` | `float` | On position-close event | Telemetry, not gating (the gating is in RiskEngine) |
| `is_flat_phase` | `bool` | True after `pre_flatten_time_ct` | Block new entries |

Indicators:

- `ATR(period=14)` on 5-min bars, Wilder smoothing. Initialized from the previous N×5min bars at `on_start` via the data pipeline's history backfill.

### 3.7 v2 candidates (documented, NOT implemented in v1)

For each: mechanism, why parked for v1, and what it takes to add later. In every case the answer is "new `Strategy` subclass + new YAML profile", with **zero new infrastructure**. That's the test of D4/D17 working as intended.

**V2-A. Maróy 2025 intraday momentum continuation (Sharpe >3.0).** Detect breach of the "noise boundary" — prior-close ± k × intraday-volatility envelope — and enter in the breach direction with multi-hour holds. Parked because (a) Sharpe is parameter-optimized and walk-forward sensitivity is unverified for NQ futures (paper is on SPY/QQQ), and (b) the Maróy "different exit strategies" component requires the bracket-modification path our v1 ExecutionClient doesn't exercise yet. To add later: new `MomentumContinuationStrategy(Strategy)` + YAML profile. No new infrastructure.

**V2-B. Larry Williams volatility breakout.** Place a buy stop at `PrevClose + 0.5 × (PrevHigh − PrevLow)` and a mirrored sell stop; first trigger wins, second cancels (OCO); flat at session close. Parked because the OCO bracket pattern is a different order-graph than v1's single-bracket-after-entry, so the IB and TopstepX execution clients need an OCO conformance test (`02-execution-clients.md`) before this is safe. To add later: extend ExecutionClient conformance suite with OCO, then new `WilliamsVolBreakoutStrategy` + profile.

**V2-C. Crabel NR7-ID + Stretch.** NR7-ID flags a "double compression" day (today's range smaller than each of the prior 6 days, *and* inside the prior day's range); on the next session, place breakout stops at prior day's H/L. "Stretch" uses 10-day average of (open − nearest extreme) for stop placement. Parked because NR7-ID fires 4–8 times per year per market — too low frequency to validate in walk-forward inside the v1 timebox; better as a portfolio-add than a standalone v2. To add later: new `CrabelCompressionStrategy` + profile, plus a multi-day daily-bar feed (already in `01-data-pipeline.md` requirements).

**V2-D. VWAP trend-pullback (continuation, not fade).** On a confirmed trend day (price persistently above/below VWAP with positive/negative ADX), enter on a touch of VWAP in the trend direction with momentum confirmation. Maintenance-mode candidate. Parked because (a) requires a trend-day classifier the v1 data pipeline doesn't compute yet, and (b) "VWAP fade" and "VWAP pullback" both look like "VWAP touch entry" to a naive backtest — they need careful distinction to avoid accidentally implementing the fade (which §3.7 of the research warns is a documented failure mode). To add later: new `VWAPPullbackStrategy` + profile + ADX/VWAP-slope indicators in the data pipeline.

**Anti-patterns explicitly excluded.** ICT/SMC, sub-30s-hold scalping, ES/NQ pairs, news-time paired bracket entries, and any logic that produces a single >50% day. See `../research/prop-firm-strategy-literature.md` §11.

## 4. Implementation sketch

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Literal

from nautilus_trader.trading.strategy import Strategy
# Bar: see 01-data-pipeline §4
# OrderIntent: see 02-execution-clients §4

Side = Literal["BUY", "SELL"]


@dataclass
class ORBProfile:
    """YAML-loaded profile. No defaults here — surge.yml / maintenance.yml own them."""
    name: str
    instrument: str
    position_size: int
    opening_range_minutes: int
    atr_period: int
    stop_atr_multiplier: float
    take_profit_r_multiple: float
    time_filter_window_et: tuple[time, time] | None
    max_trades_per_day: int
    max_directions_per_day: int
    pre_flatten_time_ct: time


class OpeningRangeBreakoutStrategy(Strategy):
    """Single strategy class for both Surge and Maintenance modes.
    Loaded with one YAML profile; behavior differs by parameters, not code paths."""

    def __init__(self, profile: ORBProfile) -> None:
        super().__init__()
        self.profile = profile
        # Per-session state — reset by self._reset_session() on each RTH open
        self.opening_range_high: float | None = None
        self.opening_range_low: float | None = None
        self.opening_range_set: bool = False
        self.opening_range_bars: list[Bar] = []
        self.trades_taken_today: int = 0
        self.directions_taken_today: set[Side] = set()
        self.is_flat_phase: bool = False
        self.atr: ATRIndicator = ATRIndicator(period=profile.atr_period)
        self.tick_size: float = 0.25  # MNQ; from instrument metadata at on_start

    # ---- lifecycle ----

    def on_start(self) -> None:
        instrument = self.cache.instrument(self.profile.instrument)
        self.tick_size = float(instrument.price_increment)
        self.subscribe_bars(self._bar_type_5min(instrument))
        # Pre-flatten timer in CT; risk engine owns the 15:10 CT hard-flat
        self.clock.set_time_alert(
            name="pre_flatten",
            alert_time=self._today_at_ct(self.profile.pre_flatten_time_ct),
        )
        self._reset_session()

    def on_bar(self, bar: Bar) -> None:
        self.atr.update(bar)
        if self._is_new_session(bar.ts_event):
            self._reset_session()

        # Build opening range from the first N minutes of the session
        if not self.opening_range_set:
            if self._bar_in_opening_range(bar):
                self.opening_range_bars.append(bar)
            if self._opening_range_complete(bar):
                self.opening_range_high = max(b.high for b in self.opening_range_bars)
                self.opening_range_low = min(b.low for b in self.opening_range_bars)
                self.opening_range_set = True
            return

        if self.is_flat_phase:
            return
        if not self._within_time_filter(bar.ts_event):
            return
        if self.trades_taken_today >= self.profile.max_trades_per_day:
            return

        # Breakout checks
        if bar.high > self.opening_range_high and self._direction_allowed("BUY"):
            self._enter("BUY", reference_price=bar.close)
        elif bar.low < self.opening_range_low and self._direction_allowed("SELL"):
            self._enter("SELL", reference_price=bar.close)

    def on_clock(self, event) -> None:
        if event.name == "pre_flatten":
            self.is_flat_phase = True
            if not self._is_flat():
                self._emit_flatten()

    def on_order_event(self, event) -> None:
        # Update bookkeeping; broker is source of truth
        if event.is_fill and event.is_entry:
            self.trades_taken_today += 1
            self.directions_taken_today.add(event.side)

    def on_position_event(self, event) -> None:
        # Sync flat status from broker truth (per D12)
        if event.is_closed:
            self._on_position_closed(event)

    # ---- entry construction ----

    def _enter(self, side: Side, reference_price: float) -> None:
        atr_value = self.atr.value
        stop_ticks = round(self.profile.stop_atr_multiplier * atr_value / self.tick_size)
        tp_ticks = round(self.profile.take_profit_r_multiple * stop_ticks)
        stop_distance = stop_ticks * self.tick_size
        tp_distance = tp_ticks * self.tick_size

        if side == "BUY":
            stop_price = reference_price - stop_distance
            tp_price = reference_price + tp_distance
        else:
            stop_price = reference_price + stop_distance
            tp_price = reference_price - tp_distance

        # NOTE: OrderIntent field names match the canonical definition in
        # 02-execution-clients.md §4. We pass ticks (broker-agnostic); each
        # adapter computes broker-specific entry/SL/TP prices.
        intent = OrderIntent(
            symbol=self.profile.instrument,
            side=side,
            quantity=self.profile.position_size,
            order_type="BRACKET",
            client_order_id=self._next_client_order_id(
                tag=f"orb_{self.profile.name}",
            ),
            timestamp=self.clock.utc_now(),
            bracket=Bracket(
                stop_loss_ticks=stop_ticks,
                take_profit_ticks=tp_ticks,
            ),
        )
        self.submit_order(intent)  # RiskEngine gate → ExecutionClient

        # stop_price / tp_price computed above are NOT sent to the broker; they
        # are useful for telemetry / logs only. The bracket leg adapter (02 §3.5)
        # converts ticks → broker-specific prices using contract minTick.

    # ---- helpers (sketched, not exhaustive) ----

    def _direction_allowed(self, side: Side) -> bool:
        if side in self.directions_taken_today:
            return False
        if len(self.directions_taken_today) >= self.profile.max_directions_per_day:
            return False
        return True

    def _within_time_filter(self, ts) -> bool:
        if self.profile.time_filter_window_et is None:
            return True
        et = ts.in_timezone("America/New_York").time()
        lo, hi = self.profile.time_filter_window_et
        return lo <= et <= hi

    def _emit_flatten(self) -> None: ...
    def _reset_session(self) -> None: ...
    def _is_new_session(self, ts) -> bool: ...
    def _bar_in_opening_range(self, bar: Bar) -> bool: ...
    def _opening_range_complete(self, bar: Bar) -> bool: ...
    def _is_flat(self) -> bool: ...
    def _on_position_closed(self, event) -> None: ...
    def _bar_type_5min(self, instrument): ...
    def _today_at_ct(self, t: time): ...
```

ORB entry-logic pseudocode (the critical bit, isolated):

```
on every closed 5-min bar after opening_range_set:
    if is_flat_phase: skip
    if not within_time_filter(bar.ts): skip
    if trades_taken_today >= max_trades_per_day: skip

    if bar.high > opening_range_high and direction_allowed(BUY):
        submit MARKET BUY position_size, bracket:
            stop  = bar.close - stop_atr_multiplier * ATR
            tp    = bar.close + take_profit_r_multiple * stop_distance

    elif bar.low < opening_range_low and direction_allowed(SELL):
        symmetric SHORT
```

## 5. Testing strategy

Tests live under `tests/strategies/test_orb.py`. All tests run against the Nautilus `BacktestEngine` with a deterministic `SimBroker` from `02-execution-clients.md`.

**T1. Replay test — known session.** Feed a recorded NQ session (2024-Q4 sample) where a manual annotation says "9:35 bar high broken at 09:48; long entry; stopped at 10:14 for −18 ticks." Assert the strategy emits exactly that entry, that stop, and that exit. Tolerance: 0 ticks on the entry decision; broker fill slippage is the SimBroker's responsibility.

**T2. Profile-swap test.** Same `OpeningRangeBreakoutStrategy` class, run twice against the same 60-day backtest window, once with `surge.yml` and once with `maintenance.yml`. Both runs must complete without code changes. Assert:

- `surge` run has more trades than `maintenance` (looser time filter, higher max_trades)
- `maintenance` run has lower max-position-size at all timestamps (1 MNQ vs 2 MNQ)
- Both runs produce non-empty trade lists (i.e., neither config accidentally filters every trade)

**T3. Edge case — doji opening range.** Construct a synthetic session where the 09:30–09:35 ET bar has range = 1 tick (0.25 NQ pts). Stop distance via `1.0 × ATR(14)` should derive from prior session ATR, *not* the (essentially zero) opening-range height. Assert: the strategy does NOT produce a micro-stop ≤ 2 ticks. Failure mode this guards against: ATR collapse + tight stop = nuisance stop-outs on noise.

**T4. Edge case — overnight gap.** Construct a session where the 09:30 ET cash open gaps 1.5% above prior close. Assert: opening range still anchors on the 09:30–09:35 bar (not on prior close), and the strategy emits an entry only on the post-OR break, not at the gap itself. Failure mode this guards against: anchoring opening-range computation on overnight data, which would invalidate the breakout logic.

**T5. Property-based test — position size never exceeds Topstep MLL implication.** Using Hypothesis, generate arbitrary profiles in the v1 parameter ranges. For each, simulate a worst-case adverse move:

```
worst_case_loss_$ = position_size × tick_value × stop_distance_ticks_at_max_ATR
assert worst_case_loss_$ < 0.5 * TOPSTEP_50K_MLL  # leaves headroom
```

This catches profiles like "10 MNQ, 4.0 ATR multiplier" that compile but would blow up a Combine on one stop-out. The risk engine in `04-risk-engine.md` is the authoritative gate; this test is the spec-level smoke check.

**T6. End-of-day pre-flatten.** Assert that at `pre_flatten_time_ct`, if the strategy holds a position, it emits a flatten `OrderIntent`. Assert that after `pre_flatten_time_ct`, no new entry `OrderIntent`s are emitted regardless of breakout signal.

**T7. Conformance with execution-client suite.** The conformance suite in `02-execution-clients.md` runs this strategy against `SimBroker`, `IBBroker`, and `TopstepXBroker` with identical event streams and asserts identical callback sequences. The strategy must be deterministic given a fixed event stream — no `random`, no wall-clock decisions outside Nautilus's `clock`.

## 6. Open questions

1. **Opening range window: 5 min vs 15 min.** Zarattini–Aziz peer-reviewed result is on 5-min. Community variants (futures.io, Trading123) use 15-min and report ~55% win rate with VWAP confirmation. Resolve via backtest sweep in `05-backtest-harness.md` over NQ 2018–2025. Hypothesis: 5-min has more signals but lower per-signal win rate; 15-min has fewer signals but higher quality. Picking by realized Sharpe is the right tiebreaker.

2. **ATR period: 10 vs 14 vs 20.** Default Wilder ATR(14) is the textbook choice. ATR(10) is more reactive (Crabel-style); ATR(20) is more stable. Sweep.

3. **Cash open (9:30 ET) vs futures session open (overnight Globex 17:00 CT prior day).** v1 picks cash open because (a) Zarattini–Aziz, QuantMacro, and community ORB literature all use cash open, (b) NQ liquidity regime shifts at 9:30 ET when QQQ opens, (c) Globex overnight session has no statistically documented breakout edge. Document this choice in the README; do *not* re-litigate without new evidence.

4. **Maintenance profile 09:30–11:30 ET time filter.** This is a heuristic from prop-firm-strategy-literature §3.8 ("opening drive" effect), not a backtested parameter. Validate empirically in `05-backtest-harness.md`: does restricting Maintenance to 09:30–11:30 ET actually improve Sharpe, or is it superstition? If the latter, widen the window or drop the filter entirely.

5. **Max trades per day in Surge.** Default 2 (one long + one short). Open question: does allowing a re-entry after the first trade stops out improve P&L, or is it revenge-trading dressed up as parameter? Sweep `max_trades_per_day ∈ {1, 2, 3}` for Surge only.

6. **Stop type — stop-market vs stop-limit.** v1 uses stop-market for guaranteed exit. Stop-limit risks no-fill on a fast move beyond the limit (catastrophic in a trailing-MLL world). This is a locked decision unless a backtest demonstrates non-trivial slippage cost we want to claw back; defer to `04-risk-engine.md` for the policy rationale.

7. **Bracket attachment timing.** Do we send `(market entry + stop + tp)` as a single OCO bracket, or do we send market entry first and attach stop/TP on fill confirmation? The latter is safer (we know the real fill price); the former is faster. The execution-client conformance suite in `02-execution-clients.md` will pin this down. v1 spec assumes "attach on fill" because both IB and TopstepX support post-fill bracket attach.

## 7. References

Primary literature (load-bearing for v1):

- Zarattini, Aziz (2023) — *Can Day Trading Really Be Profitable? Evidence … ORB strategy on QQQ*. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
- Zarattini, Aziz, Barbon (2024) — *Beat the Market: An Effective Intraday Momentum Strategy for SPY*. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172
- QuantMacro independent review of the ORB paper. https://quantmacro.substack.com/p/paper-review-an-effective-intraday

v2-candidate sources:

- Maróy (2025). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5095349
- Larry Williams volatility breakout (QuantifiedStrategies). https://www.quantifiedstrategies.com/larry-williams-volatility-strategy/
- Crabel NR7 / Stretch (Oxford-Strat). https://oxfordstrat.com/trading-strategies/nr7/ ; https://oxfordstrat.com/trading-strategies/opening-range-breakout/
- VWAP trend-pullback (Steady Turtle). https://medium.com/@steady-turtle-trading/how-professional-traders-really-use-vwap-its-not-what-you-think-cff7bfd9ecd0

Internal:

- `../research/prop-firm-strategy-literature.md` — full candidate ranking (Surge §9, Maintenance §10, anti-patterns §11).
- `../research/bot-architecture-patterns.md` — single-strategy-class-with-profiles pattern; "no registry before second class" rule.
- `00-architecture-overview.md` — D4, D5, D17, §7.7 (no multi-strategy registry in v1).
- `01-data-pipeline.md` §4 — `Bar` type, session boundaries, ATR backfill on `on_start`.
- `02-execution-clients.md` §4 — `OrderIntent` type, bracket semantics, `SIDE_BUY=0` defensive constant for TopstepX.
- `04-risk-engine.md` — owner of the 15:10 CT hard-flat, phantom-MLL gate, position-size denial.
- `05-backtest-harness.md` — owner of the 5/15-min sweep, ATR-period sweep, time-filter empirical validation.
