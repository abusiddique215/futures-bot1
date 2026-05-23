# Plan 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the `bot` Python package with canonical types, constants, Protocols, and a typed Pydantic v2 config loader so subsequent plans (data pipeline, risk engine, execution clients, etc.) have a stable, fully type-checked foundation to extend.

**Architecture:** Single Python package under `src/bot/` with explicit subpackages (`execution/`, `risk/`). All cross-cutting dataclasses live in `bot/types.py` to keep type imports in one place and avoid Protocol↔Protocol circular imports between subpackages. The two Protocols other plans will extend (`ExecutionClient`, `DrawdownPolicy`) ship as shells now. Config uses Pydantic v2 with cross-field validators so invalid env/broker combinations fail at load time, not at runtime. TDD throughout — failing test before every implementation.

**Tech Stack:** Python 3.12, Pydantic v2 + pydantic-settings, pytest + pytest-asyncio + hypothesis + freezegun, ruff, mypy, PyYAML, python-dotenv.

**Scope notes:**
- This plan ships **no business logic**. No risk gate, no broker adapters, no strategies, no data pipeline. Only types + Protocol shells + config.
- Other plans will import from this plan; this plan imports from nothing project-internal.
- iCloud Drive working-tree caveat: this plan is safe to run from iCloud. Plan 9 (deploy) requires moving the tree to local disk before live install — that constraint does NOT apply here.

**Deliverable verification (success criteria):**
- `pytest -q` passes with at least the count of tests created in this plan.
- `mypy src/ tests/` clean.
- `ruff check src/ tests/` clean.
- `python -c "from bot.config import load_config; from pathlib import Path; print(load_config(Path('config/bot.example.yml')))"` prints a `BotConfig` object.
- `python -c "import bot, bot.types, bot.constants, bot.execution.ports, bot.risk.policies"` succeeds with no errors.

---

## File Structure

Files created by this plan:

```
.
├── .gitignore
├── .env.example
├── README.md                                       # one paragraph, what-this-is
├── pyproject.toml                                  # deps + ruff/mypy/pytest config
├── config/
│   └── bot.example.yml                             # sample BotConfig YAML
├── src/
│   └── bot/
│       ├── __init__.py                             # package marker, __version__
│       ├── types.py                                # ALL cross-cutting dataclasses
│       ├── constants.py                            # TICK_VALUES, Topstep $50K constants
│       ├── config.py                               # Pydantic BotConfig + load_config()
│       ├── execution/
│       │   ├── __init__.py
│       │   └── ports.py                            # ExecutionClient Protocol shell
│       └── risk/
│           ├── __init__.py
│           └── policies.py                         # DrawdownPolicy Protocol shell
└── tests/
    ├── __init__.py
    ├── conftest.py                                 # shared fixtures (UTC factory)
    ├── test_smoke.py
    ├── test_types_bar_tick.py
    ├── test_types_order_intent.py
    ├── test_types_position_order_event.py
    ├── test_types_account_state.py
    ├── test_types_risk_results.py
    ├── test_constants.py
    ├── test_execution_ports.py
    ├── test_risk_policies.py
    └── test_config.py
```

**Why one big `bot/types.py` instead of split-by-domain modules:**
- The risk engine's `OrderDenied` references `OrderIntent`; execution's `ExecutionClient.get_account()` returns `AccountState` (owned by risk). Splitting types by domain creates a circular import (risk ↔ execution).
- One shared `types.py` is the minimum-friction resolution. Split later if it grows past ~500 lines.
- Per project CLAUDE.md §2 (Simplicity First): no premature abstraction.

---

## Tasks

### Task 1: Project skeleton (git, .gitignore, .env.example, README)

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`
- Create: `src/bot/__init__.py`
- Create: `src/bot/execution/__init__.py`
- Create: `src/bot/risk/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Initialize git if needed**

```bash
cd "/Users/abusiddique/Library/Mobile Documents/com~apple~CloudDocs/projects/algo trade training"
git init -b main 2>/dev/null || true
git status
```

Expected: either fresh repo on `main` or existing repo status. If repo already exists, do NOT reinitialize — proceed.

- [ ] **Step 2: Write `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.eggs/
build/
dist/
.venv/
venv/
env/

# Tooling caches
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
.hypothesis/

# Editors
.vscode/
.idea/
*.swp
.DS_Store

# Project-local
.env
.env.local
state/
logs/
data/raw/
data/parquet/
data/quarantine/
secrets/*.age
!secrets/.gitkeep
```

- [ ] **Step 3: Write `.env.example`**

```bash
# Interactive Brokers paper (used when broker=ib_paper)
IB_USERNAME=
IB_PASSWORD=
IB_GATEWAY_HOST=127.0.0.1
IB_GATEWAY_PORT=4002

# TopstepX live (used when broker=topstepx)
TOPSTEPX_USERNAME=
TOPSTEPX_API_KEY=

# Telegram alerts (always required)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

- [ ] **Step 4: Write `README.md`**

```markdown
# Topstep Futures Trading Bot

Python automated futures trading bot for the Topstep prop firm, targeting NQ/MNQ on a $50K Combine. Two operating modes (Surge / Maintenance) driven by YAML profiles of a single 5-minute Opening Range Breakout strategy. Runs on NautilusTrader for backtest/paper/live parity.

See `docs/superpowers/specs/2026-05-22-futures-bot/` for the architecture spec and `docs/superpowers/plans/` for implementation plans.
```

- [ ] **Step 5: Create empty package markers**

Write the following empty files (just `""` content):

- `src/bot/__init__.py` — content: `__version__ = "0.0.1"\n`
- `src/bot/execution/__init__.py` — content: `""\n`
- `src/bot/risk/__init__.py` — content: `""\n`
- `tests/__init__.py` — content: `""\n`

- [ ] **Step 6: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


@pytest.fixture
def utc_now() -> datetime:
    """A fixed, timezone-aware UTC timestamp for tests that need one."""
    return datetime(2026, 5, 22, 14, 30, 0, tzinfo=timezone.utc)
```

- [ ] **Step 7: Commit**

```bash
git add .gitignore .env.example README.md src/bot/__init__.py \
        src/bot/execution/__init__.py src/bot/risk/__init__.py \
        tests/__init__.py tests/conftest.py
git commit -m "chore: project skeleton for futures bot"
```

---

