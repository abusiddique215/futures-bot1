"""BotSpec frozen dataclass + YAML loader for `config/bots/*.yml`.

Each YAML file in the bots directory describes one bot: name, symbol,
strategy id + params, risk policy id + params, schedule id + params, and
the per-bot SQLite journal path. The loader validates the directory as a
whole (no duplicate names; no duplicate journal paths) and raises
`ConfigError` with the offending file + reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import yaml

RiskPolicyId = Literal["combine_intraday", "efa_standard", "efa_consistency"]
ScheduleId = Literal["always", "market_hours", "custom_windows"]

_REQUIRED: Final[frozenset[str]] = frozenset({
    "name", "enabled", "symbol", "strategy_id", "strategy_params",
    "risk_policy", "risk_params", "schedule_type", "schedule_params",
    "journal_path",
})


class ConfigError(ValueError):
    """Raised when a BotSpec YAML is malformed or the directory has conflicts."""


@dataclass(frozen=True)
class BotSpec:
    """One bot's full configuration. Sorted by `name` in the registry's view."""

    name: str
    enabled: bool
    symbol: str
    strategy_id: str
    strategy_params: dict[str, Any]
    risk_policy: RiskPolicyId
    risk_params: dict[str, Any]
    schedule_type: ScheduleId
    schedule_params: dict[str, Any]
    journal_path: Path


def _parse_one(path: Path) -> BotSpec:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: invalid YAML — {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top-level YAML must be a mapping")

    keys = set(raw.keys())
    missing = _REQUIRED - keys
    if missing:
        raise ConfigError(f"{path}: missing required field(s): {sorted(missing)}")
    extra = keys - _REQUIRED
    if extra:
        raise ConfigError(f"{path}: unknown field(s): {sorted(extra)}")

    try:
        return BotSpec(
            name=str(raw["name"]),
            enabled=bool(raw["enabled"]),
            symbol=str(raw["symbol"]),
            strategy_id=str(raw["strategy_id"]),
            strategy_params=dict(raw["strategy_params"] or {}),
            risk_policy=raw["risk_policy"],
            risk_params=dict(raw["risk_params"] or {}),
            schedule_type=raw["schedule_type"],
            schedule_params=dict(raw["schedule_params"] or {}),
            journal_path=Path(str(raw["journal_path"])),
        )
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{path}: malformed value — {e}") from e


def load_bot_specs(directory: Path) -> list[BotSpec]:
    """Glob `*.yml` under `directory`, parse each, validate uniqueness.

    Returns the specs sorted by `name`. Raises `ConfigError` on the first
    structural problem (missing field, unknown field, duplicate name,
    duplicate journal_path).
    """
    files = sorted(directory.glob("*.yml"))
    specs = [_parse_one(p) for p in files]

    seen_names: set[str] = set()
    seen_journals: set[Path] = set()
    for spec in specs:
        if spec.name in seen_names:
            raise ConfigError(f"duplicate bot name across files: {spec.name!r}")
        if spec.journal_path in seen_journals:
            raise ConfigError(
                f"duplicate journal_path across files: {spec.journal_path}"
            )
        seen_names.add(spec.name)
        seen_journals.add(spec.journal_path)

    return sorted(specs, key=lambda s: s.name)
