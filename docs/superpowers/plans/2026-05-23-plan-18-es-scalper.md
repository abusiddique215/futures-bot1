# Plan 18 — ES Scalper (ES, 10m Daily Exit) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Second non-NQ user-facing bot. ES Scalper trades ES1!/S&P 500 E-mini Futures (CME) on a 10-minute timeframe with a "Daily Exit" pattern (per "RP - ES Scalper (10m) [Daily Exit]" visible at ~20:00 in the VSL). Maintenance-family risk profile (EFA Standard). After this plan: 4 of 6 user-facing bots deployable. Reuses Plan 14's MarketSpec for ES/MES and Plan 17's mean-reversion strategy (similar instrument class — ES and GC both benefit from mean-reversion in chop).

**Architecture:** ES Scalper is a `BotSpec` (Plan 12) wiring `MeanReversionStrategy` (from Plan 17) with ES-tuned parameters + `MarketHours` schedule (simpler than Gold Bot — just US regular session) + `EFAStandardEoDDrawdown` + MarketSpec for ES/MES (Plan 14). The "Scalper" framing means tighter targets and faster exits than the other maintenance bots.

**Tech Stack:** No new deps. Reuses Plan 12, Plan 13, Plan 14, Plan 17's `MeanReversionStrategy`.

**VSL fidelity (observable constraints honored):**
- **Market**: ES1! (CME S&P 500 E-mini) — verified at ~20:00 ("ES1! · S&P 500 E-mini Futures · 10 · CME")
- **Timeframe**: 10-minute — verified by "10" in chart header + "(10m)" in bot label
- **Daily Exit**: flat by EoD
- **Scalper framing**: faster turnaround than the other maintenance bots — tighter TP, more trades per day

**Performance claim from VSL strategy report (~20:00):** +$68,300 net profit, $24,400 max drawdown, 3,029 trades, 73.65% profitable, 1.097 profit factor. The 3,029 trades over the report period strongly imply high-frequency scalping (~10+ trades/day). Our `max_trades_per_day` cap should reflect that (e.g., 10-15/day), but verified backtest results may inform a different cap.

**Internal strategy logic disclaimer:** ES Scalper's actual rules are hidden. We use the same MeanReversionStrategy as Gold Bot (BB + RSI) but with tighter parameters: shorter BB period, tighter RSI thresholds, smaller reward ratio. Document the design.

**Deliverable:**
- `src/bot/strategy/profiles/es_scalper.py` — ES-tuned MeanReversion params.
- `config/bots/es_scalper.yml` — full BotSpec.
- Backtest run against ES FirstRateData → proof bundle. Compare net profit / trade count to VSL claim (sanity check only — not a pass/fail).
- CI green (~662 + ~10 new tests).
- Tag `plan-18-es-scalper-complete`.

---

## File structure

- Create: `src/bot/strategy/profiles/es_scalper.py`
- Create: `config/bots/es_scalper.yml`
- Create: `tests/integration/test_es_scalper_e2e.py`

(No new strategy class — reuses Plan 17's MeanReversionStrategy with different parameters.)

---

## Tasks

### T1: ES Scalper strategy profile

`src/bot/strategy/profiles/es_scalper.py`:
```python
ES_SCALPER_DEFAULTS = {
    "bb_period": 10,        # shorter than Gold's 20 — faster signals
    "bb_stddev": 1.5,       # tighter than 2.0 — more entries
    "rsi_period": 9,        # shorter — more sensitive
    "rsi_oversold": 35.0,   # tighter thresholds
    "rsi_overbought": 65.0,
    "reward_ratio": 0.75,   # smaller TP — scalper ethos
    "max_trades_per_day": 10,
    "symbol": "MES",
}
```

Tests:
- Profile loads + matches MeanReversionStrategy schema.
- Loading via "mean_reversion_bb" registry id + these params produces a valid strategy.

Commit: `feat(strategy): ES Scalper profile (tighter BB+RSI, smaller TP)`.

### T2: BotSpec YAML

`config/bots/es_scalper.yml`:
```yaml
name: es_scalper
enabled: true
symbol: MESH26   # Micro ES for $50K Combine sizing
strategy_id: mean_reversion_bb
strategy_params:
  bb_period: 10
  bb_stddev: 1.5
  rsi_period: 9
  rsi_oversold: 35.0
  rsi_overbought: 65.0
  reward_ratio: 0.75
  max_trades_per_day: 10
risk_policy: efa_standard
risk_params:
  mll_amount: 2000
schedule_type: market_hours
schedule_params:
  open_ct: "08:30"
  close_ct: "14:45"   # 25 min before hard-flat — scalper needs cleanup time
journal_path: state/journal_es_scalper.db
```

Tests:
- YAML loads + builds.
- Schedule honors 08:30-14:45 CT.

Commit: `feat(config): es_scalper.yml`.

### T3: End-to-end integration test

`tests/integration/test_es_scalper_e2e.py`. Drives synthetic ES bars (1 day) → FleetRuntime → SimClient → Journal. Asserts:
- Multiple entries per day (vs SurgeBot's 2-cap).
- All flat by 14:45 CT.
- Journal records ES/MES symbol.

Optional: comparison vs VSL strategy report claim. If a real ES FirstRateData backtest fixture exists, run backtest over 1 year and print: actual trade count vs claimed 3,029, actual win rate vs claimed 73.65%, actual net profit vs claimed $68,300. Don't fail the test on mismatch — just print for sanity-check.

Commit: `test(integration): ES Scalper end-to-end + VSL comparison print`.

### T4: Docs + tag

Append ES Scalper section to `09-bot-lineup.md`. Document the parameter tightening rationale + the VSL claim comparison protocol.

Then:
```
git tag plan-18-es-scalper-complete
git push origin plan-18-wt --tags  # (or main)
```

Commit: `docs(spec): ES Scalper lineup entry`.

---

## Verification

```bash
cd ~/futures-bot1
source ~/.venvs/topstep-bot/bin/activate
ruff check . && mypy --strict src/ && pytest -x -q
python -m bot.backtest --bot es_scalper --start 2024-01-01 --end 2024-12-31 --data-fixture tests/data/fixtures/es_1min_2024.csv
```

End state: 4 of 6 bots deployable. Plan 19 (Lux Bot) adds Discord signal ingestion — first bot with an external signal source.