### Task 2: `pyproject.toml` with deps and tooling config

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "bot"
version = "0.0.1"
description = "Topstep futures trading bot — NQ/MNQ, NautilusTrader runtime"
readme = "README.md"
requires-python = ">=3.12,<3.14"  # 3.12 + 3.13 both supported; nautilus-trader 1.227 covers both per pre-Plan-1 verification
dependencies = [
    # Plan 1 imports only these two. Heavier deps (nautilus-trader, ib-async,
    # project-x-py, pyarrow, aiosqlite, python-telegram-bot, loguru,
    # pydantic-settings, python-dotenv) are added by the plan that first
    # imports them, to keep Plan 1's install fast and to avoid the Rust
    # toolchain build cost + the project-x-py PyPI-name uncertainty until
    # Plan 8 actually needs it.
    "pydantic>=2.7",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "hypothesis>=6.100",
    "freezegun>=1.5",
    "ruff>=0.5",
    "mypy>=1.10",
    "types-PyYAML",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
addopts = "-ra --strict-markers --strict-config"
asyncio_mode = "auto"
filterwarnings = [
    "error",
    "ignore::DeprecationWarning:nautilus_trader.*",
]

[tool.mypy]
python_version = "3.12"
strict = true
warn_unreachable = true
disallow_untyped_decorators = false
plugins = ["pydantic.mypy"]
# iCloud Drive's sync layer corrupts sqlite-backed mypy caches → sqlite3.OperationalError.
# Park the cache on local disk so iCloud never sees it.
cache_dir = "/tmp/mypy-topstep-bot"

[[tool.mypy.overrides]]
module = ["nautilus_trader.*", "ib_async.*", "project_x.*"]
ignore_missing_imports = true

# Tests are explicit code; we don't enforce strict typing inside them so that
# pytest fixture parameters can be written `(utc_now)` instead of
# `(utc_now: datetime)` for every test. src/ stays strict.
[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false
disallow_incomplete_defs = false
check_untyped_defs = true

[tool.ruff]
target-version = "py312"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "B",   # flake8-bugbear
    "UP",  # pyupgrade
    "C4",  # flake8-comprehensions
    "PT",  # pytest style
    "RUF", # ruff-specific
]
ignore = [
    "E501",  # line length (covered by formatter)
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["B018"]
```

- [ ] **Step 2: Install dev deps in a venv OUTSIDE iCloud**

The working tree is on iCloud Drive (`~/Library/Mobile Documents/...`). iCloud sync corrupts Python venvs (broken symlinks, evicted `.pyc` files under memory pressure, sync collisions on `pip install`). Put the venv on local disk instead:

```bash
cd "/Users/abusiddique/Library/Mobile Documents/com~apple~CloudDocs/projects/algo trade training"
mkdir -p ~/.venvs

# Pick the first available interpreter in the [3.12, 3.13] range. Both are
# supported by every dep we'll need across all 9 plans (verified pre-Plan-1).
if command -v python3.12 >/dev/null; then
    PYBIN=python3.12
elif command -v python3.13 >/dev/null; then
    PYBIN=python3.13
else
    echo "Need Python 3.12 or 3.13. Install via: brew install python@3.13" >&2
    exit 1
fi
$PYBIN -m venv ~/.venvs/topstep-bot
source ~/.venvs/topstep-bot/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

Expected: install completes in well under a minute (Plan 1 only needs `pydantic`, `pyyaml`, plus the dev tooling — no Rust toolchain, no heavy ML/data libs). If `pydantic>=2.7` is unavailable for some reason, do NOT downgrade silently — surface the version mismatch as a parked dependency and stop.

**Activation note for subsequent steps and future shells**: every shell that wants to run `pytest`, `mypy`, etc. needs to run `source ~/.venvs/topstep-bot/bin/activate` first. Consider adding an alias to your shell rc (`alias topstep-bot='source ~/.venvs/topstep-bot/bin/activate && cd "/Users/abusiddique/Library/Mobile Documents/com~apple~CloudDocs/projects/algo trade training"'`) — optional, but you'll switch in and out of this venv a lot across Plans 2-9.

- [ ] **Step 3: Verify tooling runs**

```bash
ruff check src/ tests/
mypy src/ tests/
pytest -q
```

Expected: ruff clean, mypy clean (no source files to check yet), pytest reports `no tests ran` or `0 passed`. If pytest fails with `ERROR: file or directory not found: tests/`, that's expected — the test dir exists but has no test_*.py files yet.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: pyproject.toml with pinned deps + ruff/mypy/pytest config"
```

---

### Task 3: Smoke test (verify infrastructure works)

**Files:**
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write the smoke test**

```python
# tests/test_smoke.py
"""One-line sanity test that pytest discovery + asyncio mode + a fixture all work."""
from __future__ import annotations

import asyncio

import pytest


def test_python_version_is_312() -> None:
    import sys
    assert sys.version_info >= (3, 12), "Plan 1 requires Python 3.12+"


def test_bot_package_importable() -> None:
    import bot
    assert bot.__version__ == "0.0.1"


@pytest.mark.asyncio
async def test_asyncio_mode_works() -> None:
    await asyncio.sleep(0)
    assert True


def test_conftest_fixture_is_tz_aware(utc_now) -> None:
    assert utc_now.tzinfo is not None
```

- [ ] **Step 2: Run and verify all four tests pass**

```bash
pytest tests/test_smoke.py -v
```

Expected:
```
tests/test_smoke.py::test_python_version_is_312 PASSED
tests/test_smoke.py::test_bot_package_importable PASSED
tests/test_smoke.py::test_asyncio_mode_works PASSED
tests/test_smoke.py::test_conftest_fixture_is_tz_aware PASSED
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test: smoke test for pytest + asyncio + conftest"
```

---

### Task 4: `Bar` and `Tick` types with timezone-aware validation

**Files:**
- Create: `src/bot/types.py`
- Create: `tests/test_types_bar_tick.py`

Source: spec `01-data-pipeline.md §3.5` and §4 implementation sketch. Naive timestamps must raise `TypeError` at construction.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_types_bar_tick.py
"""Tests for the Bar and Tick dataclasses.

Spec: 01-data-pipeline.md §3.5 timezone-awareness invariant.
"""
from __future__ import annotations

from datetime import datetime

import pytest


def test_bar_rejects_naive_timestamp() -> None:
    from bot.types import Bar
    with pytest.raises(TypeError, match="timezone-aware"):
        Bar(
            symbol="MNQ",
            open=15000.0, high=15010.0, low=14990.0, close=15005.0,
            volume=100,
            timestamp=datetime(2026, 5, 22, 14, 30, 0),  # naive!
            interval="1m",
        )


def test_bar_accepts_utc_timestamp(utc_now) -> None:
    from bot.types import Bar
    b = Bar(symbol="MNQ", open=1.0, high=2.0, low=0.5, close=1.5,
            volume=10, timestamp=utc_now, interval="1m")
    assert b.symbol == "MNQ"
    assert b.timestamp.tzinfo is not None


def test_bar_is_frozen(utc_now) -> None:
    from bot.types import Bar
    from dataclasses import FrozenInstanceError
    b = Bar(symbol="MNQ", open=1.0, high=2.0, low=0.5, close=1.5,
            volume=10, timestamp=utc_now, interval="1m")
    with pytest.raises(FrozenInstanceError):
        b.symbol = "NQ"  # type: ignore[misc]


def test_tick_rejects_naive_timestamp() -> None:
    from bot.types import Tick
    with pytest.raises(TypeError, match="timezone-aware"):
        Tick(
            symbol="MNQ",
            price=15000.0, size=1,
            timestamp=datetime(2026, 5, 22, 14, 30, 0),
        )


def test_tick_accepts_non_utc_tz(utc_now) -> None:
    """Any tz-aware datetime is valid at construction; UTC conversion happens
    elsewhere (per spec 01 §3.5 storage is UTC, ingest converts ET→UTC)."""
    from bot.types import Tick
    from zoneinfo import ZoneInfo
    et_now = utc_now.astimezone(ZoneInfo("America/New_York"))
    t = Tick(symbol="MNQ", price=1.0, size=1, timestamp=et_now)
    assert t.timestamp.tzinfo is not None
```

- [ ] **Step 2: Run and verify the tests fail (ModuleNotFoundError)**

```bash
pytest tests/test_types_bar_tick.py -v
```

Expected: `ModuleNotFoundError: No module named 'bot.types'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# src/bot/types.py
"""Canonical cross-cutting dataclasses for the futures bot.

This module is intentionally a single file: the dataclasses below are referenced
by both bot.execution and bot.risk subpackages, and splitting them by domain
would create circular imports. Keep it under ~500 lines; split later if it grows.

Spec sources:
- 00-architecture-overview.md  : locked decisions, rule constants references
- 01-data-pipeline.md §3.5, §4 : Bar / Tick
- 02-execution-clients.md §4   : Bracket, OrderIntent (+ helpers), OrderEvent, Position
- 04-risk-engine.md §4.1       : AccountState, OrderDenied, ApprovedOrder
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


# ---- Data pipeline (spec 01) -------------------------------------------------

@dataclass(frozen=True)
class Bar:
    """Closed OHLCV bar. timestamp is the bar's OPEN time, tz-aware UTC.

    See spec 01 §3.4 (closed-bar semantics) and §3.5 (timezone discipline).
    """
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: datetime
    interval: str  # "1m", "5m"

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise TypeError("Bar.timestamp must be timezone-aware")


@dataclass(frozen=True)
class Tick:
    """Single trade or quote tick. timestamp must be tz-aware."""
    symbol: str
    price: float
    size: int
    timestamp: datetime

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise TypeError("Tick.timestamp must be timezone-aware")
```

- [ ] **Step 4: Run and verify tests pass**

```bash
pytest tests/test_types_bar_tick.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/bot/types.py tests/test_types_bar_tick.py
git commit -m "feat(types): Bar and Tick dataclasses with tz-aware validation"
```

---

### Task 5: `Bracket` and `OrderIntent` (bare dataclasses, no helper methods yet)

**Files:**
- Modify: `src/bot/types.py` (add Bracket + OrderIntent)
- Create: `tests/test_types_order_intent.py`

Source: spec `02-execution-clients.md §4`. The four helper methods are added in Task 6 — keep this task small.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_types_order_intent.py
"""Tests for OrderIntent and Bracket dataclasses (bare-field tests only here;
helper-method tests live in their own task to keep tasks bite-sized).

Spec: 02-execution-clients.md §4.
"""
from __future__ import annotations

import pytest


def test_bracket_is_frozen_with_two_int_fields() -> None:
    from bot.types import Bracket
    b = Bracket(stop_loss_ticks=20, take_profit_ticks=40)
    assert b.stop_loss_ticks == 20
    assert b.take_profit_ticks == 40


def test_order_intent_minimal_market_buy(utc_now) -> None:
    from bot.types import OrderIntent
    o = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="MARKET",
        client_order_id="t-1",
        timestamp=utc_now,
    )
    assert o.symbol == "MNQ"
    assert o.side == "BUY"
    assert o.quantity == 1
    assert o.order_type == "MARKET"
    assert o.limit_price is None
    assert o.stop_price is None
    assert o.bracket is None


def test_order_intent_with_bracket(utc_now) -> None:
    from bot.types import Bracket, OrderIntent
    o = OrderIntent(
        symbol="MNQ", side="SELL", quantity=2,
        order_type="BRACKET",
        client_order_id="t-2",
        timestamp=utc_now,
        bracket=Bracket(stop_loss_ticks=15, take_profit_ticks=30),
    )
    assert o.bracket is not None
    assert o.bracket.stop_loss_ticks == 15


def test_order_intent_is_frozen(utc_now) -> None:
    from bot.types import OrderIntent
    from dataclasses import FrozenInstanceError
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=1,
                    order_type="MARKET", client_order_id="t-3",
                    timestamp=utc_now)
    with pytest.raises(FrozenInstanceError):
        o.quantity = 99  # type: ignore[misc]
