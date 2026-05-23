# 04 — Risk Engine (TopstepRiskGate)

**Project**: Topstep Futures Trading Bot
**Date**: 2026-05-22
**Status**: Spec — research phase, ready for implementation planning
**Owner**: abu.siddique215@gmail.com
**Depends on**: `00-architecture-overview.md`, `02-execution-clients.md` (for `OrderIntent`, `OrderEvent`, `PositionEvent`)

---

## 1. Purpose

`TopstepRiskGate` is the single, mandatory choke point between strategy decisions and broker order placement. It encodes every Topstep prop-firm rule that can cause an account closure, a payout block, or a ToS violation, and it short-circuits any `OrderIntent` that would put the account at risk before that intent reaches an `ExecutionClient`.

This is **the load-bearing safety component**. A bug here is a real-money / real-eval loss. Three properties must hold:

1. **No bypass.** Strategy code never holds a broker reference. The only path from strategy to broker is `Strategy.emit(intent) → TopstepRiskGate.approve_or_deny(intent, state) → ExecutionClient.submit(order)`. This invariant is structurally enforced by Nautilus's `RiskEngine` plug-in point (see 00 D8) and verified by the conformance suite in `02-execution-clients.md`.
2. **Real-time, not fill-time.** The Combine MLL is monitored on **unrealized P&L tick-by-tick** by Topstep itself (research §2a). The gate's state machine must therefore tick with the data feed, not with order events.
3. **Deterministic and pure.** Given an `OrderIntent` and an `AccountState`, the gate's decision is a pure function. All side effects (logging, journaling, telemetry) live in adapters around the pure core, so the property-based test in §5 can compare against a reference implementation.

Force-flat and equity-touch liquidation are also owned by this module (§3, force-flatten trigger). They are **independent of strategy state** — even if the strategy is wedged, the gate flattens.

---

## 2. Inherited decisions

This spec assumes the following from `00-architecture-overview.md`:

- **D1 — Topstep is the target prop firm.** The rules encoded here are Topstep-specific; do not over-abstract for "any prop firm."
- **D3 — Target account: $50K Combine.** Constants below default to the $50K row of 00 §5. The `AccountState.is_combine` flag selects the Combine-vs-EFA `DrawdownPolicy`.
- **D8 — Runtime is NautilusTrader.** The gate is implemented as a Nautilus `RiskEngine` subclass; pre-trade rejection emits typed `OrderDenied`. Force-flat is wired through `clock.set_time_alert("15:10:00 America/Chicago")`.

The rule table in **00 §5** is the authoritative constants table. This document does **not** redefine it; it consumes it. Specifically:

| 00 §5 row | This spec's usage |
|---|---|
| Profit target $3,000 | Consistency-rule denominator (rule 6) |
| DLL $1,000 | Rule 2 |
| MLL $2,000 (Combine, real-time on unrealized) | Rule 3 + phantom-MLL state machine |
| MLL $2,000 (EFA Standard, EoD) | `EFAStandardEoDDrawdown` policy |
| Max position 5 mini / 50 micro | Rule 4 |
| Hard flat-by 3:10 PM CT | Rule 1 + force-flatten trigger |
| Consistency 50% (Combine) | Rule 6 |
| Consistency 40% (EFA Consistency) | `EFAConsistencyDrawdown` policy |
| News max-position | Rule 5 + `NewsCalendar` |
| HFT cancel/fill (undefined) | Rule 7 |
| Cross-account hedging prohibited | Startup assertion |
| VPS/cloud prohibited (live) | Out of scope here; enforced in `07-config-and-deploy.md` |

The seven **critical defensive items** in **00 §7** are all owned or co-owned here:

- 00 §7.2 (Combine MLL on unrealized, real-time) — owned by §3 phantom-MLL state machine and rule 3.
- 00 §7.3 (Hard flat by 3:10 PM CT) — owned by §3 force-flatten trigger and rule 1.
- 00 §7.4 (News throttle) — owned by §3 `NewsCalendar` integration and rule 5.
- 00 §7.6 (Broker truth on restart) — co-owned: `AccountState` is populated from the broker, not the journal, at startup; the gate refuses to evaluate intents until reconciliation succeeds.

---

## 3. Design

### 3.1 Contract

```
TopstepRiskGate.approve_or_deny(
    intent: OrderIntent,           # from 02 §4
    state:  AccountState,          # from §4 below
) -> ApprovedOrder | OrderDenied
```

- **Total function.** Every call returns one of the two result types; the gate never raises on a normal flow. (Configuration / startup errors raise during `__init__`.)
- **Pure.** No I/O inside `approve_or_deny`. Logging, journaling, Telegram alerts on `OrderDenied` are handled by a thin adapter wired to the result, not by the gate itself. This is what makes the property-based test in §5 tractable.
- **Strategy emits `OrderIntent`, never `Order`.** The intent is broker-agnostic (see 02 §4). Translation to broker-specific order shape (including the `SIDE_BUY=0/SIDE_SELL=1` TopstepX inversion, 00 §7.1) happens in the `ExecutionClient` **after** the gate approves.
- **Idempotent w.r.t. state.** Calling `approve_or_deny` twice with the same `(intent, state)` yields identical results. The gate does not mutate `state`; state mutation is the driver's job (the driver feeds the gate fresh `AccountState` snapshots).
- **Snapshot semantics.** `ApprovedOrder.state_snapshot` and `OrderDenied.state_snapshot` capture the exact `AccountState` that the decision was made against. This is what gets journaled. If the broker later fills at a different equity than `state.equity`, the journal still tells us what the gate believed.

### 3.2 Rule checks (executed in order, short-circuit on first deny)

The seven rule checks below run in a fixed order. **The first denial wins**; subsequent rules are not evaluated. Order matters because:

