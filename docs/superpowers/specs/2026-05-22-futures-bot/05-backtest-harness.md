# 05 — Backtest Harness

**Project**: Topstep Futures Trading Bot
**Date**: 2026-05-22
**Status**: Spec — research phase
**Owner**: abu.siddique215@gmail.com

---

## 1. Purpose

Wrap Nautilus's `BacktestEngine` with four research workflows the production engine does not ship out of the box:

1. **Walk-forward** — rolling train/test windows; the single best defense against curve-fit.
2. **Parameter sweep** — grid search over YAML profile params (Surge / Maintenance) parallelized across cores.
3. **Monte Carlo** — shuffle historical trade order N times → drawdown distribution → 95th-percentile worst-case.
4. **Topstep rule-replay** — every simulated fill re-enters `TopstepRiskGate` so the report tells us how often the bot *would* have busted the Combine, not just its raw PnL.

The harness is research infrastructure. It does not touch a broker. It does not bypass the Strategy → RiskGate → ExecutionClient pipeline — it replays it offline against historical data.

**Parity guarantee** (inherited from `00 §4`): the *same* `Strategy` subclass runs here, in IB paper, and on TopstepX live. The harness wraps Nautilus; it does not fork the strategy.

---

## 2. Inherited decisions

From `00-architecture-overview.md`:

- **D8 — NautilusTrader** is the runtime. The harness extends `BacktestEngine`; it does not reimplement event-driven simulation.
- **D11 — Ratio-adjusted continuous-contract roll.** Backtest data uses the same adjustment method as live; otherwise we test a different instrument than we trade. See `01-data-pipeline.md` for the canonical loader the harness consumes.
- **D9 — FirstRateData** historical 1-min NQ/MNQ is the data source; snapshot hash is pinned per run for reproducibility.
- **D4 — One Strategy class, two YAML profiles** (Surge / Maintenance). The sweep grids profile params, not strategy classes.
- **§5 — Topstep $50K Combine rule constants** drive the rule-replay reporter and the Combine pass/fail flag on every window.

---

## 3. Design

### 3.1 Harness role

Thin orchestration around `nautilus_trader.backtest.BacktestEngine`. Responsibilities:

- Construct an engine with the correct `FuturesContract`, fill model, commission model, and starting account.
- Inject the `Strategy` instance the production system uses, parametrized from a YAML profile.
- Inject `TopstepRiskGate` (from `04-risk-engine.md`) as a Nautilus `RiskEngine` extension — identical to live.
- Loop the engine over (window | param-cell | mc-run) and aggregate results.
- Emit a report bundle that humans and CI can both read.

The harness **never** holds strategy state. State lives in the Strategy. The harness only drives the engine and collects outputs.

### 3.2 CLI surface

One entrypoint, subcommands per workflow:

```
python -m bot.backtest --strategy=orb --profile=surge --account=combine_50k \
    --start=2020-01-01 --end=2025-12-31

python -m bot.backtest sweep \
    --strategy=orb --profile=surge \
    --param=stop_atr_multiplier:0.5:2.0:0.1 \
    --param=tp_r:1.0:3.0:0.5

python -m bot.backtest walk-forward \
    --strategy=orb --profile=surge \
    --train-months=6 --test-months=2 --windows=12

python -m bot.backtest monte-carlo \
    --from-run=<run-id> --runs=1000
```

Common flags: `--seed`, `--data-snapshot=<hash>`, `--report-dir=reports/`, `--workers=N`, `--account=combine_50k|funded_50k`.

The bare invocation (no subcommand) is the single deterministic backtest — the building block every other subcommand calls.

### 3.3 Walk-forward

Rolling train/test windows over the full history.

- Default: `train=6mo`, `test=2mo`, step = test window (no overlap on test).
- N windows = `(history − train) // test`. At 5y history that's 24 windows; cap with `--windows`.
- "Train" in our context = parameter selection window. The Strategy itself does not learn online; sweep+select happens on train, the selected params are then frozen on test.
- Two modes: **anchored** (train start fixed, train window grows) and **rolling** (train window fixed length, both ends slide). Default rolling.
- Per-window metrics: net PnL, Sharpe, Sortino, max drawdown, win rate, profit factor, expectancy, trade count, **Combine pass/fail flag** (would this window have busted the 50K Combine? = phantom-MLL touched OR DLL touched OR consistency rule violated).
- Aggregate report: pass rate across windows; out-of-sample equity curve stitched from test segments only.

A strategy that passes the Combine on the in-sample sweep but fails on 6 of 12 walk-forward test windows is overfit — kill it before paper.

### 3.4 Parameter sweep

Grid search over profile params. Source of truth for grid axes = the profile schema in `03-strategies.md` (only declared params are tunable).

