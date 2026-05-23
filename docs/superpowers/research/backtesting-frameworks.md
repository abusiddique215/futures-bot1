# Backtesting Frameworks Evaluation for NQ/MNQ Futures + Topstep Prop-Firm Rules

Research date: 2026-05-22
Use case: Python intraday algo bot trading NQ/MNQ on 1m/5m, multi-strategy, Topstep-rule compliance (daily-loss / trailing drawdown / max contracts / flat-by-time), with backtest -> walk-forward -> paper -> live lifecycle.

---

## TL;DR Recommendation

**Primary: NautilusTrader.** Best fit because it is one engine for backtest + paper + live, has a real Python-side `RiskEngine` with pre-trade `OrderDenied` semantics, native futures instrument objects with tick size / multiplier, an Interactive Brokers futures adapter (continuous futures supported in v1.227.0, May 18 2026), and a Python `ExecutionClient` SDK suitable for building a TopstepX/ProjectX adapter. Trade-off is a steep first 2-3 weeks (event-driven, async, Rust/Cython core).

**Secondary: QuantConnect Lean (local CLI / Docker).** Closest competitor. Has a clean pre-trade gate via `BrokerageModel.CanSubmitOrder` overridable in Python, native continuous-futures rollover with `SymbolChangedEvent`, AlgoSeek NQ minute data, and the Algorithm Framework already has `RiskManagementModel`. Downsides: the open-source live-broker list does not include TopstepX/ProjectX; a custom brokerage adapter is C#, not Python; ergonomics tilt toward the QC cloud.

**Tertiary (research-side only): vectorbt / vectorbtpro.** Use exclusively for parameter sweeps and walk-forward grid searches against a fast vectorized model. Not the production engine.

**Do not use as the primary engine:** backtesting.py (single-asset by design, weak futures specs), backtrader (last push Aug 2024, effectively dormant), zipline-reloaded (futures support is bolt-on, last tagged release 2017), Alpaca for live (does not offer futures).

---

## Hard Constraints Discovered That Reshape the Question

1. **Alpaca cannot trade futures.** Confirmed via Alpaca docs and community forum. Their API supports stocks, ETFs, crypto, and options only. Remove Alpaca from the live-broker discussion for this bot.
2. **Topstep does not route through Alpaca/IBKR for users.** TopstepX exposes a **ProjectX Gateway REST + WebSocket API**. An active third-party Python SDK exists: `project-x-py` on PyPI (v3.3.4, Python 3.12+, async). None of the seven frameworks ships a native ProjectX adapter in 2026. **A custom broker adapter is required regardless of framework choice.** The framework should therefore be selected on (a) how clean the adapter seam is and (b) what language that adapter must be written in.
3. **Multi-year 1m NQ data is multi-GB.** Pandas-resident frameworks (backtesting.py, backtrader) feel that weight. Arrow / columnar / Cython-backed engines (Nautilus, Lean, vectorbt) handle it better.
4. **vectorbt free vs vectorbtpro.** Free vectorbt is in maintenance and does not have first-class futures contract specs. vectorbtpro has futures, is proprietary, and is a paid subscription (~$20/mo annual saver via Ko-fi). The polakowo/vectorbt repo is active (pushed 2026-04-25) but the development center of gravity has moved to vectorbtpro.

---

## Per-Framework Findings

Repo telemetry pulled 2026-05-22 via `gh api`.

### 1. backtesting.py (kernc/backtesting.py)