- Time-based denials (rule 1) must fire even on a "safe" intent at 3:11 PM CT.
- Hard-money denials (rules 2, 3) must fire before sizing rules (4, 5), because a sizing-compliant intent that breaches DLL/MLL is still unacceptable.
- The HFT cap (rule 7) is last because it is the only rule with a soft, self-imposed threshold; we want it to be the discriminator only when nothing else has caught the order.

#### Rule 1 — Hard-flat clock check

```
now = state.timestamp.astimezone("America/Chicago")
if now >= 15:10 CT:
    if intent.is_open_increasing_exposure(state.open_positions):
        deny("HARD_FLAT_PASSED", rule="HARD_FLAT_CLOCK")
elif now >= 15:00 CT:
    if intent.is_open_increasing_exposure(state.open_positions):
        deny("HARD_FLAT_APPROACHING", rule="HARD_FLAT_PREEMPT")
# closes (intent that strictly reduces |position|) always allowed
```

- "Open-increasing-exposure" means `sign(intent.qty) == sign(state.open_positions[intent.symbol])` **or** `state.open_positions[intent.symbol] == 0`. A flattening order (opposite sign, |qty| ≤ |position|) is always permitted, even after 15:10.
- DST is handled by always converting `state.timestamp` (which is UTC, tz-aware) to `America/Chicago` via `zoneinfo.ZoneInfo`. Never use a fixed UTC offset. See §5 time-zone test.
- The 15:00 CT pre-emptive denial exists because the strategy is supposed to be flattening by 15:00 (see `03-strategies.md`). If it tries to open new exposure between 15:00 and 15:10, that is a strategy bug; the gate refuses the order and logs `HARD_FLAT_PREEMPT`.

#### Rule 2 — Daily Loss Limit (DLL)

```
worst_case_loss = stop_distance_ticks * tick_value(intent.symbol) * abs(intent.qty)
projected_realized = state.realized_pnl_today - worst_case_loss
if projected_realized <= -DLL_AMOUNT:           # DLL_AMOUNT = 1000 for $50K
    deny("DLL_NEAR_LIMIT", rule="DLL")
```

- `stop_distance_ticks` comes from `intent.bracket.stop_loss_ticks`. An intent without a stop is itself a denial (rule 2a — sub-check inside rule 2):

  ```
  if intent.is_market_or_limit_open() and intent.bracket.stop_loss_ticks is None:
      deny("UNPROTECTED_OPEN", rule="STOP_REQUIRED")
  ```

  No naked open-exposure orders, ever. A close (reducing) order does not require a stop.
- `tick_value(symbol)`: MNQ = $0.50/tick (4 ticks/pt × $2/pt), NQ = $5/tick (4 ticks/pt × $20/pt). Encoded as constants alongside the gate. Source: CME contract specs (cited in `01-data-pipeline.md`).
- Worst case assumes the stop is hit. Slippage allowance is folded into `stop_distance_ticks` by the strategy (see `03-strategies.md` Surge profile). The gate does not add additional slippage; the strategy's stop placement already reflects expected slippage.
- The `≤` (not `<`) is intentional: equality with `-DLL` is a denial. The DLL is the hard floor.

#### Rule 3 — Max Loss Limit (MLL) phantom check (Combine variant)

```
phantom_mll = policy.phantom_mll(state)            # see 3.4 state machine
worst_case_loss = stop_distance_ticks * tick_value(intent.symbol) * abs(intent.qty)
projected_equity_floor = state.equity - worst_case_loss
if projected_equity_floor < phantom_mll:
    deny("MLL_PHANTOM_TRIGGER", rule="MLL")
```

- `state.equity` includes `state.unrealized_pnl`. This is the critical point: the gate must run with a tick-driven `AccountState` feed, not a fill-driven one. The driver (Nautilus `RiskEngine` host) emits fresh `AccountState` snapshots on every tick to recompute `high_water_equity` and `phantom_mll`. See §3.4.
- `projected_equity_floor < phantom_mll` (strict less-than) means an intent that would land equity *exactly* at the phantom MLL is rejected. We do not give Topstep the chance to round us out.
- For EFA Standard accounts (`state.is_combine == False`), the `DrawdownPolicy.phantom_mll` returns the EoD-trailing floor (no intraday wick concern). See §3.3.
- Defensive interaction with rule 8 (stop offset safety buffer, §3.6): even if rule 3 approves, the stop is automatically widened so that the broker-side stop sits at `phantom_mll - safety_buffer_ticks`, never at the worst-case-loss boundary. This is the difference between "the gate allows this order if the stop holds" and "the gate also makes the stop holding more likely."

#### Rule 4 — Max position

```
current = state.open_positions.get(intent.symbol, 0)
projected = current + intent.signed_qty()          # signed_qty: +qty for BUY, -qty for SELL
cap = max_position_for(intent.symbol, state.account_size, state.is_combine)
if abs(projected) > cap:
    deny("MAX_POSITION_EXCEEDED", rule="MAX_POSITION")
```

- For $50K Combine: `cap = 5 NQ` OR `cap = 50 MNQ`. **A combined cap applies** if the strategy ever holds both NQ and MNQ at once: `5 * |nq_qty| + 0.5 * |mnq_qty| <= 5` (mini-equivalent units). v1 trades only one of NQ/MNQ per session per strategy profile, so the combined cap is enforced as a defensive assertion, not a routine path.
- For EFA accounts, the cap is **profit-gated** per the scaling plan (research §2d). `max_position_for` is a function on the policy, not a constant. **CRITICAL: Topstep's scaling plan is keyed off accumulated profit (`equity − start_balance`), NOT absolute equity.** On a $50K EFA, absolute equity is > $50K from day one — gating off absolute equity would always hit the unrestricted branch and quietly bypass the scaling rule.
  ```
  EFAStandardEoDDrawdown.max_position(symbol, state):
      profit = state.equity - state.start_balance
      if profit < 1500:  return 2 mini-equiv
      if profit < 2000:  return 3 mini-equiv
      else:              return 5 mini-equiv
  ```
  Scaling-plan thresholds are **Medium confidence** (research §2d). They must be re-verified from the TopstepX in-platform Trade Report before live; encoded as `_PROVISIONAL` constants with a startup warning if the source has not been verified within 90 days. See §6 open question.

