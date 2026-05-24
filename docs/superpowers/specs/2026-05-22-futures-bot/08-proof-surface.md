# 08 — Proof Surface

The proof surface is the product face of the bot: a per-bot bundle that
turns the journal (live) or a backtest TradeLog (offline) into a 3-file
artifact mirroring the TradingView Strategy Report shape visible in the VSL
at ~18:00, 19:00, 20:00. Every bot in the fleet can generate one on demand;
Plan 21 will surface them via a live web dashboard.

## Bundle layout

`state/proof/<bot_name>_<YYYYMMDD-HHMMSS>/`

| File | Purpose |
|---|---|
| `report.json` | StrategyReport fields as JSON. Machine-readable. |
| `equity_curve.png` | 1200x600 cumulative-PnL curve (matplotlib Agg). |
| `report.html` | Headline + secondary metric tables, embeds the PNG. |

## StrategyReport (13 fields)

The 5 headline metric labels match TradingView's Strategy Report verbatim
(the labels visible in the VSL):

| Label | Field | Definition |
|---|---|---|
| Net Profit | `net_profit` | sum of per-trade PnL, dollars |
| Max Drawdown | `max_drawdown` | worst peak-to-trough on the cumulative-PnL equity curve |
| Total Trades | `total_trades` | number of closed round-trips |
| % Profitable | `pct_profitable` | wins / total, in 0.0-1.0 |
| Profit Factor | `profit_factor` | sum(wins) / abs(sum(losses)); 0.0 if no winners or no losers (no div-by-zero) |

Secondary metrics (smaller in the HTML):

| Field | Definition |
|---|---|
| `avg_trade_pnl` | mean per-trade PnL |
| `avg_win` | mean PnL across winning trades |
| `avg_loss` | mean magnitude across losing trades (positive number) |
| `avg_holding_minutes` | mean (exit_ts - entry_ts) in minutes |
| `sharpe_light` | mean(per-trade-PnL) / pstdev(per-trade-PnL); 0 if <2 trades or zero stdev (no annualization) |
| `period_start` | entry_ts of first closed trade |
| `period_end` | exit_ts of last closed trade |
| `bot_name` | identifier passed in from the CLI / caller |

## Source adapters

`bot.proof.sources.TradeSource` Protocol: `iter_closed_trades() -> Iterable[ClosedTrade]`.

- `JournalSource(journal_path, bot_name)`: read-only SQLite join of
  `fills.client_order_id -> orders.client_order_id` to recover side + symbol,
  then walks per-symbol cash flow (mirror of `bot.backtest.report._round_trip_pnls`)
  and emits a `ClosedTrade` on each return-to-flat. The `bot_name` arg is
  currently a no-op (the schema has no `bot_name` column yet; Plan 12 will add
  it). A `sqlite3.OperationalError` on the filtered query falls back to
  unfiltered scan, so this adapter transparently upgrades when Plan 12 lands.
- `BacktestLogSource(trade_log_path)`: reads a JSON file shaped as
  `{"approved_orders": [{"intent": {...}, "event": {...}}, ...]}` (mirrors
  `TradeLog.approved_orders`), runs the same per-symbol walker.

## CLI

```
python -m bot.proof --journal state/journal_xxx.db --bot example_orb_nq
python -m bot.proof --backtest tests/proof/sample_trade_log.json --bot demo
```

- `--journal` xor `--backtest` (mutually exclusive, one required).
- `--bot <name>` required.
- `--output <dir>` defaults to `state/proof/<bot_name>_<YYYYMMDD-HHMMSS>/`.

## Implementation notes

- matplotlib forces Agg backend at module import (`render.py`). Required for
  headless CI + LaunchAgent execution.
- jinja2 template lives at `src/bot/proof/templates/report.html.j2` and is
  shipped via `[tool.setuptools.package-data]`.
- `ClosedTrade.pnl` is computed in dollars by the adapter (point-value math
  stays in the adapter layer); `metrics.py` is free of broker-specific
  constants.

## Owned by

- `bot.proof` (additive — does NOT replace `bot.backtest.report.TradeReport`,
  which is the legacy backtest summary the CLI prints).
