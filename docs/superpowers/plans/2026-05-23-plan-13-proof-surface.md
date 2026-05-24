# Plan 13 — Proof Surface Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Pull reporting out of `BacktestEngine` into a first-class product feature that mirrors the VSL's proof surface (TradingView-style Strategy Report screens + equity curves visible at ~18:00, 19:00, 20:00 in the video). After this plan: any bot — backtest or live — can emit a per-bot proof report on demand, matching the metric shape the VSL sells with.

**Architecture:** New `bot.proof` package. `StrategyReport` dataclass captures the 5 headline metrics observed in the VSL (net profit, max drawdown, total trades, % profitable, profit factor) plus secondary metrics (avg trade, win/loss, avg holding time, sharpe-light). `ProofGenerator` consumes either a `TradeLog` (from backtest) or a `Journal` (from live trading) and emits a `StrategyReport` + an equity-curve PNG (matplotlib, the one heavy dep already in the project's dev tree for backtest plots) + an HTML page. CLI `python -m bot.proof <source>` outputs the proof bundle.

**Tech Stack:** Reuses `bot.backtest.tracker.AccountStateTracker`, `bot.backtest.report.TradeReport`, `bot.journal.Journal`. Adds matplotlib (already in pyproject.toml dev deps for the existing report module). No new prod deps.

**Scope notes:**
- The VSL shows TradingView reports with specific metric labels: "Net Profit," "Max Drawdown," "Total Trades," "% Profitable," "Profit Factor." Our `StrategyReport` mirrors these labels verbatim so the product feels familiar.
- Equity curve = cumulative P&L over time as a PNG. HTML wrapper embeds the PNG + the metric table.
- Per-bot: each ResolvedBot from Plan 12 gets its own report. The CLI accepts `--bot <name>` to filter from the fleet journal layout.
- Proof reports are *generated*, not stored as a live web service. (Plan 21 dashboard adds the live web surface.)
- Output dir defaults to `state/proof/<bot_name>_<timestamp>/` containing `report.json`, `equity_curve.png`, `report.html`.

**Deliverable:**
- `python -m bot.proof --journal state/journal_xxx.db --bot example_orb_nq` produces the 3-file proof bundle.
- `python -m bot.proof --backtest <trade_log.json>` does the same from a backtest TradeLog.
- HTML opens in a browser and visually matches the VSL Strategy Report shape (metric table top, equity curve below).
- New tests cover: metric calculation, PNG generation (file exists + non-zero size), HTML rendering (contains expected strings).
- CI green (~572 + ~15 new tests).
- Tag `plan-13-proof-surface-complete`.

---

## File structure

- Create: `src/bot/proof/__init__.py`
- Create: `src/bot/proof/metrics.py` — `StrategyReport` dataclass + computation
- Create: `src/bot/proof/sources.py` — `TradeSource` Protocol + `JournalSource`, `BacktestLogSource`
- Create: `src/bot/proof/render.py` — equity-curve PNG + HTML page renderers
- Create: `src/bot/proof/generator.py` — `ProofGenerator.generate(source, bot_name, output_dir) -> ProofBundle`
- Create: `src/bot/proof/cli.py`
- Create: `src/bot/proof/__main__.py`
- Create: `src/bot/proof/templates/report.html.j2` — Jinja2 template (jinja2 likely already in deps; if not, add)
- Create: `tests/proof/test_metrics.py`
- Create: `tests/proof/test_sources.py`
- Create: `tests/proof/test_render.py`
- Create: `tests/proof/test_generator.py`
- Create: `tests/proof/test_cli.py`
- Create: `tests/proof/__init__.py`

---

## Tasks

### T1: `StrategyReport` metrics

`src/bot/proof/metrics.py`. Frozen dataclass `StrategyReport`:
- `bot_name: str`
- `period_start: datetime`
- `period_end: datetime`
- `net_profit: float`
- `max_drawdown: float` (worst peak-to-trough on equity curve)
- `total_trades: int`
- `pct_profitable: float` (0.0–1.0)
- `profit_factor: float` (sum-of-wins / sum-of-losses)
- `avg_trade_pnl: float`
- `avg_win: float`
- `avg_loss: float`
- `avg_holding_minutes: float`
- `sharpe_light: float` (mean(daily_returns) / stdev(daily_returns), no annualization)

Function `compute_report(trades: list[ClosedTrade], bot_name: str) -> StrategyReport`.

Define `ClosedTrade(entry_ts, exit_ts, side, entry_price, exit_price, qty, pnl)` — used as the universal intermediate format both source adapters produce.

Tests:
- Empty trade list → all metrics zero, profit_factor=0.
- Single winning trade → metrics match expected.
- Mixed wins/losses → pct_profitable + profit_factor correct.
- Max drawdown: equity curve [100, 110, 105, 95, 100] → max DD = 15 (110→95).
- All-losing → profit_factor = 0 (avoid div-by-zero).

Commit: `feat(proof): StrategyReport dataclass + compute_report`.

### T2: Source adapters

`src/bot/proof/sources.py`. Protocol `TradeSource.iter_closed_trades() -> Iterable[ClosedTrade]`.

`JournalSource(journal_path: Path, bot_name: str | None)`: opens read-only SQLite, joins `orders` + `fills` to reconstruct closed trades. If bot_name given, filters to that bot's journal (post-Plan-12 layout); else reads all.

`BacktestLogSource(trade_log_path: Path)`: reads JSON TradeLog (from `bot.backtest.tracker.TradeLog`), converts each closed leg to ClosedTrade.

Tests:
- JournalSource against fixture .db with 5 fills → 2 round-trip trades.
- BacktestLogSource against fixture JSON → expected trade count.
- Empty journal → empty iterable.
- Bot-name filter excludes other bots' rows.

Commit: `feat(proof): JournalSource + BacktestLogSource adapters`.

### T3: Equity-curve PNG renderer

`src/bot/proof/render.py`. Function `render_equity_curve(trades, output_path) -> Path`. Uses matplotlib (Agg backend, no GUI). X-axis = exit timestamp, Y-axis = cumulative net P&L. Title = bot name. Save 1200×600 PNG.

Tests:
- 10-trade input produces a PNG file > 5KB.
- Empty input produces a PNG with "No trades yet" text (not a crash).
- Matplotlib in Agg mode (no $DISPLAY required) — set rcParams in module.

Commit: `feat(proof): equity-curve PNG renderer (matplotlib Agg)`.

### T4: HTML template + renderer

`src/bot/proof/templates/report.html.j2` — Jinja2 template. Top: title + period. Middle: metric table (5 headline metrics in big text, 8 secondary metrics smaller). Bottom: embedded `<img src="equity_curve.png">`.

`render_html(report: StrategyReport, equity_curve_filename: str, output_path: Path) -> Path` — fills the template, writes to disk.

Tests:
- HTML output contains report.net_profit formatted with dollar sign + commas.
- HTML contains a `<table>` with all 13 metric labels.
- HTML references `equity_curve.png` (relative path).

Commit: `feat(proof): Jinja2 HTML template + render_html`.

### T5: `ProofGenerator` end-to-end

`src/bot/proof/generator.py`. Class `ProofGenerator`:
- `generate(source: TradeSource, bot_name: str, output_dir: Path) -> ProofBundle`.
- Returns frozen dataclass `ProofBundle(report_json_path, equity_curve_png_path, html_path, report: StrategyReport)`.
- Steps: iter trades from source → compute report → write report.json → render PNG → render HTML.
- Creates output_dir if missing.

Tests:
- End-to-end with BacktestLogSource fixture: bundle returned, all 3 files exist on disk, report.net_profit matches expected.
- Output dir nested (`state/proof/foo/bar/`): created recursively.

Commit: `feat(proof): ProofGenerator end-to-end (source → report + PNG + HTML)`.

### T6: CLI

`src/bot/proof/cli.py` + `__main__.py`. Argparse:
- `--journal <path>` OR `--backtest <log-path>` (mutually exclusive, one required).
- `--bot <name>` (required for journal; ignored for backtest).
- `--output <dir>` (default: `state/proof/<bot_name>_<YYYYMMDD-HHMMSS>/`).

Tests:
- `python -m bot.proof --backtest <fixture.json> --bot test_bot --output <tmpdir>` exits 0, prints bundle paths.
- `python -m bot.proof` (no source) exits non-zero with usage.
- `--journal` and `--backtest` both given → exits non-zero.

Commit: `feat(proof): CLI runner`.

### T7: Docs + tag

Add new spec file `docs/superpowers/specs/2026-05-22-futures-bot/08-proof-surface.md` describing the proof bundle structure, the 13 metrics, and the VSL labels they mirror. Update `INDEX.md`.

Then:
```
git tag plan-13-proof-surface-complete
git push origin main --tags
```

Commit: `docs(spec): proof-surface spec 08 + INDEX update`.

---

## Verification

```bash
cd ~/futures-bot1
source ~/.venvs/topstep-bot/bin/activate
ruff check . && mypy --strict src/ && pytest -x -q
# E2E from an existing backtest fixture (Plan 4 produced one):
python -m bot.proof --backtest tests/backtest/fixtures/sample_trade_log.json --bot demo --output /tmp/proof_test/
ls /tmp/proof_test/  # expect: report.json, equity_curve.png, report.html
open /tmp/proof_test/report.html  # visual check
```

Expected:
- CI green: ~587 tests.
- The opened HTML shows the 5 headline metrics in big text, the 8 secondary metrics below, and the equity curve PNG.
- Visual sanity: looks like a TradingView Strategy Report. Not identical, but the same information density.
- Tag `plan-13-proof-surface-complete` pushed.

End state: every bot in the fleet can produce its own proof bundle — the missing product surface the VSL sells with.