```

- [ ] **Step 2: Run and verify the tests fail**

```bash
pytest tests/test_types_order_intent.py -v
```

Expected: `ImportError: cannot import name 'Bracket'` or `'OrderIntent'`.

- [ ] **Step 3: Add Bracket and OrderIntent to `src/bot/types.py`**

Append to `src/bot/types.py` (after the Tick class):

```python


# ---- Execution (spec 02) -----------------------------------------------------

Side = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "BRACKET"]


@dataclass(frozen=True)
class Bracket:
    """Tick-offset stop and take-profit attached to a parent order.

    Tick offsets are broker-agnostic. The ExecutionClient adapter converts
    ticks to absolute prices (IB) or sends ticks directly (TopstepX).
    See spec 02 §3.5 bracket-translation table.
    """
    stop_loss_ticks: int
    take_profit_ticks: int


@dataclass(frozen=True)
class OrderIntent:
    """Broker-agnostic order request emitted by Strategy → RiskGate → ExecutionClient.

    The Strategy never holds a broker reference; the only path to a broker order
    is by emitting an OrderIntent. Helper methods (signed_qty, etc.) are added
    in the next task.
    """
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    client_order_id: str
    timestamp: datetime
    limit_price: float | None = None
    stop_price: float | None = None
    bracket: Bracket | None = None
```

And add the `Literal` import at the top of `src/bot/types.py`:

```python
from typing import Literal
```

- [ ] **Step 4: Run and verify tests pass**

```bash
pytest tests/test_types_order_intent.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/bot/types.py tests/test_types_order_intent.py
git commit -m "feat(types): Bracket and OrderIntent dataclasses"
```

---

### Task 6: `OrderIntent` helper methods (`signed_qty`, `is_open_increasing_exposure`, `is_market_or_limit_open`, `with_stop`)

**Files:**
- Modify: `src/bot/types.py` (add four methods to OrderIntent)
- Modify: `tests/test_types_order_intent.py` (add new tests at the bottom — do not rewrite the file)

Source: spec `02-execution-clients.md §4` lines 259-283. These methods are called by the risk gate (`04 §3.2 rule 1, 3.6 safety buffer`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_types_order_intent.py`:

```python


# ---- Helper methods (spec 02 §4 lines 259-283) -----------------------------

def test_signed_qty_buy_is_positive(utc_now) -> None:
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=3,
                    order_type="MARKET", client_order_id="t-1",
                    timestamp=utc_now)
    assert o.signed_qty() == 3


def test_signed_qty_sell_is_negative(utc_now) -> None:
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="SELL", quantity=3,
                    order_type="MARKET", client_order_id="t-2",
                    timestamp=utc_now)
    assert o.signed_qty() == -3


def test_is_open_increasing_exposure_flat_then_buy(utc_now) -> None:
    """Going from flat to +3 is increasing exposure."""
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=3,
                    order_type="MARKET", client_order_id="t-3",
                    timestamp=utc_now)
    assert o.is_open_increasing_exposure({}) is True
    assert o.is_open_increasing_exposure({"MNQ": 0}) is True


def test_is_open_increasing_exposure_long_then_buy_more(utc_now) -> None:
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=2,
                    order_type="MARKET", client_order_id="t-4",
                    timestamp=utc_now)
    assert o.is_open_increasing_exposure({"MNQ": 1}) is True


def test_is_open_increasing_exposure_long_then_sell_reducing(utc_now) -> None:
    """Reducing a long is NOT increasing exposure."""
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="SELL", quantity=1,
                    order_type="MARKET", client_order_id="t-5",
                    timestamp=utc_now)
    assert o.is_open_increasing_exposure({"MNQ": 3}) is False


def test_is_open_increasing_exposure_long_then_sell_flipping(utc_now) -> None:
    """Selling more than current long flips short — that IS increasing |pos|."""
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="SELL", quantity=5,
                    order_type="MARKET", client_order_id="t-6",
                    timestamp=utc_now)
    assert o.is_open_increasing_exposure({"MNQ": 1}) is True


def test_is_market_or_limit_open_market(utc_now) -> None:
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=1,
                    order_type="MARKET", client_order_id="t-7",
                    timestamp=utc_now)
    assert o.is_market_or_limit_open() is True


def test_is_market_or_limit_open_bracket(utc_now) -> None:
    from bot.types import Bracket, OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=1,
                    order_type="BRACKET", client_order_id="t-8",
                    timestamp=utc_now,
                    bracket=Bracket(stop_loss_ticks=10, take_profit_ticks=20))
    assert o.is_market_or_limit_open() is True


def test_is_market_or_limit_open_stop_returns_false(utc_now) -> None:
    """STOP / STOP_LIMIT are bracket children, not opens — see spec 02 §4 line 272-274."""
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="SELL", quantity=1,
                    order_type="STOP", client_order_id="t-9",
                    timestamp=utc_now, stop_price=14000.0)
    assert o.is_market_or_limit_open() is False


def test_with_stop_replaces_only_stop_loss_ticks(utc_now) -> None:
    from bot.types import Bracket, OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=1,
                    order_type="BRACKET", client_order_id="t-10",
                    timestamp=utc_now,
                    bracket=Bracket(stop_loss_ticks=20, take_profit_ticks=40))
    o2 = o.with_stop(15)
    assert o2.bracket is not None
    assert o2.bracket.stop_loss_ticks == 15
    assert o2.bracket.take_profit_ticks == 40           # unchanged
    assert o2.quantity == 1                              # unchanged
    assert o2.client_order_id == "t-10"                  # unchanged
    # Returns a new instance, doesn't mutate
    assert o.bracket is not None
    assert o.bracket.stop_loss_ticks == 20


def test_with_stop_raises_when_no_bracket(utc_now) -> None:
    from bot.types import OrderIntent
    o = OrderIntent(symbol="MNQ", side="BUY", quantity=1,
                    order_type="MARKET", client_order_id="t-11",
                    timestamp=utc_now)
    with pytest.raises(ValueError, match="without a bracket"):
        o.with_stop(15)
```

- [ ] **Step 2: Run and verify the tests fail**

```bash
pytest tests/test_types_order_intent.py -v -k "signed_qty or is_open_increasing or is_market_or_limit or with_stop"
```

Expected: AttributeError / "OrderIntent has no attribute 'signed_qty'".

- [ ] **Step 3: Add methods to OrderIntent**

In `src/bot/types.py`, **update** the existing `from dataclasses import dataclass` line to also import `replace`:

```python
from dataclasses import dataclass, replace
```

Then add the four methods inside the `OrderIntent` class body (after the `bracket` field):

```python
    # ---- Helper methods called by 04-risk-engine (spec 02 §4 lines 259-283) ----

    def signed_qty(self) -> int:
        """+quantity for BUY, -quantity for SELL. Used by rule 4 (max position)."""
        return self.quantity if self.side == "BUY" else -self.quantity

    def is_open_increasing_exposure(self, open_positions: dict[str, int]) -> bool:
        """True iff applying this intent would grow |position| on this symbol.

        A pure reducing/flattening order returns False. A flip (sell more than
        long) returns True — the resulting |short| is larger than original |long|.
        Used by rule 1 (hard-flat) — closes are always allowed after 15:00 CT.
        """
        current = open_positions.get(self.symbol, 0)
        projected = current + self.signed_qty()
        return abs(projected) > abs(current)

    def is_market_or_limit_open(self) -> bool:
        """True iff this intent opens (or modifies) exposure.

        Strategies emit only MARKET / LIMIT / BRACKET intents; STOP / STOP_LIMIT
        arrive only as bracket children submitted by the adapter. Used by
        rule 2 sub-check (STOP_REQUIRED).
        """
        return self.order_type in ("MARKET", "LIMIT", "BRACKET")

    def with_stop(self, ticks: int) -> "OrderIntent":
        """Return a NEW OrderIntent with bracket.stop_loss_ticks replaced.

        Used by rule 3 + §3.6 stop-offset safety buffer augmentation in 04.
        Raises ValueError if called on an intent that has no bracket.
        """
        if self.bracket is None:
            raise ValueError("with_stop() called on intent without a bracket")
        new_bracket = replace(self.bracket, stop_loss_ticks=ticks)
        return replace(self, bracket=new_bracket)
```

- [ ] **Step 4: Run and verify all OrderIntent tests pass**

```bash
pytest tests/test_types_order_intent.py -v
```

Expected: all tests pass (4 from Task 5 + 11 new = 15 total).

- [ ] **Step 5: Commit**

```bash
git add src/bot/types.py tests/test_types_order_intent.py
git commit -m "feat(types): OrderIntent helper methods (signed_qty, is_open_increasing_exposure, is_market_or_limit_open, with_stop)"
```

---

### Task 7: `Position`, `Order`, `OrderEvent` dataclasses

**Files:**
- Modify: `src/bot/types.py`
- Create: `tests/test_types_position_order_event.py`

Source: spec `02-execution-clients.md §4` lines 285-305.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_types_position_order_event.py
"""Tests for Position, Order, and OrderEvent dataclasses.

Spec: 02-execution-clients.md §4.
"""
from __future__ import annotations

import pytest


def test_position_basic_fields(utc_now) -> None:
    from bot.types import Position
    p = Position(
        symbol="MNQ", signed_qty=2, avg_entry_price=15000.0,
        unrealized_pnl=50.0, opened_at=utc_now,
    )
    assert p.symbol == "MNQ"
    assert p.signed_qty == 2