- Grid parsed from `--param=name:start:stop:step` (inclusive at both ends; numpy `arange`-style with epsilon).
- Categorical grids accepted as `--param=name:a,b,c`.
- Cartesian product of all `--param` declarations. Hard cap: 5,000 cells per invocation (refuse to run; user must narrow). Prevents accidental 10,000-cell sweeps.
- Parallelize via `multiprocessing.Pool(workers)`. Each worker constructs its own `BacktestEngine` (Nautilus engines are not thread-safe; processes only).
- Determinism: every cell gets its own seed derived from `(base_seed, cell_index)`. Same `base_seed` reproduces identically.
- Output:
  - `sweep.parquet` — one row per cell with all params + all metrics.
  - `heatmap.png` — top-2 params (by variance in PnL) on x/y, color = net PnL. matplotlib, no seaborn dep.
  - `top10.md` — top 10 cells by primary objective (default: profit factor with min-trades filter).

### 3.5 Monte Carlo

Takes a single completed backtest and bootstraps a drawdown distribution.

- Input: the per-trade journal from a base run (`trades.parquet`, columns: pnl, duration, side).
- Method: **trade-return bootstrap**. Resample N=1000 trade sequences with replacement (or shuffle without replacement; see §6), compute cumulative equity curve, record max drawdown per run.
- Output: histogram of max drawdowns, 50th/90th/95th/99th percentile.
- **Pass criterion**: 95th-percentile MaxDD < Topstep MLL ($2,000 at 50K). If it's not, the strategy is one bad trade-order shuffle from busting the Combine.
- Optional richer mode (`--bootstrap=fills`): resample fills with per-bar slippage noise. More realistic, more compute. Default off; see §6.

Monte Carlo answers "is the historical equity curve a fluke?" Walk-forward answers "does the edge persist across regimes?" Both are required; neither subsumes the other.

### 3.6 Topstep rule-replay

Every simulated order from every backtest passes through `TopstepRiskGate` (from `04-risk-engine.md`) with the simulated `AccountState`. The replay reporter records:

- Orders submitted vs orders approved vs orders denied (by `OrderDenied` reason code).
- Denial frequency by reason: phantom-MLL proximity, DLL approached, position-size cap, hard-flat window, news throttle, consistency rule.
- **Combine bust flag per day**: any tick where phantom-MLL was touched → that day is a Combine failure. Any day with this flag = walk-forward window fails.
- DLL touches per day, MLL high-water-mark per day, max drawdown per day.

This is the *actual* Topstep simulation. The raw equity curve is misleading on its own — a strategy with a great Sharpe and a single $2,100 intraday drawdown still busts the Combine.

### 3.7 Reproducibility

A backtest is reproducible iff identical inputs → identical outputs. The harness pins:

- `seed` — int, in config, threaded to Nautilus + numpy + python `random`.
- `strategy_version` — git SHA of the strategy module (refuse to run on dirty tree unless `--allow-dirty`).
- `data_snapshot_hash` — SHA-256 of the FirstRateData parquet bundle. Loader (in `01-data-pipeline.md`) emits this.
- `harness_version` — git SHA of `bot/backtest/`.
- `nautilus_version` — pinned in `pyproject.toml`, recorded in manifest.

All five land in `manifest.json` alongside every report bundle. CI replays manifests as a smoke test.

### 3.8 Reports

Saved to `reports/<YYYY-MM-DD>/<strategy>-<profile>-<run-id>/`:

```
manifest.json              # seed, snapshot hash, versions, CLI args
metrics.json               # headline stats
trades.parquet             # per-trade journal
fills.parquet              # per-fill journal
rule_denials.parquet       # every OrderDenied with reason + state
equity_curve.png
drawdown.png
monthly_returns.png        # heatmap year × month
rule_replay_summary.md     # human-readable Topstep rule-replay
walk_forward.parquet       # only on walk-forward runs
sweep.parquet              # only on sweep runs
heatmap.png                # only on sweep runs
mc_distribution.png        # only on MC runs
```

`run-id` = first 8 of `sha256(manifest_canonical_json)`. Identical inputs collide on disk by design — re-running a deterministic backtest overwrites bit-identical outputs.

### 3.9 Deterministic vs Monte Carlo

| Workflow | Determinism | Use |
|---|---|---|
| Single backtest | Fully deterministic given seed + data + params. | Sanity, debugging, CI regression. |
| Parameter sweep | Each cell deterministic. Cell results identical across runs. | Find candidate params. |
| Walk-forward | Each window deterministic. | Validate out-of-sample. |
| Monte Carlo | Randomized **on top of** a deterministic base result. | Worst-case drawdown bound. |

Never randomize the base backtest. Randomness is a layer applied to deterministic outputs, never mixed in.

---

## 4. Implementation sketch

Python 3.12. `bot/backtest/` package. Pseudocode only — interfaces, not bodies.