#### Rule 5 — News throttle

```
if news_calendar.in_window(state.timestamp):
    news_cap = news_calendar.max_position_during_window()    # default: 1 contract
    projected = abs(current + intent.signed_qty())
    if projected > news_cap:
        deny("NEWS_WINDOW_SIZE_LIMIT", rule="NEWS_THROTTLE")
```

- Default window: `[event_time - 5 min, event_time + 15 min]` (00 §7.4).
- "Maximum position news trading" is on Topstep's prohibited list (research §6). The threshold is enforced case-by-case by Topstep; we self-impose `1 contract` during the window as a conservative cap. Configurable.
- A position open *before* the window enters is not force-closed by this rule (that would conflict with the strategy's own exit logic). Only **new orders** during the window are size-capped. If an existing position exceeds `news_cap` when the window opens, the gate emits a `NEWS_WINDOW_OVERSIZED` warning to telemetry; the strategy is responsible for trimming. (A future hardening pass — see §6 — could make the gate force-trim, but that risks fighting the strategy's exits.)

#### Rule 6 — Consistency rule (Combine, soft-flag only by default)

```
if state.is_combine:
    best_day = journal.best_day_pnl_so_far()
    target_remaining = PROFIT_TARGET - journal.net_pnl_so_far()
    if target_remaining > 0 and best_day / target_remaining > 0.50:
        if config.consistency_mode == "hard":
            deny("CONSISTENCY_50PCT_EXCEEDED", rule="CONSISTENCY_HARD")
        else:
            warn("CONSISTENCY_50PCT_EXCEEDED")    # allow trade
```

- Topstep's Combine consistency rule (research §3) is enforced *at evaluation pass time*, not per-trade. A single big day does not fail the Combine on its own; it raises the bar (`required_total = 2 * best_day`). So a per-trade hard deny would be needlessly aggressive.
- Default `consistency_mode = "soft"`. Operator can flip to `"hard"` in `07-config-and-deploy.md` if they want the bot to force restraint.
- "Net P&L so far" includes today's realized P&L *and* unrealized for the open intent (worst-case excluded — we don't penalize the consistency check with a hypothetical loss; that would be self-defeating).
- This rule is **not applicable to EFA Standard**. For EFA Consistency, the analogous 40% rule lives inside `EFAConsistencyDrawdown.gate_payout()`, not in this per-trade gate, because the 40% applies across a payout window not per-trade.

#### Rule 7 — HFT defensive cap

```
ratio = self.cancel_to_fill_tracker.ratio(window_minutes=60)
if ratio > config.hft_cancel_to_fill_threshold:    # default: 5.0
    deny("HFT_CANCEL_RATIO_EXCEEDED", rule="HFT_DEFENSIVE")
```

- Topstep's HFT threshold is officially undefined (research §9; 00 §5 row "HFT threshold"). We self-impose 5.0 cancels per fill over a 60-min rolling window — conservative. Configurable.
- `cancel_to_fill_tracker` is owned by the gate (it sees every `OrderEvent` the `ExecutionClient` emits — see 02 §4). It is *not* a strategy responsibility.
- This rule denies new orders, not cancels. A bot tripping over its own cancel ratio cannot make it worse by submitting yet more cancels; it cools off until the rolling window drops the offending cancels.

### 3.3 `DrawdownPolicy` swappable strategy pattern

Three concrete policies, selected by configuration (`07-config-and-deploy.md`):

| Policy | When to use | Phantom MLL semantics | Max position |
|---|---|---|---|
| `CombineIntradayDrawdown` | $50K/$100K/$150K Combine | Real-time on `state.equity` (incl. unrealized); locks at `start_balance` once `equity ≥ start_balance + MLL_AMOUNT` | Fixed (5 / 10 / 15 mini) |
| `EFAStandardEoDDrawdown` | EFA Standard (post-Combine pass) | Trails on **end-of-day equity only**; intraday wicks ignored. Locks at $0. | Balance-gated scaling plan (research §2d, Medium confidence) |
| `EFAConsistencyDrawdown` | EFA Consistency | Same EoD drawdown as Standard; **plus** a payout-window 40% best-day cap that gates `request_payout()`, not per-trade | Same scaling plan |

Common interface:

```python
class DrawdownPolicy(Protocol):
    def phantom_mll(self, state: AccountState) -> float:
        """Equity floor below which the account is dead. Used by rule 3."""
    def is_locked(self, state: AccountState) -> bool:
        """True once the trailing drawdown has reached its lock point."""
    def max_position(self, symbol: str, state: AccountState) -> int:
        """Per-symbol size cap. Used by rule 4."""
    def update_on_tick(self, state: AccountState) -> AccountState:
        """Return a new AccountState with high_water_equity updated. Pure."""
    def update_on_eod(self, state: AccountState) -> AccountState:
        """Apply EoD-only updates (e.g., EFA EoD trailing). Pure."""
```

Why a protocol and not subclassing: the three policies share no implementation, only an interface. Forcing a base class would invite leaky abstractions (e.g., a `_compute_trail_distance` helper that means different things in Combine vs EFA). The protocol keeps each policy self-contained and the test matrix small.