def test_position_short_has_negative_signed_qty(utc_now) -> None:
    from bot.types import Position
    p = Position(symbol="MNQ", signed_qty=-3, avg_entry_price=15000.0,
                 unrealized_pnl=0.0, opened_at=utc_now)
    assert p.signed_qty == -3


def test_order_minimal(utc_now) -> None:
    from bot.types import Order
    o = Order(
        client_order_id="c-1",
        broker_order_id="b-1",
        symbol="MNQ",
        side="BUY",
        quantity=1,
        order_type="MARKET",
        status="WORKING",
        timestamp=utc_now,
    )
    assert o.client_order_id == "c-1"
    assert o.status == "WORKING"


def test_order_event_pending_fields(utc_now) -> None:
    from bot.types import OrderEvent
    ev = OrderEvent(
        client_order_id="c-1",
        broker_order_id="b-1",
        status="PENDING",
        filled_quantity=0,
        avg_fill_price=None,
        timestamp=utc_now,
    )
    assert ev.status == "PENDING"
    assert ev.metadata is None


def test_order_event_filled_with_metadata(utc_now) -> None:
    from bot.types import OrderEvent
    ev = OrderEvent(
        client_order_id="c-1",
        broker_order_id="b-1",
        status="FILLED",
        filled_quantity=1,
        avg_fill_price=15010.25,
        timestamp=utc_now,
        metadata={"venue": "GLOBEX"},
    )
    assert ev.filled_quantity == 1
    assert ev.metadata == {"venue": "GLOBEX"}


def test_order_event_rejected_status_allowed(utc_now) -> None:
    from bot.types import OrderEvent
    ev = OrderEvent(client_order_id="c-1", broker_order_id="",
                    status="REJECTED", filled_quantity=0,
                    avg_fill_price=None, timestamp=utc_now,
                    metadata={"errorCode": 17})
    assert ev.status == "REJECTED"


def test_position_is_frozen(utc_now) -> None:
    from bot.types import Position
    from dataclasses import FrozenInstanceError
    p = Position(symbol="MNQ", signed_qty=1, avg_entry_price=1.0,
                 unrealized_pnl=0.0, opened_at=utc_now)
    with pytest.raises(FrozenInstanceError):
        p.signed_qty = 99  # type: ignore[misc]
```

- [ ] **Step 2: Run and verify the tests fail**

```bash
pytest tests/test_types_position_order_event.py -v
```

Expected: ImportError for `Position` / `Order` / `OrderEvent`.

- [ ] **Step 3: Add Position, Order, OrderEvent to `src/bot/types.py`**

Append after the `OrderIntent` class:

```python


OrderStatus = Literal[
    "PENDING", "WORKING", "PARTIAL_FILL", "FILLED", "CANCELED", "REJECTED",
]


@dataclass(frozen=True)
class Position:
    """Broker-reported position snapshot. See spec 02 §4 line 285."""
    symbol: str
    signed_qty: int              # +long, -short
    avg_entry_price: float
    unrealized_pnl: float
    opened_at: datetime


@dataclass(frozen=True)
class Order:
    """Broker-reported open-order snapshot. Returned by ExecutionClient.get_open_orders()."""
    client_order_id: str
    broker_order_id: str
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    status: OrderStatus
    timestamp: datetime
    limit_price: float | None = None
    stop_price: float | None = None


@dataclass(frozen=True)
class OrderEvent:
    """State transition emitted by ExecutionClient on every order update.

    The Strategy / RiskGate consume these via the engine's event bus; metadata
    holds broker-specific error codes (e.g. TopstepX errorCode on REJECTED).
    """
    client_order_id: str
    broker_order_id: str
    status: OrderStatus
    filled_quantity: int
    avg_fill_price: float | None
    timestamp: datetime
    metadata: dict[str, object] | None = None
```

- [ ] **Step 4: Run and verify tests pass**

```bash
pytest tests/test_types_position_order_event.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/bot/types.py tests/test_types_position_order_event.py
git commit -m "feat(types): Position, Order, OrderEvent dataclasses"
```

---

### Task 8: `AccountState` dataclass

**Files:**
- Modify: `src/bot/types.py`
- Create: `tests/test_types_account_state.py`

Source: spec `04-risk-engine.md §4.1` lines 388-404.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_types_account_state.py
"""Tests for the AccountState dataclass.

Spec: 04-risk-engine.md §4.1 lines 388-404.
"""
from __future__ import annotations

import pytest


def test_account_state_required_fields(utc_now) -> None:
    from bot.types import AccountState
    s = AccountState(
        equity=50_000.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=50_000.0,
        is_combine=True,
        timestamp=utc_now,
    )
    assert s.equity == 50_000.0
    assert s.is_combine is True


def test_account_state_defaults_for_locked_and_lock_point(utc_now) -> None:
    from bot.types import AccountState
    s = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
    )
    assert s.is_locked is False
    assert s.lock_point is None


def test_account_state_default_start_balance_is_50k(utc_now) -> None:
    from bot.types import AccountState
    s = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
    )
    assert s.start_balance == 50_000.0
    assert s.account_size == "50K"


def test_account_state_is_frozen(utc_now) -> None:
    from bot.types import AccountState
    from dataclasses import FrozenInstanceError
    s = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
    )
    with pytest.raises(FrozenInstanceError):
        s.equity = 99_999.0  # type: ignore[misc]


def test_account_state_position_dict_can_hold_short_and_long(utc_now) -> None:
    from bot.types import AccountState
    s = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={"MNQ": 3, "NQ": -1},
        pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
    )
    assert s.open_positions["MNQ"] == 3
    assert s.open_positions["NQ"] == -1
```

- [ ] **Step 2: Run and verify tests fail**

```bash
pytest tests/test_types_account_state.py -v
```

Expected: ImportError for `AccountState`.

- [ ] **Step 3: Add AccountState to `src/bot/types.py`**

Append after `OrderEvent`:

```python


# ---- Risk engine state (spec 04 §4.1) ---------------------------------------

AccountSize = Literal["50K", "100K", "150K"]


@dataclass(frozen=True)
class AccountState:
    """Tick-fresh account snapshot fed to TopstepRiskGate.approve_or_deny().

    Populated by the driver (Nautilus RiskEngine host) from broker queries on
    every tick. The phantom-MLL state machine in CombineIntradayDrawdown
    updates high_water_equity / is_locked / lock_point — never the strategy.
    See spec 04 §3.4.
    """
    equity: float                          # cash + unrealized; tick-fresh
    realized_pnl_today: float              # since 17:00 CT yesterday
    unrealized_pnl: float                  # mark-to-market on open positions
    open_positions: dict[str, int]         # symbol → signed qty (+long, -short)
    pending_intent_count: int              # in flight, not yet broker-acked
    high_water_equity: float               # for trailing MLL state machine
    is_combine: bool                       # Combine vs EFA flavor
    timestamp: datetime                    # tz-aware UTC
    is_locked: bool = False                # populated by phantom-MLL machine
    lock_point: float | None = None
    start_balance: float = 50_000.0
    account_size: AccountSize = "50K"
```

- [ ] **Step 4: Run and verify tests pass**

```bash
pytest tests/test_types_account_state.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/bot/types.py tests/test_types_account_state.py
git commit -m "feat(types): AccountState dataclass for risk engine"
```

---

### Task 9: `OrderDenied` and `ApprovedOrder` (risk-gate return types)

**Files:**
- Modify: `src/bot/types.py`
- Create: `tests/test_types_risk_results.py`

