"""BotSpec dataclass + load_bot_specs YAML loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from bot.runtime.fleet.spec import BotSpec, ConfigError, load_bot_specs


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


_MINIMAL = """\
name: alpha
enabled: true
symbol: MNQ
strategy_id: orb_5m
strategy_params:
  range_minutes: 5
risk_policy: combine_intraday
risk_params:
  start_balance: 50000
  mll_amount: 2000
  max_mini: 5
schedule_type: always
schedule_params: {}
journal_path: state/journal_alpha.db
"""


def test_round_trip_fields(tmp_path: Path) -> None:
    _write(tmp_path / "alpha.yml", _MINIMAL)
    specs = load_bot_specs(tmp_path)
    assert len(specs) == 1
    s = specs[0]
    assert s.name == "alpha"
    assert s.enabled is True
    assert s.symbol == "MNQ"
    assert s.strategy_id == "orb_5m"
    assert s.strategy_params == {"range_minutes": 5}
    assert s.risk_policy == "combine_intraday"
    assert s.risk_params["start_balance"] == 50000
    assert s.schedule_type == "always"
    assert s.schedule_params == {}
    assert s.journal_path == Path("state/journal_alpha.db")


def test_two_files_two_specs_sorted(tmp_path: Path) -> None:
    _write(tmp_path / "alpha.yml", _MINIMAL)
    _write(tmp_path / "beta.yml", _MINIMAL.replace("alpha", "beta"))
    specs = load_bot_specs(tmp_path)
    names = [s.name for s in specs]
    assert names == ["alpha", "beta"]


def test_duplicate_names_raise(tmp_path: Path) -> None:
    _write(tmp_path / "a.yml", _MINIMAL)
    _write(tmp_path / "b.yml", _MINIMAL)  # same `name: alpha`
    with pytest.raises(ConfigError, match=r"duplicate.*alpha"):
        load_bot_specs(tmp_path)


def test_duplicate_journal_paths_raise(tmp_path: Path) -> None:
    _write(tmp_path / "a.yml", _MINIMAL)
    _write(tmp_path / "b.yml", _MINIMAL.replace("alpha", "beta").replace(
        "journal_beta.db", "journal_alpha.db"
    ))
    with pytest.raises(ConfigError, match="duplicate journal_path"):
        load_bot_specs(tmp_path)


def test_missing_required_field_raises(tmp_path: Path) -> None:
    body = _MINIMAL.replace("symbol: MNQ\n", "")
    _write(tmp_path / "broken.yml", body)
    with pytest.raises(ConfigError, match="symbol"):
        load_bot_specs(tmp_path)


def test_disabled_bots_are_loaded(tmp_path: Path) -> None:
    body = _MINIMAL.replace("enabled: true", "enabled: false")
    _write(tmp_path / "alpha.yml", body)
    specs = load_bot_specs(tmp_path)
    assert len(specs) == 1
    assert specs[0].enabled is False


def test_empty_dir_returns_empty_list(tmp_path: Path) -> None:
    assert load_bot_specs(tmp_path) == []


def test_botspec_is_frozen() -> None:
    spec = BotSpec(
        name="x",
        enabled=True,
        symbol="MNQ",
        strategy_id="orb_5m",
        strategy_params={},
        risk_policy="combine_intraday",
        risk_params={},
        schedule_type="always",
        schedule_params={},
        journal_path=Path("state/x.db"),
    )
    with pytest.raises((AttributeError, TypeError)):
        spec.name = "y"  # type: ignore[misc]


def test_unknown_top_level_key_raises(tmp_path: Path) -> None:
    body = _MINIMAL + "stray: yes\n"
    _write(tmp_path / "alpha.yml", body)
    with pytest.raises(ConfigError, match="stray"):
        load_bot_specs(tmp_path)
