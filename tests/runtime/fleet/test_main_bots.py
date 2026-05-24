"""bot.runtime.main --bots integration."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.runtime.main import (
    EXIT_NO_BOTS,
    EXIT_OK,
    run_fleet,
)

_MINIMAL_SPEC = """\
name: alpha
enabled: true
symbol: MNQ
strategy_id: orb_5m
strategy_params: {{}}
risk_policy: combine_intraday
risk_params:
  start_balance: 50000
  mll_amount: 2000
  max_mini: 5
schedule_type: always
schedule_params: {{}}
journal_path: {jpath}
"""


def _broker_mock() -> MagicMock:
    from datetime import UTC, datetime

    from bot.types import AccountState
    b = MagicMock()
    b.connect = AsyncMock(return_value=None)
    b.disconnect = AsyncMock(return_value=None)
    b.get_positions = AsyncMock(return_value=[])
    b.get_open_orders = AsyncMock(return_value=[])
    b.get_account = AsyncMock(return_value=AccountState(
        equity=50_000.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=50_000.0,
        is_combine=True,
        timestamp=datetime(2026, 5, 23, 14, 0, tzinfo=UTC),
    ))
    return b


async def test_check_only_loads_specs_and_exits_zero(tmp_path: Path) -> None:
    """`--bots <dir> --check` validates registry + spec set; exits 0."""
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    j1 = tmp_path / "j1.db"
    (bots_dir / "alpha.yml").write_text(_MINIMAL_SPEC.format(jpath=j1), encoding="utf-8")

    broker = _broker_mock()
    exit_code = await run_fleet(
        bots_dir=bots_dir,
        check_only=True,
        connect_broker_fn=AsyncMock(return_value=broker),
    )
    assert exit_code == EXIT_OK


async def test_empty_dir_returns_no_bots(tmp_path: Path) -> None:
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()

    exit_code = await run_fleet(
        bots_dir=bots_dir,
        check_only=True,
        connect_broker_fn=AsyncMock(return_value=_broker_mock()),
    )
    assert exit_code == EXIT_NO_BOTS


async def test_all_disabled_returns_no_bots(tmp_path: Path) -> None:
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    body = _MINIMAL_SPEC.format(jpath=tmp_path / "j.db").replace(
        "enabled: true", "enabled: false"
    )
    (bots_dir / "alpha.yml").write_text(body, encoding="utf-8")

    exit_code = await run_fleet(
        bots_dir=bots_dir,
        check_only=True,
        connect_broker_fn=AsyncMock(return_value=_broker_mock()),
    )
    assert exit_code == EXIT_NO_BOTS


@pytest.mark.parametrize("check_only", [True, False])
async def test_disabled_bots_skipped(tmp_path: Path, check_only: bool) -> None:
    """Disabled bots are filtered before construction; enabled bots remain."""
    bots_dir = tmp_path / "bots"
    bots_dir.mkdir()
    a = _MINIMAL_SPEC.format(jpath=tmp_path / "ja.db")
    b = _MINIMAL_SPEC.format(jpath=tmp_path / "jb.db").replace(
        "alpha", "beta",
    ).replace("enabled: true", "enabled: false")
    (bots_dir / "alpha.yml").write_text(a, encoding="utf-8")
    (bots_dir / "beta.yml").write_text(b, encoding="utf-8")

    broker = _broker_mock()
    # For non-check, we need the run path to terminate. Use an empty source.
    from bot.runtime.bar_source import SimBarSource
    exit_code = await run_fleet(
        bots_dir=bots_dir,
        check_only=check_only,
        connect_broker_fn=AsyncMock(return_value=broker),
        bar_source_factory=lambda spec: SimBarSource([]),
    )
    assert exit_code == EXIT_OK