Source: spec `04-risk-engine.md §4.1` lines 406-419.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_types_risk_results.py
"""Tests for OrderDenied and ApprovedOrder (TopstepRiskGate return types).

Spec: 04-risk-engine.md §4.1 lines 406-419.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from bot.types import AccountState, OrderIntent


def _make_intent_and_state(utc_now: datetime) -> tuple[OrderIntent, AccountState]:
    intent = OrderIntent(
        symbol="MNQ", side="BUY", quantity=1,
        order_type="MARKET", client_order_id="t-1", timestamp=utc_now,
    )
    state = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
    )
    return intent, state


def test_order_denied_fields(utc_now: datetime) -> None:
    from bot.types import OrderDenied
    intent, state = _make_intent_and_state(utc_now)
    d = OrderDenied(
        intent=intent, reason="DLL near limit",
        rule="DLL_NEAR_LIMIT", state_snapshot=state, timestamp=utc_now,
    )
    assert d.rule == "DLL_NEAR_LIMIT"
    assert d.state_snapshot is state


def test_approved_order_fields(utc_now) -> None:
    from bot.types import ApprovedOrder
    intent, state = _make_intent_and_state(utc_now)
    a = ApprovedOrder(intent=intent, state_snapshot=state, timestamp=utc_now)
    assert a.intent is intent


def test_order_denied_is_frozen(utc_now) -> None:
    from bot.types import OrderDenied
    from dataclasses import FrozenInstanceError
    intent, state = _make_intent_and_state(utc_now)
    d = OrderDenied(intent=intent, reason="r", rule="R",
                    state_snapshot=state, timestamp=utc_now)
    with pytest.raises(FrozenInstanceError):
        d.reason = "x"  # type: ignore[misc]


def test_approved_order_is_frozen(utc_now) -> None:
    from bot.types import ApprovedOrder
    from dataclasses import FrozenInstanceError
    intent, state = _make_intent_and_state(utc_now)
    a = ApprovedOrder(intent=intent, state_snapshot=state, timestamp=utc_now)
    with pytest.raises(FrozenInstanceError):
        a.timestamp = utc_now  # type: ignore[misc]
```

- [ ] **Step 2: Run and verify tests fail**

```bash
pytest tests/test_types_risk_results.py -v
```

Expected: ImportError for `OrderDenied` / `ApprovedOrder`.

- [ ] **Step 3: Add OrderDenied and ApprovedOrder to `src/bot/types.py`**

Append after `AccountState`:

```python


@dataclass(frozen=True)
class OrderDenied:
    """Result returned by TopstepRiskGate.approve_or_deny() on rule violation."""
    intent: OrderIntent
    reason: str                            # human-readable
    rule: str                              # canonical, e.g. "DLL_NEAR_LIMIT"
    state_snapshot: AccountState
    timestamp: datetime


@dataclass(frozen=True)
class ApprovedOrder:
    """Result returned by TopstepRiskGate.approve_or_deny() on approval.

    `intent` is post-buffer-augmentation — its stop_loss_ticks may be tighter
    than what the strategy originally emitted, per spec 04 §3.6.
    """
    intent: OrderIntent                    # post-buffer-augmentation
    state_snapshot: AccountState
    timestamp: datetime
```

- [ ] **Step 4: Run and verify tests pass**

```bash
pytest tests/test_types_risk_results.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Verify ALL types tests still pass**

```bash
pytest tests/test_types_*.py -v
```

Expected: all tests pass (5 Bar/Tick + 15 OrderIntent + 7 Position/Order/OrderEvent + 5 AccountState + 4 risk results = 36 total).

- [ ] **Step 6: Commit**

```bash
git add src/bot/types.py tests/test_types_risk_results.py
git commit -m "feat(types): OrderDenied and ApprovedOrder for risk gate"
```

---

### Task 10: `bot/constants.py` — tick values + Topstep $50K Combine rule constants

**Files:**
- Create: `src/bot/constants.py`
- Create: `tests/test_constants.py`

Source: spec `00-architecture-overview.md §5` (rule constants table) and `04-risk-engine.md §3.2 rule 2` (tick values for MNQ / NQ).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_constants.py
"""Tests for the constants module.

Source: 00-architecture-overview.md §5 (rule constants table),
        04-risk-engine.md §3.2 rule 2 (tick values).
"""
from __future__ import annotations

import pytest


def test_tick_value_mnq_is_50_cents() -> None:
    """MNQ tick value = $0.50 (4 ticks/pt × $2/pt). See 04 §3.2 rule 2."""
    from bot.constants import TICK_VALUES
    assert TICK_VALUES["MNQ"] == pytest.approx(0.50)


def test_tick_value_nq_is_5_dollars() -> None:
    """NQ tick value = $5.00 (4 ticks/pt × $20/pt). See 04 §3.2 rule 2."""
    from bot.constants import TICK_VALUES
    assert TICK_VALUES["NQ"] == pytest.approx(5.00)


def test_min_tick_size() -> None:
    """Both MNQ and NQ tick at 0.25 points. See 02 §3.2 contract resolution."""
    from bot.constants import MIN_TICK
    assert MIN_TICK["MNQ"] == pytest.approx(0.25)
    assert MIN_TICK["NQ"] == pytest.approx(0.25)


def test_combine_50k_constants() -> None:
    """Topstep $50K Combine rule constants. See 00 §5."""
    from bot.constants import (
        COMBINE_50K_PROFIT_TARGET,
        COMBINE_50K_DLL,
        COMBINE_50K_MLL,
        COMBINE_50K_START_BALANCE,
        COMBINE_50K_MAX_MINI,
        COMBINE_50K_MAX_MICRO,
        COMBINE_50K_CONSISTENCY_PCT,
    )
    assert COMBINE_50K_START_BALANCE == 50_000
    assert COMBINE_50K_PROFIT_TARGET == 3_000
    assert COMBINE_50K_DLL == 1_000
    assert COMBINE_50K_MLL == 2_000
    assert COMBINE_50K_MAX_MINI == 5
    assert COMBINE_50K_MAX_MICRO == 50
    assert COMBINE_50K_CONSISTENCY_PCT == pytest.approx(0.50)


def test_hard_flat_time_is_15_10_chicago() -> None:
    """3:10 PM CT hard flat. See 00 §5 + §7 item 3."""
    from datetime import time
    from zoneinfo import ZoneInfo
    from bot.constants import HARD_FLAT_TIME_CT, HARD_FLAT_TZ
    assert HARD_FLAT_TIME_CT == time(15, 10)
    assert HARD_FLAT_TZ == ZoneInfo("America/Chicago")


def test_topstepx_side_constants_are_inverted_from_intuition() -> None:
    """TopstepX side encoding: 0=BUY (Bid), 1=SELL (Ask). The footgun.
    See 00 §7 item 1, 02 §3.4."""
    from bot.constants import TOPSTEPX_SIDE_BUY, TOPSTEPX_SIDE_SELL
    assert TOPSTEPX_SIDE_BUY == 0, "TopstepX 0 is BUY (Bid). Do not change."
    assert TOPSTEPX_SIDE_SELL == 1, "TopstepX 1 is SELL (Ask). Do not change."
```

- [ ] **Step 2: Run and verify tests fail**

```bash
pytest tests/test_constants.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Write `src/bot/constants.py`**

```python
# src/bot/constants.py
"""Static constants — CME contract specs and Topstep $50K Combine rule values.

Source:
- CME contract specs: NQ / MNQ tick = 0.25 pt, NQ point = $20, MNQ point = $2.
- Topstep $50K Combine rules: 00-architecture-overview.md §5.
- TopstepX side encoding: 02-execution-clients.md §3.4 (the inversion footgun).

Constants are loud-named and `Final`-annotated. Do NOT add a level of indirection
(no `RULES["mll"]`) — a typo on a key fails silently, a typo on a constant name
fails at import time.
"""
from __future__ import annotations

from datetime import time
from typing import Final
from zoneinfo import ZoneInfo


# ---- CME contract specs -----------------------------------------------------

# Dollar value of one tick, by symbol.
# MNQ: 0.25 pt × $2/pt  = $0.50/tick
# NQ:  0.25 pt × $20/pt = $5.00/tick
TICK_VALUES: Final[dict[str, float]] = {
    "MNQ": 0.50,
    "NQ":  5.00,
}

# Minimum tick size in points.
MIN_TICK: Final[dict[str, float]] = {
    "MNQ": 0.25,
    "NQ":  0.25,
}


# ---- Topstep $50K Combine rule constants (00 §5) ----------------------------

COMBINE_50K_START_BALANCE:   Final[float] = 50_000.0
COMBINE_50K_PROFIT_TARGET:   Final[float] = 3_000.0    # Combine pass threshold
COMBINE_50K_DLL:             Final[float] = 1_000.0    # Daily Loss Limit
COMBINE_50K_MLL:             Final[float] = 2_000.0    # Max Loss Limit (trailing, intraday on unrealized)
COMBINE_50K_MAX_MINI:        Final[int]   = 5
COMBINE_50K_MAX_MICRO:       Final[int]   = 50
COMBINE_50K_CONSISTENCY_PCT: Final[float] = 0.50       # best-day-vs-target ≤ 50%

# Hard-flat time, timezone-aware (00 §5, §7 item 3).
HARD_FLAT_TIME_CT: Final[time]     = time(15, 10)
HARD_FLAT_TZ:      Final[ZoneInfo] = ZoneInfo("America/Chicago")
PREEMPT_FLAT_TIME_CT: Final[time]  = time(15, 0)       # soft-warn after this (04 §3.2 rule 1)


# ---- TopstepX wire protocol — DO NOT REORDER (00 §7 item 1, 02 §3.4) --------

# These constants are loud on purpose. If you "simplify" them, you will lose money.
TOPSTEPX_SIDE_BUY:  Final[int] = 0   # Bid
TOPSTEPX_SIDE_SELL: Final[int] = 1   # Ask
```

- [ ] **Step 4: Run and verify tests pass**

```bash
pytest tests/test_constants.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/bot/constants.py tests/test_constants.py
git commit -m "feat(constants): tick values + Topstep \$50K Combine rule constants + TopstepX side encoding"
```

---

### Task 11: `ExecutionClient` Protocol shell

**Files:**
- Create: `src/bot/execution/ports.py`
- Create: `tests/test_execution_ports.py`

Source: spec `02-execution-clients.md §3.1` (port interface) and §4 lines 307-316.

The Protocol is a shell — no implementation. Tests assert that the Protocol's surface matches the spec and that a dummy implementation satisfies it at type-check time.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_execution_ports.py
"""Tests for the ExecutionClient Protocol.

Spec: 02-execution-clients.md §3.1, §4 lines 307-316.