```python
# bot/backtest/runner.py
from dataclasses import dataclass
from nautilus_trader.backtest.engine import BacktestEngine

@dataclass(frozen=True)
class BacktestResult:
    manifest: dict
    metrics: dict            # net_pnl, sharpe, sortino, max_dd, win_rate, profit_factor
    trades: "pd.DataFrame"
    fills: "pd.DataFrame"
    rule_denials: "pd.DataFrame"
    equity_curve: "pd.Series"
    combine_pass: bool       # phantom-MLL never touched

class BacktestRunner:
    def __init__(self, strategy_factory, data, account_config, seed: int):
        self.strategy_factory = strategy_factory  # () -> Strategy
        self.data = data                          # loader from 01-data-pipeline
        self.account_config = account_config      # combine_50k | funded_50k
        self.seed = seed

    def run(self) -> BacktestResult:
        engine = self._build_engine()
        engine.add_strategy(self.strategy_factory())
        engine.add_risk_engine(TopstepRiskGate(self.account_config))  # from 04
        engine.run()
        return self._collect(engine)

    def _build_engine(self) -> BacktestEngine: ...
    def _collect(self, engine) -> BacktestResult: ...
```

```python
# bot/backtest/walk_forward.py
@dataclass(frozen=True)
class Window:
    train_start: "datetime"
    train_end: "datetime"
    test_start: "datetime"
    test_end: "datetime"

class WalkForwardOrchestrator:
    def __init__(self, base_config, train_months: int, test_months: int,
                 windows: int | None = None, mode: str = "rolling"):
        self.base_config = base_config
        self.train_months = train_months
        self.test_months = test_months
        self.windows = windows
        self.mode = mode  # "rolling" | "anchored"

    def windows_for(self, start, end) -> list[Window]: ...

    def run_all(self) -> list[BacktestResult]:
        results = []
        for w in self.windows_for(self.base_config.start, self.base_config.end):
            params = self._select_on_train(w)                # sweep on train
            results.append(self._evaluate_on_test(w, params))  # frozen on test
        return results
```

```python
# bot/backtest/sweep.py
class ParameterSweep:
    def __init__(self, base_config, param_grid: dict[str, list]):
        self.base_config = base_config
        self.param_grid = param_grid  # {"stop_atr_multiplier": [0.5, 0.6, ...], ...}

    def cells(self) -> list[dict]:
        # cartesian product; raise if > 5_000
        ...

    def run_parallel(self, workers: int) -> "SweepResults":
        with multiprocessing.Pool(workers) as pool:
            rows = pool.map(_run_cell, self.cells())
        return SweepResults(rows)

def _run_cell(cell: dict) -> dict:
    config = merge(BASE, cell)
    result = BacktestRunner(...).run()
    return {**cell, **result.metrics, "combine_pass": result.combine_pass}
```

```python
# bot/backtest/monte_carlo.py
class MonteCarloRunner:
    def __init__(self, base_result: BacktestResult, runs: int = 1000, seed: int = 0,
                 method: str = "trade_bootstrap"):
        self.trades = base_result.trades
        self.runs = runs
        self.seed = seed
        self.method = method  # "trade_bootstrap" | "fill_resample"

    def run(self) -> "MCResults":
        rng = np.random.default_rng(self.seed)
        drawdowns = []
        for _ in range(self.runs):
            shuffled = self.trades.sample(frac=1.0, replace=True, random_state=rng)
            equity = shuffled.pnl.cumsum()
            drawdowns.append(_max_drawdown(equity))
        return MCResults(distribution=np.array(drawdowns))
```

```python
# bot/backtest/rule_replay.py
class TopstepRuleReplay:
    def __init__(self, gate: "TopstepRiskGate", fills: "pd.DataFrame"):
        self.gate = gate
        self.fills = fills

    def summary(self) -> "RuleReplaySummary":
        # replays fills through gate, returns
        # {denials_by_reason, daily_mll_touches, daily_dll_touches, combine_busts}
        ...
```

```python
# bot/backtest/__main__.py
def main(argv):
    args = parse(argv)
    match args.command:
        case None:           BacktestRunner(...).run()
        case "sweep":        ParameterSweep(...).run_parallel(args.workers)
        case "walk-forward": WalkForwardOrchestrator(...).run_all()
        case "monte-carlo":  MonteCarloRunner(load(args.from_run), args.runs).run()
```

---

## 5. Testing strategy

Four invariants. Each gets a test; CI fails on any regression.

1. **Determinism.** Same seed + same data snapshot + same params → byte-identical `equity_curve.parquet` and `trades.parquet`. Run twice, `hashlib.sha256` both, assert equal. Catches every "did I just introduce a hidden RNG call" bug.

