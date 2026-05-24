"""ProfileStore + ProfileOverlay — per-user customization foundation.

Each user has a profile directory under `state/profiles/<name>/`:
  overrides.yaml   — `{bot_name: {strategy_params|risk_params|schedule_params: {key: value}}}`
  prefs.json       — UI preferences (theme, refresh rate, …)
  history.jsonl    — append-only audit log of every set_override call

ProfileStore:
  - File-system backed; safe across threads via `fcntl.flock` (POSIX advisory
    lock on a per-profile `.lock` file wrapped around read-modify-write).
  - Auto-creates the "default" profile on first instantiation so callers never
    encounter a "missing default" footgun.
  - history.jsonl is append-only; deletion of a profile removes the directory
    (including the audit trail). Operators who want to retain history should
    archive the directory before deletion.

ProfileOverlay:
  - Pure function. `apply(spec, overrides) -> new BotSpec`.
  - Deep-merges into strategy_params / risk_params / schedule_params.
  - Validates the result by running the registry factory (raises
    ProfileValidationError on bad value — saves the frontend from having to
    duplicate the validation rules).
  - `spec_hash(spec)` returns a stable hex digest so callers can diff before
    + after to decide which bots to restart on hot-swap.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from bot.runtime.fleet.registry import BotRegistry
from bot.runtime.fleet.spec import BotSpec

_VALID_BLOCKS = frozenset({"strategy_params", "risk_params", "schedule_params"})


class ProfileNotFoundError(LookupError):
    """Raised when an operation references a profile that doesn't exist."""


class ProfileValidationError(ValueError):
    """Raised when an overlay produces an invalid BotSpec."""