These tests verify the Protocol's method signatures exist and that a dummy
implementation satisfies it structurally. Real adapter conformance lives in
Plan 6 (IB) / Plan 8 (TopstepX) / Plan 4 (Sim) — this just nails down the seam.
"""
from __future__ import annotations

import pytest


def test_execution_client_protocol_importable() -> None:
    from bot.execution.ports import ExecutionClient
    assert ExecutionClient is not None


def test_execution_client_protocol_has_expected_methods() -> None:
    from bot.execution.ports import ExecutionClient
    expected = {
        "connect", "disconnect",
        "place_order", "cancel_order", "cancel_all",
        "get_positions", "get_open_orders", "get_account",
    }
    actual = {n for n in dir(ExecutionClient) if not n.startswith("_")}
    missing = expected - actual
    assert not missing, f"Protocol missing methods: {missing}"


@pytest.mark.asyncio
async def test_dummy_implementation_satisfies_protocol(utc_now) -> None:
    """A dummy class with matching async signatures satisfies the structural
    Protocol. This proves the Protocol is correctly shaped for Plan 4 / 6 / 8."""
    from bot.execution.ports import ExecutionClient
    from bot.types import (
        AccountState, Order, OrderEvent, OrderIntent, Position,
    )

    class _DummyClient:
        async def connect(self) -> None: ...
        async def disconnect(self) -> None: ...
        async def place_order(self, intent: OrderIntent) -> OrderEvent:
            return OrderEvent(
                client_order_id=intent.client_order_id,
                broker_order_id="b-x", status="PENDING",
                filled_quantity=0, avg_fill_price=None,
                timestamp=intent.timestamp,
            )
        async def cancel_order(self, client_order_id: str) -> OrderEvent:
            return OrderEvent(
                client_order_id=client_order_id, broker_order_id="b-x",
                status="CANCELED", filled_quantity=0, avg_fill_price=None,
                timestamp=utc_now,
            )
        async def cancel_all(self, symbol: str) -> list[OrderEvent]:
            return []
        async def get_positions(self) -> list[Position]: return []
        async def get_open_orders(self) -> list[Order]: return []
        async def get_account(self) -> AccountState:
            return AccountState(
                equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
                open_positions={}, pending_intent_count=0,
                high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
            )

    client: ExecutionClient = _DummyClient()  # structural conformance check
    assert (await client.get_account()).equity == 50_000.0
```

- [ ] **Step 2: Run and verify tests fail**

```bash
pytest tests/test_execution_ports.py -v
```

Expected: ModuleNotFoundError for `bot.execution.ports`.

- [ ] **Step 3: Write `src/bot/execution/ports.py`**

```python
# src/bot/execution/ports.py
"""ExecutionClient port (Protocol).

The single seam between strategy/risk-gate and broker wire formats. Three
concrete implementations live in sibling plans:
  - Plan 4 : SimExecutionClient (deterministic, in-memory)
  - Plan 6 : IBExecutionClient (paper rail via ib_async)
  - Plan 8 : TopstepXExecutionClient (live rail via project-x-py)

Spec: 02-execution-clients.md §3.1, §4 lines 307-316.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bot.types import (
    AccountState,
    Order,
    OrderEvent,
    OrderIntent,
    Position,
)


@runtime_checkable
class ExecutionClient(Protocol):
    """Broker-agnostic execution port. All methods async.

    Idempotency: `place_order` is idempotent on `intent.client_order_id` —
    the adapter dedupes on a recent-submissions cache plus the broker's
    own dedup key (IB orderRef, TopstepX customTag). See spec 02 §3.8.
    """

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def place_order(self, intent: OrderIntent) -> OrderEvent: ...

    async def cancel_order(self, client_order_id: str) -> OrderEvent: ...

    async def cancel_all(self, symbol: str) -> list[OrderEvent]: ...

    async def get_positions(self) -> list[Position]: ...

    async def get_open_orders(self) -> list[Order]: ...

    async def get_account(self) -> AccountState: ...
```

- [ ] **Step 4: Run and verify tests pass**

```bash
pytest tests/test_execution_ports.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/bot/execution/ports.py tests/test_execution_ports.py
git commit -m "feat(execution): ExecutionClient Protocol shell"
```

---

### Task 12: `DrawdownPolicy` Protocol shell

**Files:**
- Create: `src/bot/risk/policies.py`
- Create: `tests/test_risk_policies.py`

Source: spec `04-risk-engine.md §3.3` (DrawdownPolicy interface, lines 215-225).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_risk_policies.py
"""Tests for the DrawdownPolicy Protocol.

Spec: 04-risk-engine.md §3.3 lines 215-225.

The three concrete policies (CombineIntradayDrawdown, EFAStandardEoDDrawdown,
EFAConsistencyDrawdown) are implemented in Plan 3 (Risk Engine). This file
only nails down the Protocol shape so Plan 3 has a target to extend.
"""
from __future__ import annotations

import pytest


def test_drawdown_policy_protocol_importable() -> None:
    from bot.risk.policies import DrawdownPolicy
    assert DrawdownPolicy is not None


def test_drawdown_policy_protocol_has_expected_methods() -> None:
    from bot.risk.policies import DrawdownPolicy
    expected = {
        "phantom_mll", "is_locked", "max_position",
        "update_on_tick", "update_on_eod",
    }
    actual = {n for n in dir(DrawdownPolicy) if not n.startswith("_")}
    missing = expected - actual
    assert not missing, f"Protocol missing methods: {missing}"


def test_dummy_policy_satisfies_protocol(utc_now) -> None:
    """Trivial policy where the floor is fixed at start_balance - MLL.
    Validates the Protocol's shape; not real risk-engine logic."""
    from bot.risk.policies import DrawdownPolicy
    from bot.types import AccountState

    class _NoopPolicy:
        def phantom_mll(self, state: AccountState) -> float:
            return state.start_balance - 2_000.0
        def is_locked(self, state: AccountState) -> bool:
            return False
        def max_position(self, symbol: str, state: AccountState) -> int:
            return 0
        def update_on_tick(self, state: AccountState) -> AccountState:
            return state
        def update_on_eod(self, state: AccountState) -> AccountState:
            return state

    p: DrawdownPolicy = _NoopPolicy()
    state = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
    )
    assert p.phantom_mll(state) == pytest.approx(48_000.0)
    assert p.is_locked(state) is False
    assert p.update_on_tick(state) is state
```

- [ ] **Step 2: Run and verify tests fail**

```bash
pytest tests/test_risk_policies.py -v
```

Expected: ModuleNotFoundError for `bot.risk.policies`.

- [ ] **Step 3: Write `src/bot/risk/policies.py`**

```python
# src/bot/risk/policies.py
"""DrawdownPolicy port (Protocol).

Three concrete policies live in Plan 3 (Risk Engine):
  - CombineIntradayDrawdown    : real-time on unrealized; locks at start_balance
  - EFAStandardEoDDrawdown     : EoD-trailing; profit-gated scaling plan
  - EFAConsistencyDrawdown     : EoD-trailing + payout-window 40% cap

This file ships the Protocol shell only. Concrete implementations + the
phantom-MLL state machine + force-flatten triggers come in Plan 3.

Spec: 04-risk-engine.md §3.3 lines 215-225.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bot.types import AccountState


@runtime_checkable
class DrawdownPolicy(Protocol):
    """Selects the Combine vs EFA drawdown semantics for TopstepRiskGate.

    All methods are pure functions on AccountState. State updates return a new
    AccountState; never mutate. See spec 04 §3.4 transition diagram.
    """

    def phantom_mll(self, state: AccountState) -> float:
        """Equity floor below which the account is dead. Used by rule 3."""
        ...

    def is_locked(self, state: AccountState) -> bool:
        """True once the trailing drawdown has reached its lock point."""
        ...

    def max_position(self, symbol: str, state: AccountState) -> int:
        """Per-symbol size cap. Used by rule 4.

        For Combine: fixed. For EFA: profit-gated scaling plan keyed off
        accumulated profit (= equity - start_balance), NOT absolute equity.
        See spec 04 §3.2 rule 4 note.
        """
        ...

    def update_on_tick(self, state: AccountState) -> AccountState:
        """Return a new AccountState with high_water_equity / is_locked /
        lock_point updated per the policy's tick-cadence rules.

        Combine: ratchets high-water on every tick; locks at start_balance
        once high_water >= start_balance + MLL.
        EFA: tick is a no-op (EoD-trailing).
        """
        ...

    def update_on_eod(self, state: AccountState) -> AccountState:
        """End-of-day update.

        Combine: no-op.
        EFA: ratchets high_water_equity at session close.
        """
        ...
```

- [ ] **Step 4: Run and verify tests pass**

```bash
pytest tests/test_risk_policies.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/bot/risk/policies.py tests/test_risk_policies.py
git commit -m "feat(risk): DrawdownPolicy Protocol shell"
```

---

### Task 13: Pydantic config models (`DataConfig`, `TelegramConfig`, `BotConfig` core)

**Files:**
- Create: `src/bot/config.py`
- Create: `tests/test_config.py` (initial tests; more tests added in Task 14)

Source: spec `07-config-and-deploy.md §3.1` (config schema). The two cross-validators are added in Task 14 — this task only ships the dataclasses.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
"""Tests for Pydantic config models.

Spec: 07-config-and-deploy.md §3.1.
"""
from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest
from pydantic import ValidationError


