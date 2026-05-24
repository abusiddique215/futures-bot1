# Plan 14 — Multi-Market Plumbing (GC + ES) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Extend the data pipeline + execution + risk constants to cover GC1!/Gold Futures (COMEX) and ES1!/S&P 500 E-mini Futures (CME) in addition to the current NQ/MNQ coverage. After this plan: Gold Bot (Plan 17) and ES Scalper (Plan 18) can each hold their own continuous-roll series, contract calendar, FirstRateData ingest, IB live data subscription, and tick-value/position-cap math without per-bot symbol logic.

**Architecture:** The existing single-symbol assumptions in `bot.constants`, `bot.data.contract_calendar`, `bot.data.continuous`, `bot.data.firstratedata`, and `bot.data.live_ib` are keyed off `if symbol.startswith("MNQ" or "NQ")` patterns. Replace with a `MarketSpec` registry (one entry per market) that owns tick value, min tick, contract-month codes, roll calendar, IB contract spec, and position-cap rules. All symbol-specific branching becomes a lookup against the registry.

**Tech Stack:** No new deps. Reuses `bot.data` modules. The IB contract specs come from `ib_async` types (already in use for NQ).

**Scope notes:**
- Markets in scope this plan: NQ, MNQ (continue working), GC (Gold, COMEX), MGC (Micro Gold), ES, MES (Micro S&P 500). Crypto, stocks, options stay out of scope.
- `MarketSpec` is a frozen dataclass — never mutated at runtime. Registry exposes lookups; tests verify all 6 markets are registered.
- Continuous-roll math (ratio-adjusted, third Friday of H/M/U/Z) is the same for all index/metal futures. Implementation generalizes the existing NQ-specific code.
- FirstRateData files have a consistent naming convention (`NQ_1min_2010-2025.txt`, `GC_1min_*.txt`, `ES_1min_*.txt`). The ingest CLI takes `--market GC` and infers paths.
- Risk policies (combine_intraday, efa_standard, efa_consistency) already encode max-position math per symbol; they need `MarketSpec.max_position_mini_to_micro_ratio` extended.

**Deliverable:**
- `MarketSpec` registry with 6 entries.
- All symbol-startswith branches in `bot.risk.*` + `bot.data.*` + `bot.constants` replaced with registry lookups.
- `python -m bot.data.ingest --market GC --start 2020-01-01 --end 2025-12-31` ingests Gold FirstRateData (against fixture file in CI).
- IB live data subscription helper supports GC + ES contract specs.
- CI green (~587 + ~25 new tests).
- Tag `plan-14-multi-market-complete`.

---

## File structure

- Create: `src/bot/markets/__init__.py`
- Create: `src/bot/markets/spec.py` — `MarketSpec` dataclass
- Create: `src/bot/markets/registry.py` — `MARKETS: dict[str, MarketSpec]` + lookup helpers
- Modify: `src/bot/constants.py` — TICK_VALUES, MIN_TICK become thin wrappers over registry
- Modify: `src/bot/risk/combine_drawdown.py:max_position` — registry lookup instead of startswith
- Modify: `src/bot/risk/efa_drawdown.py:max_position` — registry lookup
- Modify: `src/bot/data/contract_calendar.py` — generalize NQ-specific code
- Modify: `src/bot/data/continuous.py` — accept market arg
- Modify: `src/bot/data/firstratedata.py` — accept market arg in path resolver
- Modify: `src/bot/data/live_ib.py` — accept market arg for IB contract construction
- Modify: `src/bot/data/ingest.py` — add `--market` CLI arg
- Create: `tests/markets/test_spec.py`
- Create: `tests/markets/test_registry.py`
- Create: `tests/markets/__init__.py`
- Modify: existing tests that hardcoded NQ — extend with parametrize for GC, ES

---

## Tasks

### T1: `MarketSpec` dataclass

`src/bot/markets/spec.py`. Frozen dataclass with fields:
- `root: str` (e.g., "NQ", "GC", "ES")
- `name: str` (human-readable)
- `exchange: str` ("CME", "COMEX")
- `tick_size: float` (NQ=0.25, GC=0.10, ES=0.25)
- `tick_value: float` (NQ=$5, GC=$10, ES=$12.50 — verify before implementing)
- `multiplier: float` ($/point)
- `micro_root: str | None` (NQ→MNQ, GC→MGC, ES→MES; or None if no micro)
- `micro_to_full_ratio: int` (10 for NQ/MNQ; 10 for GC/MGC; 10 for ES/MES)
- `contract_months: tuple[str, ...]` (H/M/U/Z = quarterly for NQ/ES; G/J/M/Q/V/Z = monthly even for GC — VERIFY)
- `roll_day_rule: str` ("third_friday_prev_month" for NQ/ES; "first_notice_day" for GC — VERIFY)
- `ib_sec_type: str` ("FUT")
- `ib_currency: str` ("USD")

Tests:
- Frozen — mutation raises.
- All fields populated for an example instance.

Commit: `feat(markets): MarketSpec dataclass`.

### T2: Registry with 6 markets