class ProfileStore:
    """File-system backed per-user profile storage.

    Parameters
    ----------
    root
        Directory holding one subdirectory per profile. Created if missing.
        The "default" profile is auto-created on first construction.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        # Auto-create default so every operation has a baseline.
        default_dir = self._root / "default"
        if not default_dir.exists():
            self._init_profile_dir(default_dir)

    # ---- lifecycle ----

    def list_profiles(self) -> list[str]:
        return sorted(
            p.name for p in self._root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    def create(self, name: str, *, fork_from: str = "default") -> None:
        """Create a new profile, copying overrides + prefs from `fork_from`.

        Raises FileExistsError if `name` already exists, ProfileNotFoundError
        if `fork_from` doesn't exist.
        """
        target = self._root / name
        if target.exists():
            raise FileExistsError(f"profile already exists: {name!r}")
        source = self._root / fork_from
        if not source.exists():
            raise ProfileNotFoundError(f"fork source not found: {fork_from!r}")
        # Copy overrides + prefs only; history starts fresh for the new profile.
        target.mkdir(parents=True)
        for fname in ("overrides.yaml", "prefs.json"):
            src = source / fname
            if src.exists():
                shutil.copy2(src, target / fname)
        # Always seed an empty history so subsequent appends find the file.
        (target / "history.jsonl").write_text("", encoding="utf-8")

    def delete(self, name: str) -> None:
        """Remove a profile directory. Refuses to delete "default"."""
        if name == "default":
            raise ValueError("cannot delete the default profile")
        target = self._root / name
        if not target.exists():
            raise ProfileNotFoundError(f"profile not found: {name!r}")
        shutil.rmtree(target)

    # ---- overrides ----

    def get_overrides(self, name: str) -> dict[str, dict[str, dict[str, Any]]]:
        """Return the profile's overrides dict.

        Shape: `{bot_name: {block: {key: value}}}`. Missing file → empty dict.
        """
        self._require(name)
        path = self._overrides_path(name)
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ProfileValidationError(
                f"{path}: top-level overrides must be a mapping",
            )
        return data

    def set_override(
        self,
        name: str,
        bot: str,
        block: str,
        key: str,
        value: Any,
        *,
        user: str,
    ) -> None:
        """Set one override key + append an audit row.

        Concurrency: serializes against other writers via `fcntl.flock` on a
        per-profile `.lock` sentinel. Reads inside the critical section see
        a consistent overrides.yaml.
        """
        self._require(name)
        if block not in _VALID_BLOCKS:
            raise ProfileValidationError(
                f"unknown block {block!r}; expected one of {sorted(_VALID_BLOCKS)}",
            )
        lock_path = self._root / name / ".lock"
        # Touch the lock file. flock needs an actual fd.
        lock_path.touch(exist_ok=True)
        with lock_path.open("r+") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                overrides = self.get_overrides(name)
                before = (
                    overrides.get(bot, {}).get(block, {}).get(key)
                )
                bot_block = overrides.setdefault(bot, {}).setdefault(block, {})
                bot_block[key] = value
                self._write_overrides(name, overrides)
                self._append_history(name, {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "user": user,
                    "bot": bot,
                    "block": block,
                    "key": key,
                    "before": before,
                    "after": value,
                })
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

    # ---- prefs ----

    def get_prefs(self, name: str) -> dict[str, Any]:
        self._require(name)
        path = self._prefs_path(name)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def set_prefs(self, name: str, prefs: dict[str, Any]) -> None:
        self._require(name)
        self._prefs_path(name).write_text(
            json.dumps(prefs, indent=2, sort_keys=True), encoding="utf-8",
        )

    # ---- history ----

    def get_history(self, name: str) -> list[dict[str, Any]]:
        self._require(name)
        path = self._history_path(name)
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip garbled lines rather than corrupting the whole history.
                continue
        return rows

    # ---- internals ----

    def _require(self, name: str) -> None:
        if not (self._root / name).exists():
            raise ProfileNotFoundError(f"profile not found: {name!r}")

    def _init_profile_dir(self, target: Path) -> None:
        target.mkdir(parents=True)
        (target / "overrides.yaml").write_text("{}\n", encoding="utf-8")
        (target / "prefs.json").write_text("{}\n", encoding="utf-8")
        (target / "history.jsonl").write_text("", encoding="utf-8")

    def _overrides_path(self, name: str) -> Path:
        return self._root / name / "overrides.yaml"

    def _prefs_path(self, name: str) -> Path:
        return self._root / name / "prefs.json"

    def _history_path(self, name: str) -> Path:
        return self._root / name / "history.jsonl"

    def _write_overrides(
        self, name: str, overrides: dict[str, dict[str, dict[str, Any]]],
    ) -> None:
        path = self._overrides_path(name)
        path.write_text(
            yaml.safe_dump(overrides, sort_keys=True), encoding="utf-8",
        )

    def _append_history(self, name: str, row: dict[str, Any]) -> None:
        with self._history_path(name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")


# ---------- ProfileOverlay --------------------------------------------------

def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return a NEW dict that is `base` deep-merged with `overlay`.

    Scalar overlay values replace base values; dict overlay values are merged
    recursively. Used per param-block (one level of nesting in practice).
    """
    out: dict[str, Any] = {**base}
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class ProfileOverlay:
    """Pure function namespace — never instantiated."""

    # Reusable registry for validation. Construction is cheap (no I/O).
    _registry: BotRegistry = BotRegistry()

    @classmethod
    def apply(
        cls, spec: BotSpec, overrides: dict[str, Any],
    ) -> BotSpec:
        """Return a new BotSpec with `overrides` merged over the param blocks.

        `overrides` shape: `{"strategy_params": {...}, "risk_params": {...},
        "schedule_params": {...}}`. Unknown blocks raise
        ProfileValidationError. The result is validated by calling the
        existing registry factories so a bad overlay value is rejected at
        apply time rather than surfacing at the next bar.
        """
        for block in overrides:
            if block not in _VALID_BLOCKS:
                raise ProfileValidationError(
                    f"unknown block {block!r}; expected one of "
                    f"{sorted(_VALID_BLOCKS)}",
                )

        new_strategy = _deep_merge(
            dict(spec.strategy_params), overrides.get("strategy_params", {}),
        )
        new_risk = _deep_merge(
            dict(spec.risk_params), overrides.get("risk_params", {}),
        )
        new_schedule = _deep_merge(
            dict(spec.schedule_params), overrides.get("schedule_params", {}),
        )

        merged = replace(
            spec,
            strategy_params=new_strategy,
            risk_params=new_risk,
            schedule_params=new_schedule,
        )

        # Validate by running each factory. The registry raises on bad values
        # (e.g. ORB range_minutes outside 1..30). We surface as
        # ProfileValidationError so callers can map to HTTP 400.
        try:
            sid = merged.strategy_id
            if sid in cls._registry._strategies:
                cls._registry._strategies[sid](dict(merged.strategy_params))
            pid = merged.risk_policy
            if pid in cls._registry._policies:
                cls._registry._policies[pid](dict(merged.risk_params))
            sched_id = merged.schedule_type
            if sched_id in cls._registry._schedules:
                cls._registry._schedules[sched_id](
                    dict(merged.schedule_params),
                )
        except Exception as e:
            raise ProfileValidationError(
                f"overlay produces invalid BotSpec: {e}",
            ) from e
        return merged

    @staticmethod
    def spec_hash(spec: BotSpec) -> str:
        """Stable hex digest of the spec's overrideable fields.

        Used by hot-swap to decide which bots need restart on profile
        activate. Hashes only the fields a profile can change — name,
        enabled, symbol, strategy_id, etc. are excluded so a no-op overlay
        produces the same hash.
        """
        payload = {
            "strategy_params": spec.strategy_params,
            "risk_params": spec.risk_params,
            "schedule_params": spec.schedule_params,
        }
        # default=str handles datetime.time objects in schedule_params.
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