def _valid_config_kwargs() -> dict[str, object]:
    """Minimal kwargs that produce a valid BotConfig. Tests mutate copies of this
    to verify specific validator paths."""
    return {
        "env": "dev",
        "broker": "sim",
        "account_id": "sim-0",
        "strategy": "orb",
        "strategy_profile": Path("config/profiles/surge.yml"),
        "risk_policy": "combine_50k",
        "data": {
            "historical_root": Path("data/parquet"),
            "historical_vendor": "firstratedata",
            "live_source": "ib",
        },
        "telegram": {},
        "news_calendar": Path("config/news_calendar.yml"),
    }


def test_data_config_defaults() -> None:
    from bot.config import DataConfig
    c = DataConfig(
        historical_root=Path("data/parquet"),
        historical_vendor="firstratedata",
        live_source="ib",
    )
    assert c.symbol_primary == "MNQ"
    assert c.bar_seconds == 60


def test_telegram_config_default_severity_is_WARN() -> None:
    """Severity is "WARN" (not "WARNING") to match 06-observability.md §3.2.
    See spec 07 §3.1."""
    from bot.config import TelegramConfig
    t = TelegramConfig()
    assert t.min_severity == "WARN"
    assert t.bot_token_env == "TELEGRAM_BOT_TOKEN"
    assert t.chat_id_env == "TELEGRAM_CHAT_ID"


def test_bot_config_minimal_valid() -> None:
    from bot.config import BotConfig
    c = BotConfig(**_valid_config_kwargs())
    assert c.env == "dev"
    assert c.broker == "sim"
    assert c.flat_by_force_ct == time(15, 10)
    assert c.flat_by_warning_ct == time(14, 0)
    assert c.halt_on_journal_desync is True


def test_bot_config_rejects_unknown_env() -> None:
    from bot.config import BotConfig
    kwargs = _valid_config_kwargs() | {"env": "production"}
    with pytest.raises(ValidationError):
        BotConfig(**kwargs)


def test_bot_config_rejects_unknown_risk_policy() -> None:
    from bot.config import BotConfig
    kwargs = _valid_config_kwargs() | {"risk_policy": "bogus_policy"}
    with pytest.raises(ValidationError):
        BotConfig(**kwargs)
```

- [ ] **Step 2: Run and verify tests fail**

```bash
pytest tests/test_config.py -v
```

Expected: ModuleNotFoundError for `bot.config`.

- [ ] **Step 3: Write `src/bot/config.py`**

```python
# src/bot/config.py
"""Pydantic v2 configuration models for the futures bot.

Spec: 07-config-and-deploy.md §3.1.

Two cross-field validators (broker_matches_env, force_after_warning) live on
BotConfig — they're added in the next task so this file can be split into
small bite-sized test passes.
"""
from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---- Sub-configs ------------------------------------------------------------

class DataConfig(BaseModel):
    """Data pipeline settings. See spec 01 + 07 §3.1."""
    historical_root: Path                           # parquet store
    historical_vendor: Literal["firstratedata"]
    live_source: Literal["ib", "topstepx"]
    symbol_primary: Literal["MNQ", "NQ"] = "MNQ"
    bar_seconds: int = Field(default=60, ge=1)      # 1-min bars by default


class TelegramConfig(BaseModel):
    """Telegram alerts. Actual token / chat_id live in env vars; these fields
    name the env vars, they are NOT secrets themselves.

    NB: severity strings match 06-observability.md §3.2 / §3.6 (WARN, not WARNING).
    """
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"
    min_severity: Literal["INFO", "WARN", "CRITICAL"] = "WARN"


# ---- Root config ------------------------------------------------------------

Env = Literal["dev", "paper", "live"]
Broker = Literal["sim", "ib_paper", "topstepx"]
RiskPolicyTag = Literal[
    "combine_50k",
    "efa_standard_50k",
    "efa_consistency_50k",
]


class BotConfig(BaseModel):
    """Root configuration loaded from bot/config/bot.yml.

    Cross-field validators (broker_matches_env, force_after_warning) are
    attached in the next task. validate_default=True ensures those validators
    run against default values too — so a YAML that omits flat_by_force_ct
    can't silently bypass force_after_warning.
    """
    model_config = ConfigDict(validate_default=True)

    env: Env
    broker: Broker
    account_id: str                                 # IB account or TopstepX accountId
    strategy: Literal["orb"]
    strategy_profile: Path                          # path to surge.yml or maintenance.yml
    risk_policy: RiskPolicyTag
    data: DataConfig
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    news_calendar: Path
    flat_by_warning_ct: time = time(14, 0)          # soft warn — 04-risk-engine
    flat_by_force_ct:   time = time(15, 10)         # hard flatten — 04-risk-engine
    halt_on_journal_desync: bool = True
```

- [ ] **Step 4: Run and verify tests pass**

```bash
pytest tests/test_config.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/bot/config.py tests/test_config.py
git commit -m "feat(config): Pydantic BotConfig + DataConfig + TelegramConfig"
```

---

### Task 14: BotConfig cross-validators (`broker_matches_env`, `force_after_warning`)

**Files:**
- Modify: `src/bot/config.py`
- Modify: `tests/test_config.py` (append tests)

Source: spec `07-config-and-deploy.md §3.1` lines 75-94.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python


# ---- Cross-validators (spec 07 §3.1 lines 75-94) ----------------------------

@pytest.mark.parametrize(
    "env,broker,should_pass",
    [
        ("dev",   "sim",      True),
        ("dev",   "ib_paper", True),
        ("dev",   "topstepx", True),
        ("paper", "sim",      False),   # paper env demands a real broker
        ("paper", "ib_paper", True),
        ("paper", "topstepx", True),    # TopstepX Practice sub-account OK
        ("live",  "sim",      False),
        ("live",  "ib_paper", False),
        ("live",  "topstepx", True),
    ],
)
def test_broker_matches_env_matrix(env: str, broker: str, should_pass: bool) -> None:
    from bot.config import BotConfig
    kwargs = _valid_config_kwargs() | {"env": env, "broker": broker}
    if should_pass:
        BotConfig(**kwargs)
    else:
        with pytest.raises(ValidationError, match=r"broker=.* not allowed in env="):
            BotConfig(**kwargs)


def test_flat_by_force_must_be_after_warning() -> None:
    from bot.config import BotConfig
    kwargs = _valid_config_kwargs() | {
        "flat_by_warning_ct": time(15, 30),
        "flat_by_force_ct":   time(15, 10),     # before warning — invalid
    }
    with pytest.raises(ValidationError, match="must be after"):
        BotConfig(**kwargs)


def test_flat_by_force_equal_to_warning_is_invalid() -> None:
    """Equality is also a denial (the rule is strict 'after')."""
    from bot.config import BotConfig
    kwargs = _valid_config_kwargs() | {
        "flat_by_warning_ct": time(15, 10),
        "flat_by_force_ct":   time(15, 10),
    }
    with pytest.raises(ValidationError, match="must be after"):
        BotConfig(**kwargs)


def test_flat_by_force_strictly_after_is_valid() -> None:
    from bot.config import BotConfig
    kwargs = _valid_config_kwargs() | {
        "flat_by_warning_ct": time(14, 0),
        "flat_by_force_ct":   time(15, 10),
    }
    c = BotConfig(**kwargs)
    assert c.flat_by_force_ct == time(15, 10)
```

- [ ] **Step 2: Run and verify tests fail**

```bash
pytest tests/test_config.py -v -k "matrix or flat_by_force"
```

Expected: most matrix cases fail because the validator doesn't exist; `flat_by_force` cases pass for the strictly-after-valid case but fail for the others.

- [ ] **Step 3: Add the two validators to `BotConfig` in `src/bot/config.py`**

First, update the import line at the top to keep `ConfigDict` from Task 13 and add `ValidationInfo` + `field_validator`:

```python
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
```

Then, inside the `BotConfig` class body (after the `halt_on_journal_desync` field), add:

```python
    @field_validator("broker")
    @classmethod
    def broker_matches_env(cls, v: Broker, info: ValidationInfo) -> Broker:
        """env=live demands broker=topstepx (no paper rail on a live Topstep
        account). env=paper allows ib_paper or topstepx (TopstepX Practice).
        See spec 07 §3.1 + 00 D14."""
        env: Env | None = info.data.get("env")
        allowed: dict[Env, set[Broker]] = {
            "dev":   {"sim", "ib_paper", "topstepx"},
            "paper": {"ib_paper", "topstepx"},
            "live":  {"topstepx"},
        }
        if env is not None and v not in allowed[env]:
            raise ValueError(f"broker={v} not allowed in env={env}")
        return v

    @field_validator("flat_by_force_ct")
    @classmethod
    def force_after_warning(cls, v: time, info: ValidationInfo) -> time:
        """Hard-flat time must strictly exceed the soft-warning time."""
        warn: time | None = info.data.get("flat_by_warning_ct")
        if warn is not None and v <= warn:
            raise ValueError("flat_by_force_ct must be after flat_by_warning_ct")
        return v
```

- [ ] **Step 4: Run and verify all config tests pass**