2. **Walk-forward sanity (positive control).** Inject a synthetic always-profitable strategy (`return BUY at open, SELL at close, fixed +$5/contract`). Every walk-forward window must pass (positive PnL, no MLL touch, `combine_pass=True`). If any window flags red, the orchestrator is wrong, not the strategy.

3. **Monte Carlo (analytical control).** Inject synthetic trades drawn from `N(0, sigma)` random walks. The 95th-percentile MaxDD from the harness must land within 2× of the analytical expectation `≈ sigma * sqrt(n) * 1.96` for the resampling distribution. Loose bound — we're checking we're in the right order of magnitude, not validating the math exactly.

4. **Rule-replay (negative control).** Craft a known fill sequence that drives unrealized PnL past the $2,000 MLL within one bar. Replay must flag `combine_pass=False` and emit a `phantom_mll_touched` rule-denial. If it doesn't, the rule replay isn't actually calling the gate.

Bonus: **conformance with live.** Run the same Strategy + same fills through `TopstepRiskGate` directly (no backtest engine) and through the harness. Denial sets must match. This is the same property the execution-client conformance suite asserts in `02-execution-clients.md`.

---

## 6. Open questions

1. **Walk-forward window ratio.** 6mo/2mo (3:1) is the academic standard but ORB is a short-horizon intraday strategy; train signal may saturate in 2-3 months. Resolve empirically: sweep `(train, test) ∈ {(3,1), (6,2), (12,3)}` and pick the ratio whose selected params hold up best on test. Decide before locking the production walk-forward config.

2. **Parameter sweep parallelism: process pool vs Nautilus's own parallel backtests.** `multiprocessing.Pool` is simple and deterministic; Nautilus has internal parallel backtest support (newer; less battle-tested with our `RiskEngine` extension). Process pool by default; revisit if startup overhead dominates (each engine construct + warmup + teardown is several seconds).

3. **Monte Carlo: trade-return bootstrap vs fill-level resampling.** Trade bootstrap assumes trades are i.i.d. — false if the strategy clusters losses (e.g., regime-dependent). Fill-level resampling adds bar noise but is much more work and slow. Default: trade bootstrap. Build fill-resample as `--bootstrap=fills` opt-in; revisit if walk-forward shows regime-clustered loss runs.

4. **Cost modeling defaults.** Pin in `config/backtest.yaml`:
   - Commission: `$0.50/contract round-trip` MNQ at TopstepX (Topstep posts the actual sheet; confirm and pin).
   - Slippage: `1 tick` (= $0.25 on MNQ) on market orders; `0 ticks` on limits that filled at limit price; `2 ticks` on market orders during 09:30-09:35 ET (open) and 14:55-15:10 ET (close window).
   - These are conservative defaults. Backtest reports should be honest about cost assumptions; surface them in `manifest.json`.

5. **Combine bust detection: which gate state actually busts?** MLL touch is unambiguous. DLL touch is unambiguous. Consistency rule (best-day ≤ 50% of profit target) only resolves at the end of a Combine attempt, not intra-window — does the harness count a window as "bust" only if MLL/DLL violated, or also if consistency would have been violated by run-end? Default: flag MLL/DLL intra-window; emit a separate end-of-run consistency check.

6. **Methodological gap (flagged): walk-forward parameter-selection feedback loop.** Selecting params per-window from a sweep means the harness *itself* introduces a degree of overfitting at the meta-level (we are fitting the sweep procedure to history). Best mitigation is to also report a **frozen-params** walk-forward: pick params once on the first window, hold them constant across all later test windows. Compare. If frozen and adaptive walk-forward agree, the strategy has real edge. If only adaptive works, we are overfitting selection. **This belongs in the v1 harness as a parallel report, not a follow-up.**

---

## 7. References

- `00-architecture-overview.md` — D8 (Nautilus), D11 (continuous roll), §5 (Topstep rule constants).
- `01-data-pipeline.md` — historical loader, snapshot hashing, continuous-roll implementation.
- `02-execution-clients.md` — conformance test suite (same property the harness asserts in §5 bonus).
- `03-strategies.md` — Strategy class, profile schema (defines sweep grid axes).
- `04-risk-engine.md` — `TopstepRiskGate`, `DrawdownPolicy`, phantom-MLL state machine.
- `../research/backtesting-frameworks.md` — Nautilus rationale, alternatives (Lean, vectorbt) considered and rejected for production but vectorbt usable for offline sweeps.
- NautilusTrader `BacktestEngine` docs: `https://nautilustrader.io/docs/latest/concepts/backtesting/`
- López de Prado, *Advances in Financial Machine Learning* — Ch. 11 (combinatorial purged cross-validation; future upgrade path for walk-forward).
- Pardo, *The Evaluation and Optimization of Trading Strategies* — walk-forward methodology canonical reference.