`src/bot/markets/registry.py`. Module-level `MARKETS: Final[dict[str, MarketSpec]]` with entries for NQ, MNQ, GC, MGC, ES, MES.

**Before populating: web-search to verify tick values + contract months + roll rules.** Sources: CME group product pages (cmegroup.com/markets/equities/sp/e-mini-sp-500.contractSpecs.html and equivalents). Document each value's source in a code comment.

Helpers:
- `get_market(symbol: str) -> MarketSpec` — extracts root from "MNQH26" → "MNQ" → lookup.
- `is_micro(symbol: str) -> bool`
- `full_root_for(symbol: str) -> str` (e.g., "MGC" → "GC")
- `all_markets() -> list[MarketSpec]`

Tests:
- All 6 markets registered.
- `get_market("MNQH26")` returns MNQ spec.
- `get_market("ESM26")` returns ES spec.
- `get_market("UNKNOWN")` raises KeyError.
- Tick values match documented sources (NQ=$5/point=$1.25/tick; GC=$10/point=$1.00/tick; ES=$12.50/point=$3.125/tick — VERIFY).

Commit: `feat(markets): 6-market registry (NQ/MNQ/GC/MGC/ES/MES) + lookup helpers`.

### T3: Migrate `bot.constants` + risk policies

`src/bot/constants.py`: replace TICK_VALUES dict with `def tick_value(symbol): return get_market(symbol).tick_value`. Same for MIN_TICK. Keep COMBINE_50K_* unchanged.

`bot.risk.combine_drawdown.max_position`: replace startswith chain with `market = get_market(symbol); ratio = market.micro_to_full_ratio if is_micro(symbol) else 1; return self._max_mini * ratio`.

Same change to `efa_drawdown.max_position` (both classes).

Tests:
- All existing combine_drawdown + efa_drawdown tests still pass (use NQ/MNQ).
- New tests parametrize with GC/MGC and ES/MES — max_position returns correct caps.
- Unknown symbol → KeyError propagates (no silent default).

Commit: `refactor(risk,constants): market lookup replaces symbol startswith chains`.

### T4: Migrate `bot.data.contract_calendar` + `continuous`

`bot.data.contract_calendar`: generalize the third-Friday-of-prev-month logic to read from `MarketSpec.roll_day_rule`. Add branch for `first_notice_day` (Gold uses this — VERIFY).

`bot.data.continuous`: accept `market: MarketSpec` argument; use market.contract_months + market.roll_day_rule.

Tests:
- Existing NQ continuous-roll tests still pass.
- New tests for ES (same H/M/U/Z) and GC (G/J/M/Q/V/Z or whatever the verified list is).
- Roll day computation: NQ March 2026 contract rolls on third Friday of Feb 2026 (= 2026-02-20).

Commit: `feat(data): contract calendar + continuous-roll honor MarketSpec`.

### T5: Migrate `bot.data.firstratedata` + `live_ib` + ingest CLI

`bot.data.firstratedata`: accept `market: MarketSpec` arg; path resolver becomes `f"{market.root}_1min_*.txt"`.

`bot.data.live_ib`: contract construction accepts MarketSpec; replaces `Future("NQ", ...)` with `Future(market.root, ..., exchange=market.exchange, currency=market.ib_currency)`.

`bot.data.ingest` CLI: add `--market <root>` arg, default "NQ" for back-compat. Lookup market spec, pass through.

Tests:
- Existing NQ ingest tests pass unchanged.
- New tests for GC, ES path resolution (against fixture files).
- IB contract spec test: `live_ib.build_contract("ES")` returns `Future("ES", exchange="CME", currency="USD", ...)`.

Commit: `feat(data): FirstRateData + IB live data + ingest CLI honor MarketSpec`.

### T6: Documentation + tag

Update `docs/superpowers/specs/2026-05-22-futures-bot/01-data-pipeline.md` to document the MarketSpec registry as the single source of truth for per-market parameters. Update D2 in `00-architecture-overview.md` to note multi-market support.

Add `docs/superpowers/research/2026-05-23-cme-comex-contract-specs.md` capturing the web-search results from T2 (tick values, contract months, roll rules) with citation URLs.

Then:
```
git tag plan-14-multi-market-complete
git push origin main --tags
```

Commit: `docs(spec,research): MarketSpec registry + CME/COMEX contract spec citations`.

---

## Verification

```bash
cd ~/futures-bot1
source ~/.venvs/topstep-bot/bin/activate
ruff check . && mypy --strict src/ && pytest -x -q
python -c "from bot.markets.registry import all_markets; [print(m.root, m.tick_value) for m in all_markets()]"
```

Expected output:
```
NQ 5.0
MNQ 0.5
GC 10.0
MGC 1.0
ES 12.5
MES 1.25
```

(VERIFY tick values via web-search in T2 — these are likely-but-not-confirmed defaults.)

CI green: ~612 tests. Tag `plan-14-multi-market-complete` pushed.

End state: Plans 17 (Gold Bot) and 18 (ES Scalper) can use `get_market(...)` and inherit all per-market logic without writing per-symbol branches.