```bash
pytest tests/test_config.py -v
```

Expected: 14 passed (5 from Task 13 + 9 cross-validator cases).

- [ ] **Step 5: Commit**

```bash
git add src/bot/config.py tests/test_config.py
git commit -m "feat(config): cross-validators broker_matches_env + force_after_warning"
```

---

### Task 15: `load_config()` helper + example `bot.example.yml`

**Files:**
- Modify: `src/bot/config.py` (add `load_config` function at bottom)
- Create: `config/bot.example.yml`
- Modify: `tests/test_config.py` (append load-from-disk test)

- [ ] **Step 1: Write `config/bot.example.yml`**

```bash
mkdir -p config
```

```yaml
# config/bot.example.yml
# Sample BotConfig for `env=dev, broker=sim`. Copy to config/bot.yml and edit
# for your environment. Secrets (broker creds, telegram tokens) live in .env,
# never in this file.

env: dev
broker: sim
account_id: sim-0
strategy: orb
strategy_profile: config/profiles/surge.yml
risk_policy: combine_50k

data:
  historical_root: data/parquet
  historical_vendor: firstratedata
  live_source: ib
  symbol_primary: MNQ
  bar_seconds: 60

telegram:
  bot_token_env: TELEGRAM_BOT_TOKEN
  chat_id_env: TELEGRAM_CHAT_ID
  min_severity: WARN

news_calendar: config/news_calendar.yml

flat_by_warning_ct: "14:00:00"
flat_by_force_ct:   "15:10:00"
halt_on_journal_desync: true
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_config.py`:

```python


# ---- load_config() from disk -------------------------------------------------

# Path-robust: anchor to the repo root via __file__ instead of CWD, so the test
# passes regardless of where pytest is invoked from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_load_config_from_example_yaml() -> None:
    from bot.config import load_config
    c = load_config(_PROJECT_ROOT / "config" / "bot.example.yml")
    assert c.env == "dev"
    assert c.broker == "sim"
    assert c.data.symbol_primary == "MNQ"
    assert c.telegram.min_severity == "WARN"
```

- [ ] **Step 3: Run and verify test fails**

```bash
pytest tests/test_config.py::test_load_config_from_example_yaml -v
```

Expected: ImportError — `load_config` not defined.

- [ ] **Step 4: Add `load_config` to `src/bot/config.py`**

Append at the bottom of `src/bot/config.py`:

```python


# ---- Loader helper ----------------------------------------------------------

def load_config(path: Path) -> BotConfig:
    """Load and validate a BotConfig from a YAML file.

    The loader does NOT load secrets — those come from `.env` via a separate
    `load_secrets()` helper added in Plan 9. See spec 07 §3.2.
    """
    import yaml

    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping, got {type(raw).__name__}")
    return BotConfig.model_validate(raw)
```

- [ ] **Step 5: Run and verify all config tests pass**

```bash
pytest tests/test_config.py -v
```

Expected: 15 passed (14 from Task 14 + 1 load test).

- [ ] **Step 6: Commit**

```bash
git add src/bot/config.py config/bot.example.yml tests/test_config.py
git commit -m "feat(config): load_config helper + example bot.yml"
```

---

### Task 16: Final verification — type-check, lint, full test sweep, deliverable check

**Files:** (no new files)

- [ ] **Step 1: Run ruff across all source**

```bash
ruff check src/ tests/
```

Expected: all clean. If there are findings (e.g., unused imports left over from incremental edits), fix them with `ruff check --fix src/ tests/` and verify with another `ruff check`.

- [ ] **Step 2: Run mypy in strict mode**

```bash
mypy src/ tests/
```

Expected: `Success: no issues found in N source files`. If mypy complains about missing stubs for third-party libraries (e.g., `pyyaml`), the `[[tool.mypy.overrides]]` section in `pyproject.toml` should already cover it; if a new library appears, add it to that section (do not add `# type: ignore` line-by-line as a shortcut).

- [ ] **Step 3: Run the full test suite**

```bash
pytest -v
```

Expected: every test from every task passes. Approximate count:
- test_smoke.py: 4
- test_types_bar_tick.py: 5
- test_types_order_intent.py: 15
- test_types_position_order_event.py: 7
- test_types_account_state.py: 5
- test_types_risk_results.py: 4
- test_constants.py: 6
- test_execution_ports.py: 3
- test_risk_policies.py: 3
- test_config.py: 15

Total ≈ 67 passed.

- [ ] **Step 4: Verify the deliverable acceptance commands**

Run from the project root (the directory containing `pyproject.toml`):

```bash
cd "/Users/abusiddique/Library/Mobile Documents/com~apple~CloudDocs/projects/algo trade training"
python -c "import bot, bot.types, bot.constants, bot.execution.ports, bot.risk.policies; print('imports OK')"
```

Expected: `imports OK`.

```bash
python -c "from bot.config import load_config; from pathlib import Path; print(load_config(Path('config/bot.example.yml')))"
```

Expected: prints a `BotConfig(env='dev', broker='sim', ...)` repr. (Relative path resolves correctly because we `cd`'d above.)

- [ ] **Step 5: Final commit (clean-up only, if needed)**

If steps 1-4 made any cleanup edits, commit them:

```bash
git add -A
git status                                 # verify only intended files
git diff --cached
git commit -m "chore: final cleanup after Plan 1 verification"
```

If no cleanup was needed, skip the commit step — git is already clean.

- [ ] **Step 6: Tag the plan completion**

```bash
git tag plan-01-foundation-complete
git log --oneline | head -20               # sanity-check commit history
```

The tag marks the foundation checkpoint; Plan 2 will start from this commit.

---

## Self-Review Checklist (run before declaring Plan 1 done)

1. **Spec coverage** — each line in the table below traces to a task:

   | Spec section | Task |
   |---|---|
   | 01 §3.5 + §4 (Bar/Tick + tz-aware) | Task 4 |
   | 02 §4 line 241-256 (Bracket, OrderIntent base) | Task 5 |
   | 02 §4 line 259-283 (OrderIntent helpers) | Task 6 |
   | 02 §4 line 285-305 (Position, Order, OrderEvent) | Task 7 |
   | 04 §4.1 line 388-404 (AccountState) | Task 8 |
   | 04 §4.1 line 406-419 (OrderDenied, ApprovedOrder) | Task 9 |
   | 00 §5 + 04 §3.2 rule 2 + 02 §3.4 (constants) | Task 10 |
   | 02 §3.1 + §4 line 307-316 (ExecutionClient Protocol) | Task 11 |
   | 04 §3.3 line 215-225 (DrawdownPolicy Protocol) | Task 12 |
   | 07 §3.1 base + 06 severity match | Task 13 |
   | 07 §3.1 line 75-94 cross-validators | Task 14 |
   | 07 §3.1 + load helper (implicit) | Task 15 |

2. **Type-signature consistency** — verify:
   - `OrderIntent.with_stop(ticks: int)` returns `"OrderIntent"` (forward ref string) — yes, see Task 6 implementation.
   - `OrderEvent.metadata: dict[str, object] | None` — yes, Task 7.
   - `AccountState.account_size: AccountSize` (not `account_size_key`) — yes, Task 8 matches spec 04 §4.1 fixup.
   - `TelegramConfig.min_severity: Literal["INFO", "WARN", "CRITICAL"]` (not "WARNING") — yes, Task 13 matches spec 07 inline fix #4.

3. **No placeholders** — no "TODO" / "TBD" / "add appropriate" in any task. ✅

4. **No premature implementation** — Protocols are shells; concrete `Combine*Drawdown`, `IBExecutionClient`, etc. all live in later plans. ✅

5. **iCloud caveat surfaced** — yes, top-of-file under "Scope notes."

---

## Out-of-scope for Plan 1 (explicit YAGNI list)

These belong in later plans and are NOT to be added here:

- ❌ Concrete `DrawdownPolicy` implementations (Plan 3)
- ❌ Concrete `ExecutionClient` adapters (Plans 4 / 6 / 8)
- ❌ `TopstepRiskGate` class (Plan 3)
- ❌ Strategy classes (Plan 5)
- ❌ Data pipeline / FirstRateData ingest (Plan 2)
- ❌ SQLite journal / log schema (Plan 7)
- ❌ Telegram polling / alerts (Plan 7)
- ❌ `secrets.py` / `reconcile.py` / `runtime.py` (Plan 9)
- ❌ `Dockerfile` / `docker-compose.yml` / LaunchAgent (Plan 9)
- ❌ Hostname whitelist + VPS guard (Plan 9 step in spec 07 §3.6)

---

## Notes for the executor

- This plan is TDD-strict: every implementation step is preceded by a failing test step. Do not skip the "verify it fails" step — it is the only way to know your test would actually catch a regression.
- The plan's per-task commits are small. Resist the urge to batch — small commits make a `git bisect` over the eventual 9-plan stack tractable.
- If a step's expected output diverges from reality (a library bump changed something), STOP and document the divergence rather than papering over it. The next plan in the stack reads this one's commits to know what's already done.
- Estimated wall-clock budget: 2-4 focused hours for an LLM agent executor, 4-6 for a careful human. The Nautilus install in Task 2 Step 2 is the long pole at ~3 minutes.