| Field | Value |
|---|---|
| Stars / open issues | 8.4k / 77 |
| Last push | 2025-12-20 |
| Maintenance | Active but slow |
| Futures specs | Not first-class. Has a `margin` parameter (1/leverage) but no tick-value/multiplier/expiry objects. Workarounds required for contract specs (confirmed in repo discussion #314). |
| Continuous rollover | Not built-in. DIY. |
| Intraday | Yes; user supplies OHLCV at any frequency. |
| Multi-strategy / multi-asset | **Hard wall.** Single-asset by design (confirmed by maintainer responses on issues #20, #1120). |
| Walk-forward | Not built-in. Roll your own. |
| Param optimization | Built-in grid + scikit-optimize SAMBO. |
| Execution sim | Simplistic; commission % only. |
| Live trading | None. Backtest-only library. |
| Topstep-rule seam | Would have to wrap `Strategy.buy/sell` and check rules in user code. Doable but no pre-trade engine concept. |
| Learning curve | Lowest in the list. |

**Verdict:** Excellent learning tool, wrong choice for this bot. Single-asset + no live + no broker-side rule engine = abandon for production.

### 2. vectorbt (polakowo/vectorbt) and vectorbtpro

| Field | Value |
|---|---|
| Stars / open issues (free) | 7.6k / 138 |
| Last push (free) | 2026-04-25 |
| vectorbtpro | Proprietary; paid; futures support is pro-only |
| Futures specs | Free: workarounds. Pro: first-class. |
| Continuous rollover | Pro: yes. Free: DIY. |
| Multi-strategy | Excellent for parameter sweeps; less ergonomic for stateful per-bar event strategies. |
| Walk-forward | Built-in cross-validation splitters. |
| Param optimization | This is the framework's strongest dimension. Vectorized grids in seconds. |
| Execution sim | Vectorized; slippage and commission models supported. Per-bar callbacks possible via Numba but lose JIT caching (mitigated via "staticization" in pro). |
| Live trading | Not natively. |
| Topstep-rule seam | Numba callback constraints make per-order rule logic awkward and slow. |

**Verdict:** Use as the **research-side optimizer** alongside Nautilus or Lean. Run vectorbt for parameter sweeps and walk-forward grids; run Nautilus/Lean for the high-fidelity event-driven backtest, paper, and live. Do not make it the production engine for a stateful, prop-firm-constrained bot.

### 3. nautilus_trader (nautechsystems/nautilus_trader)

| Field | Value |
|---|---|
| Stars / open issues | 22.9k / 70 |
| Last push | 2026-05-22 (today) |
| Latest release | v1.227.0 on 2026-05-18 |
| Maintenance | Excellent; near-daily commits |
| Futures specs | Native `FuturesContract` instrument objects with multiplier, tick size, lot size, expiry, margin. |
| Continuous rollover | Yes; continuous-futures aggregation added in v1.227.0 (May 2026). |
| Intraday | Tick, second, minute, bar - first-class. |
| Multi-strategy | Yes; multiple `Strategy` subclasses register with the engine and share an account. Clean swappable interface. |
| Walk-forward | Not packaged; you wire it via `BacktestEngine.reset()` per window. |
| Param optimization | Not packaged; integrate with Optuna or vectorbt for sweeps. |
| Execution sim | High fidelity. Latency, partial fills, slippage, commission, queue position. |
| Live trading | Same `Strategy` code; live adapters include Interactive Brokers (futures supported), Binance, Bybit, Databento for data, dYdX. **No TopstepX/ProjectX adapter shipped.** |
| **Topstep-rule seam** | **Best in class.** `RiskEngine` sits between Strategy and ExecutionEngine; pre-trade checks return `OrderDenied`. You add a custom `PreTradeRiskCheck`-style component in Python that consults a phantom-account state machine. Extension point is documented and Python-side. |
| Force-flat at cutoff | `self.clock.set_time_alert()` / `set_timer()` in Strategy fires a Python callback at a wall-clock time; trivial to close all positions. |
| Learning curve | Steepest of the realistic options. Event-driven, async, Rust + Cython core. First 2-3 weeks slow; productive after. |

**Verdict:** **The technically cleanest fit.** The RiskEngine seam, native futures, IB futures adapter, and identical-code lifecycle (backtest -> paper -> live) match the requirements one-to-one. The cost is real: build complexity, event-driven paradigm shift, and you will write the ProjectX adapter yourself in Python (using `project-x-py` as the underlying client and Nautilus's `LiveExecutionClient` SDK).

### 4. zipline-reloaded (stefan-jansen/zipline-reloaded)

| Field | Value |
|---|---|
| Stars / open issues | 1.8k / 42 |
| Last push | 2026-01-06 |
| Last tagged release | 2017 (release tagging is dead; commits continue on main) |
| Futures specs | Inherited from original Quantopian Zipline; bolt-on rather than idiomatic. |
| Continuous rollover | Limited, community-maintained. |
| Multi-asset | Yes (this is Zipline's heritage). |
| Live trading | Via QuantRocket (commercial). |
| Topstep-rule seam | No clean pre-trade engine; you would patch `Blotter`/`Slippage`. |

**Verdict:** Skip for this use case. Heritage is daily equity portfolio rebalancing, not intraday futures with prop-firm overlays.

### 5. QuantConnect Lean (QuantConnect/Lean)

| Field | Value |
|---|---|
| Stars / open issues | 19.1k / 249 |
| Last push | 2026-05-21 |
| Latest release | v1.0.0 on 2026-04-22 |
| Maintenance | Excellent; daily |
| Futures specs | First-class. Continuous futures via `add_future(...)` with `data_mapping_mode`, `data_normalization_mode`, `contract_depth_offset`. NQ included in AlgoSeek minute dataset. |
| Continuous rollover | Built-in. `on_symbol_changed_events` fires at midnight ET; idiomatic liquidate-and-reopen pattern documented. |
| Intraday | Tick, second, minute - first-class. |
| Multi-strategy | Algorithm Framework: Alpha + Portfolio Construction + Risk Management + Execution models all swappable. Clean. |
| Walk-forward | Not first-class; community examples exist. |
| Param optimization | Yes; local + cloud optimization in LEAN CLI. |
| Execution sim | High fidelity; configurable slippage / fill / fee models per security. |
| Live trading | The same Python algorithm runs locally via Docker (LEAN CLI) and live via QC's brokerage list. **TopstepX/ProjectX is NOT on the open-source brokerage list.** Adding one means a new `IBrokerage` implementation, which is **C# in Lean core**, even if the algorithm is Python. |
| **Topstep-rule seam** | Strong. Override `DefaultBrokerageModel.CanSubmitOrder` in Python (reference: `Algorithm.Python/BrokerageModelAlgorithm.py` in the Lean repo) and call `self.set_brokerage_model(MyTopstepModel())` in `Initialize`. Rejected orders fire `on_order_event` with `BrokerageModelRefusedToSubmitOrder`. Plus the Framework's `RiskManagementModel.manage_risk` for portfolio-level adjustments. |
| Force-flat at cutoff | `self.schedule.on(self.date_rules.every_day(), self.time_rules.at(15, 55), self.flatten_all)`. |
| Learning curve | Moderate. QC concepts and Algorithm Framework take a week to internalize; well documented. |

**Verdict:** Strong secondary. The **`CanSubmitOrder` Python override is the cleanest pre-trade seam in this evaluation**, arguably cleaner than Nautilus's for someone whose strength is Python+pandas. The gotcha is the live path: shipping ProjectX requires C# work in Lean core, OR you run the Python algorithm and route execution via your own external Python ProjectX bridge that listens to `on_order_event` and translates - workable but two moving parts.

### 6. backtrader (mementum/backtrader)

| Field | Value |
|---|---|
| Stars / open issues | 21.6k / 61 |
| Last push | **2024-08-19** |
| Last release | 2017 |
| Maintenance | **Dormant for ~21 months.** Active community forks exist but none has consolidated as the canonical successor. |
| Futures specs | Decent; `commission_info` per-instrument with `mult`, `commtype`, `commission`, `margin`. |
| Multi-strategy | Yes; multiple strategies in one Cerebro. |
| Topstep-rule seam | `notify_order` happens after submission; pre-trade rejection requires subclassing the broker. Doable but not idiomatic. |

**Verdict:** Mature but stagnant. Do not start a multi-year project on it in 2026. If you must use it, use the QuantWorld2022 community fork - but you take maintenance risk.

### 7. Newer 2025-2026 entrants worth knowing

- **NautilusTrader** itself is the standout of the past 18 months; v1.0 (April 2026) on vectorbt also signals continued investment.
- **lumibot** (Lumiwealth) - growing, equities-focused, weaker futures story than Nautilus.
- **fastquant**, **bt**, **pybacktest** - too thin for this use case.
- **project-x-py** (PyPI) - not a backtester, but the Python SDK that will sit underneath whatever live adapter you build for TopstepX. Worth pinning early.

---

## The Topstep Rule-Engine Seam: How Each Framework Handles It

This is the deciding criterion. Three things must compose cleanly:

1. **Per-order allow/deny check.** Strategy says "buy 2 MNQ"; rule engine inspects current phantom equity, position size, and time-of-day, then either lets it through or denies.
2. **Phantom account mirroring Topstep trailing drawdown.** A high-watermark-based trailing limit that locks at the funded threshold. Must update on every fill.
3. **Force-flat at configurable cutoff (e.g., 15:55 ET).**

| Framework | (1) Pre-trade gate | (2) Phantom account | (3) Force-flat |
|---|---|---|---|
| backtesting.py | Wrap `self.buy/sell` in Strategy base | Track in Strategy state | Compare bar timestamp in `next()` |
| vectorbt | Numba callback (awkward, cacheability cost) | Per-fill callback | Vectorized; not natural for wall-clock cutoff |
| **NautilusTrader** | **`RiskEngine` returns `OrderDenied`** | Account / Portfolio events + custom Actor | `self.clock.set_time_alert()` |
| zipline-reloaded | Subclass `Blotter` | Custom analyzer | Scheduled function |
| **QuantConnect Lean** | **Override `CanSubmitOrder` in Python custom BrokerageModel** | Custom risk model on top of `Portfolio` | `self.schedule.on(...)` |
| backtrader | Subclass `BrokerBase.submit` | `notify_trade` | `next()` time check or timer |

Nautilus and Lean are the only two with a documented, idiomatic, first-class pre-trade seam. Everything else needs monkey-patching or "wrap the strategy method" tricks.

### Portable fallback pattern (works in any framework)

Independent of framework choice, model the rule engine as a **plain Python class** outside the framework:

```python
class PropRuleEngine:
    def __init__(self, config): ...
    def check(self, proposed_order, phantom_account, now) -> Decision: ...
    def on_fill(self, fill): ...   # update phantom_account
    def force_flat_due(self, now) -> bool: ...

class StrategyBase(<framework>.Strategy):
    def submit(self, order):
        decision = self.rules.check(order, self.phantom, self.now)
        if decision.allow: super().submit(order)
        else: self.log.warning(decision.reason)
```

This pattern is portable. If you start in Nautilus and later swap engines, the rule engine code is unchanged. It is architecturally less clean than Nautilus's `RiskEngine` seam, but it survives a framework swap and works on day one in any of the seven.

---

## Decision Matrix Summary

| Criterion | backtesting.py | vectorbt(pro) | NautilusTrader | zipline-reloaded | Lean Local | backtrader |
|---|---|---|---|---|---|---|
| Native futures specs | weak | pro only | yes | weak | yes | ok |
| Continuous rollover | DIY | pro: yes | yes | weak | built-in | DIY |
| Intraday 1m/tick | yes | yes | yes | minute via bundle | yes | yes |
| Multi-strategy clean interface | no | sweeps yes / stateful no | yes | yes | yes (Framework) | yes |
| Walk-forward built-in | no | yes | manual | manual | manual | manual |
| Realistic exec sim | basic | good | excellent | ok | excellent | good |
| Live trading w/ same code | no | no | yes (IB futures) | via QuantRocket | yes (QC brokers; not Topstep) | yes (community adapters) |
| Pre-trade rule seam in Python | wrap method | callback hack | RiskEngine | subclass Blotter | CanSubmitOrder | subclass broker |
| Maintenance pulse | active | active (free) / active (pro) | excellent | quiet | excellent | dormant |
| Learning curve | gentle | medium | steep | medium | medium | medium |

---

## Final Recommendation with Reasoning

**Adopt NautilusTrader as the production engine.**

Reasoning:
- It is the only option in the list designed as one engine for backtest, paper, and live with the same `Strategy` code. That collapses the four lifecycle phases into one codebase.
- Its `RiskEngine` is the most direct expression of "interpose a rule engine between strategy and execution" that exists in any of these frameworks.
- Native futures instruments + continuous-futures aggregation (added May 2026) match the NQ/MNQ requirement.
- Adapter SDK is Python, so the ProjectX adapter you will have to write is Python, not C#.
- Maintenance pulse is the strongest of the group: 22.9k stars, daily commits, v1.227.0 a week before this evaluation.

**Tiebreakers that settled it over Lean:**
1. **Language of the broker/risk adapter.** Nautilus extensions are Python/Cython; Lean's custom brokerage extensions are C#. The user is a Python+pandas developer.
2. **Live execution is local-first in Nautilus**; in Lean Local you still depend on QC's brokerage list for first-class live support and TopstepX is not on it.
3. **Single-engine lifecycle.** Same `Strategy` class runs backtest -> paper -> live unchanged. Lean does this too but the live story for non-Lean brokerages is rougher.

**Honest caveats:**
- The first 2-3 weeks with Nautilus will feel slow. Event-driven thinking + async + actor model + occasional Cython recompiles. Budget for it.
- Walk-forward is not packaged in Nautilus; you orchestrate it via `BacktestEngine.reset()` per window, or run vectorbt(pro) for the sweep and Nautilus for the final high-fidelity validation.
- You will build the TopstepX/ProjectX `LiveExecutionClient` yourself. Use `project-x-py` as the underlying HTTP/WS client. Plan ~1-2 weeks for a first paper-grade adapter.

**If after a one-week spike Nautilus feels too heavy, fall back to QuantConnect Lean Local CLI.** It is the closest alternative and the `CanSubmitOrder` Python override is genuinely clean. Trade-off is the C# barrier when you later need a custom TopstepX brokerage.

**Use vectorbt (free, or pro if budget allows) for parameter sweeps and walk-forward grids** regardless of which production engine you pick. Different tools for different jobs.

---

## Deal-Breakers (flagged explicitly)

- **Alpaca does not trade futures.** Strike from live-broker comparison.
- **backtrader: dormant** (last push Aug 2024). Do not start new 2026 work on it.
- **backtesting.py: single-asset by design.** Confirmed in maintainer responses. Hard wall for multi-strategy futures.
- **zipline-reloaded: futures bolt-on, tagged-release cadence dead.** Wrong heritage.
- **vectorbtpro: paid subscription** (~$20/mo annual saver) and proprietary. Free vectorbt is fine for sweeps but lacks first-class futures.
- **Lean custom brokerage**: writing one means C#, not Python. The `CanSubmitOrder` model override is Python; the brokerage transport is not.
- **NautilusTrader build complexity:** mixed Rust + Cython + Python. Wheels usually work on macOS/Linux; if you hit a build, expect to install the Rust toolchain.

---

## Recommended Stack to Start

1. NautilusTrader v1.227+ as the engine.
2. `project-x-py` as the TopstepX gateway client.
3. A Python `LiveExecutionClient` you write that bridges Nautilus to `project-x-py` for live; for backtests use Nautilus's built-in simulated venue.
4. Phantom account + Topstep rule engine implemented as a Nautilus `Actor` or as a custom component invoked from a `RiskEngine` pre-trade check.
5. vectorbt for offline parameter sweeps / walk-forward grids.
6. Databento or AlgoSeek (via QC if you also keep Lean around) for historical 1m NQ data.

---

## Sources

- [backtesting.py repo](https://github.com/kernc/backtesting.py) and [issue #1120 / discussion #314](https://github.com/kernc/backtesting.py/discussions/314)
- [NautilusTrader docs - Risk](https://nautilustrader.io/docs/latest/api_reference/risk/), [Strategies](https://nautilustrader.io/docs/latest/concepts/strategies/), [IB integration](https://nautilustrader.io/docs/latest/integrations/ib/), [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/)
- [QuantConnect Lean - Brokerages Key Concepts](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/brokerages/key-concepts), [Order Errors](https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/order-errors), [Futures Universes](https://www.quantconnect.com/docs/v2/writing-algorithms/universes/futures), [Handling Futures Data](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/futures/handling-data), [Risk Management Key Concepts](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/risk-management/key-concepts)
- [Lean Python BrokerageModelAlgorithm.py](https://github.com/QuantConnect/Lean/blob/master/Algorithm.Python/BrokerageModelAlgorithm.py)
- [LEAN CLI](https://github.com/QuantConnect/lean-cli)
- [VectorBT free](https://github.com/polakowo/vectorbt), [VectorBT PRO](https://vectorbt.pro/), [VectorBT PRO pricing](https://ko-fi.com/s/88d8ca176c)
- [backtrader Cerebro](https://www.backtrader.com/docu/cerebro/), [Strategy](https://www.backtrader.com/docu/strategy/)
- [zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded)
- [Alpaca futures fees article (BrokerChooser)](https://brokerchooser.com/broker-reviews/alpaca-trading-review/micro-emini-nasdaq100-futures-fees) and [Alpaca futures request thread](https://forum.alpaca.markets/t/futures-trade-in-alpaca/11632) confirming no futures via API
- [project-x-py SDK on PyPI](https://pypi.org/project/project-x-py/) and [docs](https://project-x-py.readthedocs.io/en/latest/quickstart.html)
- [TopstepX API Access help](https://help.topstep.com/en/articles/11187768-topstepx-api-access)