### 3.4 Phantom-MLL state machine (Combine variant)

State variables (all stored on `AccountState`, updated on every tick by the driver, never by the strategy):

```
high_water_equity:   float        # max(equity) seen since account start
is_locked:           bool         # True once trail has locked at start_balance
lock_point:          float | None # = start_balance once locked, else None
```

Transition diagram:

```
  ┌──────── on every tick ────────┐
  │                               │
  ▼                               │
state.high_water_equity = max(state.high_water_equity, state.equity)
  │
  ▼
if not state.is_locked and state.high_water_equity >= start_balance + MLL_AMOUNT:
    state.is_locked = True
    state.lock_point = start_balance        # locks PERMANENTLY at start_balance
```

Phantom-MLL computation (used by rule 3):

```
def phantom_mll(state):
    if state.is_locked:
        return state.lock_point             # constant = start_balance
    else:
        return state.high_water_equity - MLL_AMOUNT
```

Worked example, $50K Combine (`start_balance = 50_000`, `MLL_AMOUNT = 2_000`):

| Event | Equity | high_water | is_locked | lock_point | phantom_mll |
|---|---|---|---|---|---|
| Start | 50_000 | 50_000 | False | None | 48_000 |
| Up tick to 51_000 | 51_000 | 51_000 | False | None | 49_000 |
| Down tick to 50_500 | 50_500 | 51_000 | False | None | 49_000 (no change — one-way ratchet) |
| Up tick to 51_999 | 51_999 | 51_999 | False | None | 49_999 |
| Up tick to 52_000 | 52_000 | 52_000 | **True** | **50_000** | **50_000** (locks now) |
| Down tick to 51_000 | 51_000 | 52_000 | True | 50_000 | 50_000 (locked at start_balance forever) |
| Down tick to 49_999 | 49_999 | 52_000 | True | 50_000 | 50_000 — **breach: force flatten** |

**Tick cadence requirement.** The driver MUST feed `AccountState` to the gate on every tick (or at minimum every N seconds where N < worst-case-stop-distance / max-tick-velocity). A fill-driven update is insufficient: the Combine MLL is monitored on unrealized P&L in real time by Topstep itself (research §2a). If the gate only updates `high_water_equity` on fills, it will under-estimate `phantom_mll` between fills and approve orders that Topstep would liquidate. **This is the single most dangerous misconfiguration in the entire bot.** A startup assertion checks that the configured tick cadence is `<= 1 second`.

### 3.5 Force-flatten trigger

Two independent triggers, both routed to the same handler:

1. **Time trigger.** Nautilus `clock.set_time_alert("15:10:00 America/Chicago")` fires once per session. DST handled by `zoneinfo`. Handler: `force_flatten("HARD_FLAT_TIME")`.
2. **Equity-touch trigger.** On every tick, if `state.equity <= policy.phantom_mll(state)`, fire `force_flatten("MLL_EQUITY_TOUCH")`. No second chance — the moment equity touches the phantom floor we liquidate, because at that point Topstep is about to liquidate anyway and we want to be the ones in control.

Handler:

```python
def force_flatten(reason: str) -> None:
    if self._flattening:                    # idempotent: only one flatten in flight
        return
    self._flattening = True
    try:
        self.execution_client.cancel_all()           # idempotent on broker side too
        self.execution_client.close_all_positions()  # market orders, opposite side
        self.telemetry.alert("FORCE_FLATTEN", reason=reason, state=current_state)
        self.strategy.disable()                      # block further intents
    except Exception as e:
        # If the broker errors during force-flatten, escalate hard.
        self.telemetry.alert("FORCE_FLATTEN_FAILED", reason=reason, error=str(e))
        raise
```

- **Idempotent.** A second invocation while a flatten is in flight is a no-op (the `_flattening` latch).
- **Strategy disabled.** After a force-flatten, the strategy is disabled for the rest of the session (`force_flatten` is terminal). It restarts on the next session boundary (5:00 PM CT) after the operator inspects the journal and clears the latch.
- **No retries on partial fill.** `close_all_positions()` is expected to be a single market order per position; if a fill is partial, that is an execution-client problem, not a gate problem. The execution client owns retry semantics (see 02 §4).
- **Independent of strategy state.** Even if `Strategy.on_clock` is wedged, the time trigger still fires because it is registered on the Nautilus clock at gate `__init__`, not by the strategy.

### 3.6 Stop offset safety buffer

Every `OrderIntent` with `bracket.stop_loss_ticks` is augmented at gate time:

```
phantom_mll_floor      = policy.phantom_mll(state)
phantom_mll_floor_dist = (state.equity - phantom_mll_floor)
phantom_mll_in_ticks   = phantom_mll_floor_dist / (tick_value * abs(intent.qty))

safe_stop_ticks = min(
    intent.bracket.stop_loss_ticks,                    # the strategy's stop
    phantom_mll_in_ticks - config.safety_buffer_ticks  # gate's floor-aware cap
)
augmented_intent = intent.with_stop(safe_stop_ticks)
```

- Default `safety_buffer_ticks = 5`. Configurable. Wider in live than in paper.
- This is **after** rule 3 has approved the intent. Rule 3 checks the *strategy's* stop; the buffer makes the *broker's* stop tighter. The strategy's intent is preserved in `state_snapshot` for auditability.
- Why a fixed-tick buffer and not a fraction: NQ ticks are absolute units of MLL distance. A "5% margin" is a moving target; "5 ticks" is concrete and testable.
- The buffer must not invert the stop (i.e., land it on the wrong side of entry). If `safe_stop_ticks <= 0`, the gate denies the intent with `reason="STOP_INVERTED_BY_BUFFER", rule="MLL_PROXIMITY"` — meaning the account is so close to the MLL that no protective stop fits inside the safety buffer.

### 3.7 Cross-account hedging disable

At gate `__init__`:

```
assert len(config.accounts_managed) == 1, \
    "Multi-account orchestration is out of scope for v1 (00 §8). " \
    "Cross-account hedging is a Topstep ToS violation (research §9)."
```

If this assertion fails, the bot refuses to start. v1 is one bot, one account.

### 3.8 News calendar

```python
class NewsCalendar(Protocol):
    def in_window(self, now: datetime) -> bool: ...
    def max_position_during_window(self) -> int: ...
    def upcoming(self, horizon_minutes: int = 60) -> list[NewsEvent]: ...
```

v1 implementation: **`YAMLNewsCalendar`** reads `news_calendar.yml`:

```yaml
events:
  - time: 2026-05-28T14:00:00-05:00      # tz-aware
    name: FOMC
    impact: high
  - time: 2026-06-06T08:30:00-05:00
    name: NFP
    impact: high
  - time: 2026-06-12T08:30:00-05:00
    name: CPI
    impact: high
window_minutes_before: 5
window_minutes_after: 15
max_position_during_window: 1
```

Operator maintains it manually for v1. At startup, the bot warns if the latest event in the file is more than 14 days old (file likely stale).

v2 candidates (see §6):
- **Trading Economics API** — comprehensive, paid (~$50/mo for one user).
- **FRED-derived ICS calendar** — free, partial (US macro only; doesn't include FOMC press conferences as separate events).
- **Investing.com economic calendar** — comprehensive but TOS-restricted (no programmatic access; scraping prohibited).

---

## 4. Implementation sketch

### 4.1 Types defined here

(Cross-cutting types `OrderIntent`, `OrderEvent`, `PositionEvent` are defined in `02-execution-clients.md §4` and imported here.)

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

@dataclass(frozen=True)
class AccountState:
    equity: float                          # cash + unrealized; tick-fresh
    realized_pnl_today: float              # since 17:00 CT yesterday
    unrealized_pnl: float                  # mark-to-market on open positions
    open_positions: dict[str, int]         # symbol → signed quantity (+long, -short)
    pending_intent_count: int              # in flight, not yet acked by broker
    high_water_equity: float               # for trailing MLL state machine
    is_combine: bool                       # Combine vs EFA flavor (drives policy)
    timestamp: datetime                    # tz-aware UTC
    # Populated by phantom-MLL state machine, NOT by strategy:
    is_locked: bool = False
    lock_point: float | None = None
    # Account context, immutable after startup:
    start_balance: float = 50_000.0
    account_size: str = "50K"              # "50K" | "100K" | "150K"
                                            # (matches the field name used in rule 4)

@dataclass(frozen=True)
class OrderDenied:
    intent: OrderIntent
    reason: str                            # human-readable
    rule: str                              # canonical, e.g. "DLL_NEAR_LIMIT"
    state_snapshot: AccountState
    timestamp: datetime

@dataclass(frozen=True)
class ApprovedOrder:
    intent: OrderIntent                    # post-buffer-augmentation
    state_snapshot: AccountState
    timestamp: datetime
```

### 4.2 `TopstepRiskGate` pseudocode

```python
class TopstepRiskGate:
    def __init__(
        self,
        policy: DrawdownPolicy,
        news_calendar: NewsCalendar,
        execution_client: ExecutionClient,
        clock: NautilusClock,
        telemetry: Telemetry,
        config: RiskConfig,
    ) -> None:
        assert len(config.accounts_managed) == 1, "v1 single-account only"
        # Tick-cadence requirement applies to paper + live only. Backtest mode
        # legitimately runs at bar granularity (see §6 Q8); enforcing 1 Hz
        # there would prevent 05-backtest-harness from instantiating the gate.
        if config.env in ("paper", "live"):
            assert config.tick_cadence_seconds <= 1.0, \
                "Combine MLL is monitored on unrealized P&L in real time; " \
                "the gate must receive tick updates at least once per second " \
                "in paper/live mode. Backtest mode is exempt."

        self.policy = policy
        self.news_calendar = news_calendar
        self.execution_client = execution_client
        self.telemetry = telemetry
        self.config = config

        self.cancel_to_fill_tracker = RollingRatioTracker(window_minutes=60)
        self._flattening = False

        # Force-flatten time trigger
        clock.set_time_alert(
            name="hard_flat_15_10",
            alert_time=time(15, 10, tzinfo=ZoneInfo("America/Chicago")),
            handler=lambda: self.force_flatten("HARD_FLAT_TIME"),
        )

    def approve_or_deny(
        self, intent: OrderIntent, state: AccountState,
    ) -> ApprovedOrder | OrderDenied:
        now = state.timestamp

        # Rule 1 — hard-flat clock
        decision = self._check_hard_flat(intent, state, now)
        if decision is not None:
            return decision

        # Rule 2 — DLL (with sub-check 2a: stop required)
        decision = self._check_dll(intent, state)
        if decision is not None:
            return decision

        # Rule 3 — MLL phantom check
        decision = self._check_mll(intent, state)
        if decision is not None:
            return decision

        # Rule 4 — max position
        decision = self._check_max_position(intent, state)
        if decision is not None:
            return decision

        # Rule 5 — news throttle
        decision = self._check_news_throttle(intent, state)
        if decision is not None:
            return decision

        # Rule 6 — consistency (soft-flag by default)
        decision = self._check_consistency(intent, state)
        if decision is not None:
            return decision

        # Rule 7 — HFT cancel/fill ratio
        decision = self._check_hft_ratio(intent, state)
        if decision is not None:
            return decision

        # All checks passed. Apply stop-offset safety buffer.
        augmented = self._augment_with_safety_buffer(intent, state)
        if isinstance(augmented, OrderDenied):
            return augmented

        return ApprovedOrder(
            intent=augmented,
            state_snapshot=state,
            timestamp=now,
        )

    # Each _check_* returns OrderDenied | None.
    # Each is pure; no I/O.

    def on_tick(self, state: AccountState) -> AccountState:
        """Driver calls this on every tick to update the state machine.
        Returns the new AccountState; does NOT mutate input."""
        new_state = self.policy.update_on_tick(state)
        if new_state.equity <= self.policy.phantom_mll(new_state):
            self.force_flatten("MLL_EQUITY_TOUCH")
        return new_state

    def on_order_event(self, event: OrderEvent) -> None:
        """Driver calls this on every OrderEvent so we can update the
        cancel-to-fill tracker for rule 7."""
        if event.kind == "FILLED":
            self.cancel_to_fill_tracker.record_fill()
        elif event.kind == "CANCELED":
            self.cancel_to_fill_tracker.record_cancel()

    def force_flatten(self, reason: str) -> None:
        if self._flattening:
            return
        self._flattening = True
        try:
            self.execution_client.cancel_all()
            self.execution_client.close_all_positions()
            self.telemetry.alert("FORCE_FLATTEN", reason=reason)
        except Exception as e:
            self.telemetry.alert("FORCE_FLATTEN_FAILED", reason=reason, error=str(e))
            raise
```

### 4.3 `CombineIntradayDrawdown` pseudocode

```python
class CombineIntradayDrawdown:
    def __init__(self, start_balance: float, mll_amount: float, max_mini: int):
        self.start_balance = start_balance
        self.mll_amount = mll_amount
        self.max_mini = max_mini

    def update_on_tick(self, state: AccountState) -> AccountState:
        new_hw = max(state.high_water_equity, state.equity)
        new_locked = state.is_locked
        new_lock_point = state.lock_point
        if not new_locked and new_hw >= self.start_balance + self.mll_amount:
            new_locked = True
            new_lock_point = self.start_balance
        return replace(
            state,
            high_water_equity=new_hw,
            is_locked=new_locked,
            lock_point=new_lock_point,
        )

    def update_on_eod(self, state: AccountState) -> AccountState:
        # Combine intraday policy is tick-driven; EoD is a no-op.
        return state

    def phantom_mll(self, state: AccountState) -> float:
        if state.is_locked:
            return state.lock_point   # locked permanently at start_balance
        return state.high_water_equity - self.mll_amount

    def is_locked(self, state: AccountState) -> bool:
        return state.is_locked

    def max_position(self, symbol: str, state: AccountState) -> int:
        if symbol.startswith("MNQ"):
            return self.max_mini * 10        # 50 MNQ on $50K
        if symbol.startswith("NQ"):
            return self.max_mini             # 5 NQ on $50K
        raise ValueError(f"Unsupported symbol for Topstep: {symbol}")
```

### 4.4 `EFAStandardEoDDrawdown` pseudocode

```python
class EFAStandardEoDDrawdown:
    def __init__(self, mll_amount: float):
        self.mll_amount = mll_amount      # $2,000 on $50K EFA

    def update_on_tick(self, state: AccountState) -> AccountState:
        # EoD-trailing — intraday wicks don't update high_water.
        return state

    def update_on_eod(self, state: AccountState) -> AccountState:
        new_hw = max(state.high_water_equity, state.equity)  # only at EoD
        return replace(state, high_water_equity=new_hw)

    def phantom_mll(self, state: AccountState) -> float:
        # EFA: floor = max(0, peak_eod_equity) - mll, capped at 0.
        floor = max(0.0, state.high_water_equity) - self.mll_amount
        return min(floor, 0.0)             # locks at 0 once peak reaches +MLL

    def is_locked(self, state: AccountState) -> bool:
        return state.high_water_equity >= self.mll_amount

    def max_position(self, symbol: str, state: AccountState) -> int:
        # Scaling plan, $50K EFA, Medium-confidence thresholds (research §2d).
        # CRITICAL: keyed off ACCUMULATED PROFIT, not absolute equity.
        # On a $50K EFA, equity > $50K from day one; gating on absolute equity
        # would always hit the unrestricted branch and silently bypass scaling.
        profit = state.equity - state.start_balance
        if profit < 1500:   cap_mini = 2
        elif profit < 2000: cap_mini = 3
        else:               cap_mini = 5
        if symbol.startswith("MNQ"): return cap_mini * 10
        if symbol.startswith("NQ"):  return cap_mini
        raise ValueError(f"Unsupported symbol for Topstep: {symbol}")
```

### 4.5 `NewsCalendar` pseudocode

```python
@dataclass(frozen=True)
class NewsEvent:
    time: datetime              # tz-aware
    name: str
    impact: str                 # "high" | "medium" | "low"

class YAMLNewsCalendar:
    def __init__(self, path: Path, config: NewsConfig):
        self.events = self._load(path)
        self.window_before = timedelta(minutes=config.window_minutes_before)
        self.window_after = timedelta(minutes=config.window_minutes_after)
        self.cap = config.max_position_during_window

    def in_window(self, now: datetime) -> bool:
        return any(
            e.time - self.window_before <= now <= e.time + self.window_after
            for e in self.events
            if e.impact == "high"
        )

    def max_position_during_window(self) -> int:
        return self.cap
```

### 4.6 Force-flatten scheduling — wire-up sequence

```
Nautilus engine startup
  └─ TopstepRiskGate.__init__
       ├─ assert single account
       ├─ assert tick cadence <= 1s
       ├─ clock.set_time_alert("15:10:00 America/Chicago", force_flatten)
       └─ subscribe to tick stream → on_tick → maybe force_flatten

  Every tick from driver:
    driver.publish(AccountState)
      └─ TopstepRiskGate.on_tick(state)
           ├─ new_state = policy.update_on_tick(state)
           └─ if new_state.equity <= policy.phantom_mll(new_state):
                  force_flatten("MLL_EQUITY_TOUCH")

  At 15:10:00 CT:
    clock fires alert
      └─ force_flatten("HARD_FLAT_TIME")
```

### 4.7 Phantom-MLL update flow on each tick (detailed sequence)

```
Tick arrives at driver
  ↓
driver builds AccountState snapshot:
  equity = cash + unrealized_pnl
  unrealized_pnl = sum_over_positions(qty * (mark - entry) * tick_value)
  ↓
TopstepRiskGate.on_tick(state):
  new_state = policy.update_on_tick(state)
    ↓
    if is_combine_policy:
      new_hw = max(state.high_water_equity, state.equity)
      if not state.is_locked and new_hw >= start_balance + MLL_AMOUNT:
        new_locked = True
        new_lock_point = start_balance
      return state.replace(high_water_equity=new_hw,
                           is_locked=new_locked,
                           lock_point=new_lock_point)
  ↓
  phantom = policy.phantom_mll(new_state)
  if new_state.equity <= phantom:
    force_flatten("MLL_EQUITY_TOUCH")    # idempotent
  ↓
  driver caches new_state for next approve_or_deny call
```

---

## 5. Testing strategy

### 5.1 Property-based tests (hypothesis)

For randomly generated `(OrderIntent, AccountState)` pairs, `TopstepRiskGate.approve_or_deny` must produce the same decision as a pure reference implementation written from the §3 rules table. The reference implementation lives in `tests/risk_engine/reference.py` and is *re-derived* from the spec for each test session — it is **not** the production code.

Properties to check:

1. **Determinism.** `approve_or_deny(intent, state) == approve_or_deny(intent, state)` for any inputs.
2. **No side effects.** `state` is byte-identical before and after the call (frozen dataclass plus equality check).
3. **Monotone in equity.** If `state_a.equity > state_b.equity` and all other fields equal, then `decision(state_a)` is at least as permissive as `decision(state_b)`. (Counterexample would indicate a sign bug.)
4. **Closes never denied by money rules.** A reducing-exposure intent is never denied by rules 2 or 3. (Closes can still be denied by rules 1 — no, rule 1 explicitly allows closes — or by rule 7.)
5. **Rule-order short-circuit.** If two rules would deny, the canonical `rule` field matches the lower-numbered rule.

### 5.2 Scenario tests

**5.2.1 — Bad day, MLL touches.** A simulated day where the strategy takes 3 losing trades in sequence; equity falls to within 5 ticks of phantom MLL; the fourth trade's worst-case-loss would breach. Assert:
- Rule 3 denies the fourth trade.
- If a subsequent tick has equity dip to `phantom_mll`, `force_flatten("MLL_EQUITY_TOUCH")` fires exactly once.
- After force-flatten, all subsequent `approve_or_deny` calls return `OrderDenied(rule="STRATEGY_DISABLED")`.

**5.2.2 — Phantom-MLL ratchet.** Equity climbs from 50_000 → 52_500. At equity = 52_000, the lock fires. Assert `state.is_locked == True`, `state.lock_point == 50_000`, and `phantom_mll(state) == 50_000` thereafter, even as `high_water_equity` continues to rise.

**5.2.3 — Equity touch is one-shot.** Two consecutive ticks both have `equity < phantom_mll`. Assert `force_flatten` is called exactly once (idempotency via `_flattening` latch).

**5.2.4 — Strategy bug: open after 15:00 CT.** A strategy emits a new-open intent at 15:05 CT. Assert `OrderDenied(rule="HARD_FLAT_PREEMPT")`.

**5.2.5 — Strategy bug: open at 15:11 CT.** Assert `OrderDenied(rule="HARD_FLAT_CLOCK")` AND that `force_flatten("HARD_FLAT_TIME")` has already been triggered by the clock alert at 15:10:00.

### 5.3 Boundary tests

Tabulated exhaustively for each money rule:

| Rule | At threshold | One tick below | One tick above |
|---|---|---|---|
| 2 (DLL) | `realized + worst_case == -DLL` → deny | `> -DLL` → allow | `< -DLL` → deny |
| 3 (MLL) | `equity - worst_case == phantom_mll` → deny | strictly greater → allow | strictly less → deny |
| 4 (max pos) | `|proj| == cap` → allow | `< cap` → allow | `> cap` → deny |
| 5 (news cap) | `|proj| == news_cap` → allow | `< news_cap` → allow | `> news_cap` → deny |

The `≤` vs `<` choices are conscious (see §3.2 rule 2, rule 3). The boundary tests pin them.

### 5.4 Time-zone tests

Two DST transition days each year:

- **2026-03-08** (spring forward, 02:00 → 03:00 local). Clock alert for "15:10:00 America/Chicago" must fire at the correct wall-clock instant, equivalent to 20:10 UTC.
- **2026-11-01** (fall back, 02:00 → 01:00 local). Same test, equivalent to 21:10 UTC on this date.

Tests run with `freezegun` or equivalent, asserting that the Nautilus clock-alert handler is invoked exactly once at the expected UTC instant.

### 5.5 News-window tests

- Order during FOMC window, `qty=3`, `news_cap=1` → `OrderDenied(rule="NEWS_THROTTLE")`.
- Same order 6 minutes *before* event → allowed (outside `[T-5, T+15]`).
- Same order 16 minutes *after* event → allowed.
- Existing 3-contract position when window opens → no denial of incoming closes; `NEWS_WINDOW_OVERSIZED` warning emitted to telemetry mock.

### 5.6 Multi-DrawdownPolicy tests

The same `(intent, equity, realized_pnl)` triple is fed through `CombineIntradayDrawdown`, `EFAStandardEoDDrawdown`, and `EFAConsistencyDrawdown`. Assert:

- A scenario that the Combine policy denies (intraday wick) is allowed by the EFA Standard policy (EoD only).
- A scenario that the EFA Standard policy allows (no consistency check) may be denied by the EFA Consistency policy (40% breach).
- A scenario all three deny (e.g., DLL breach) produces identical `rule` fields.

### 5.7 Stop-buffer tests

- Strategy emits intent with `stop_loss_ticks = 20` when `phantom_mll_in_ticks = 30`, `safety_buffer = 5`. Assert approved intent has `stop_loss_ticks = 20` (strategy's stop is already tighter than the buffer floor).
- Strategy emits intent with `stop_loss_ticks = 28` when `phantom_mll_in_ticks = 30`, `safety_buffer = 5`. Assert approved intent has `stop_loss_ticks = 25` (capped by `30 - 5`).
- Strategy emits intent with `stop_loss_ticks = 28` when `phantom_mll_in_ticks = 4`, `safety_buffer = 5`. Assert `OrderDenied(rule="MLL_PROXIMITY")`.

### 5.8 Conformance with execution clients

A small integration test asserts: a strategy emitting an intent that violates rule N never sees `ExecutionClient.submit` invoked. Mock the execution client; assert `submit.call_count == 0` on any `OrderDenied` outcome. This catches the structural-bypass class of bug (00 §7 implicit invariant).

---

## 6. Open questions

1. **News calendar source for v2.** Which API integrates cleanly in 2026?
   - **Trading Economics** (~$50/mo, comprehensive, REST + Python SDK) — most likely choice if budget allows.
   - **FRED-derived ICS** (free, partial; US macro only; misses FOMC press conferences) — backup.
   - **Investing.com** — TOS-restricted; programmatic access prohibited. Not viable.
   Decision needed before live deployment of EFA stage; until then, manual YAML is acceptable.

2. **Stop-offset safety buffer width.** Is 5 ticks enough on a fast NQ day? An NQ tick is 0.25 pt = $5; a CPI/FOMC release can move NQ 30+ pts in 60 seconds. Validate via Monte-Carlo replay over historical high-impact-day tick data (see `05-backtest-harness.md`). Possibly make the buffer regime-dependent (wider in news regime, narrower in lunch lull).

3. **Consistency-rule mode: hard deny vs soft warn?** Default soft (so the bot can still take the trade and dilute via subsequent days). A user who wants the bot to *force* restraint could flip to hard. Document the trade-off explicitly in `07-config-and-deploy.md`; default `soft`. Re-evaluate after first 5 Combine simulations.

4. **HFT cancel-to-fill threshold.** Topstep's threshold is officially undefined (research §9). Default 5.0/60-min is conservative but unvalidated. After ~1 week of live paper, measure the bot's actual ratio under normal operation and tune the threshold to ~3x the observed steady-state.

5. **EFA scaling-plan thresholds re-verification.** Research §2d marks these Medium confidence (Topstep publishes them as an image). Before any EFA live deployment, the operator must verify the current numbers from the TopstepX in-platform Trade Report. The `EFAStandardEoDDrawdown.max_position` constants must be tagged with the verification date; a startup warning fires if it is >90 days old.

6. **`NEWS_WINDOW_OVERSIZED` action.** Currently the gate warns but does not force-trim a position oversized at window entry. Should it auto-emit a trim intent? Risks fighting the strategy's exit logic. Defer to v2 once we have a session's worth of data on how often the situation arises.

7. **Force-flatten on broker error.** §3.5 escalates hard if `close_all_positions` raises. What is the operator's recovery contract? Telegram-page-the-operator-then-halt seems right, but the page mechanism lives in `06-observability.md`; cross-reference once that spec lands.

8. **Tick-cadence floor on backtest driver.** The startup assertion `tick_cadence_seconds <= 1.0` is correct for live; on a backtest with 1-min bars, ticks aren't 1-Hz. Backtest mode must either (a) synthesize sub-bar ticks from OHLC (introduces bias), or (b) accept that the backtest understates real MLL risk and document the limitation prominently. v1 choice: accept (b), with a loud warning in the backtest report (see `05-backtest-harness.md`).

---

## 7. References

- `00-architecture-overview.md` — locked decisions D1, D3, D8; rule constants table §5; critical defensive items §7.
- `02-execution-clients.md` — `OrderIntent`, `OrderEvent`, `PositionEvent` definitions; `SIDE_BUY=0`/`SIDE_SELL=1` TopstepX inversion; conformance test suite.
- `03-strategies.md` — Surge / Maintenance YAML profiles; stop placement convention; flattening cadence.
- `05-backtest-harness.md` — Monte-Carlo replay for stop-buffer validation (§6.2); backtest tick-cadence limitation (§6.8).
- `07-config-and-deploy.md` — `DrawdownPolicy` selection; consistency-mode toggle; news-calendar file path; broker-truth reconciliation on startup.
- `../research/topstep-rules.md` — primary rule research, especially §2a (Combine MLL real-time on unrealized), §3 (consistency rules), §6 (news trading), §9 (HFT, VPS, cross-account).
- Topstep MLL article: <https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit>
- Topstep prohibited strategies: <https://help.topstep.com/en/articles/10305426-prohibited-trading-strategies-at-topstep>
- Topstep scaling plan (image-rendered table; Medium confidence numbers): <https://help.topstep.com/en/articles/8284223-what-is-the-scaling-plan>
- Topstep consistency: <https://help.topstep.com/en/articles/8284208-what-is-the-consistency-target>
