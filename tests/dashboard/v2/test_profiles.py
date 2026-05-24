"""Tests for ProfileStore + ProfileOverlay (Plan 23 T1).

Two surfaces under test:

* ProfileStore — filesystem-backed per-user profile storage:
    state/profiles/<name>/{overrides.yaml,prefs.json,history.jsonl}.
  Create / fork / delete / read / write / audit. Concurrent-write safe
  via fcntl.flock (POSIX).

* ProfileOverlay — pure function: BotSpec + overrides dict → new BotSpec.
  Deep-merges into strategy_params / risk_params / schedule_params and
  rebuilds the spec via dataclasses.replace (BotSpec is frozen).
"""
from __future__ import annotations

import json
import threading
from datetime import time
from pathlib import Path

import pytest

from bot.dashboard.v2.profiles import (
    ProfileNotFoundError,
    ProfileOverlay,
    ProfileStore,
    ProfileValidationError,
)
from bot.runtime.fleet.spec import BotSpec


def _spec(name: str = "alpha") -> BotSpec:
    return BotSpec(
        name=name,
        enabled=True,
        symbol="MNQH26",
        strategy_id="orb_5m",
        strategy_params={
            "symbol": "MNQ",
            "range_minutes": 5,
            "atr_mult": 1.0,
            "tp_r_multiple": 2.0,
        },
        risk_policy="efa_standard",
        risk_params={"mll_amount": 2000.0},
        schedule_type="market_hours",
        schedule_params={"open_ct": time(8, 30), "close_ct": time(15, 10)},
        journal_path=Path(f"state/{name}.db"),
    )


# ---------- ProfileStore ----------------------------------------------------

def test_default_profile_auto_created_on_first_access(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    assert store.list_profiles() == ["default"]
    overrides = store.get_overrides("default")
    assert overrides == {}


def test_create_fork_from_default(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    store.create("alice")
    assert sorted(store.list_profiles()) == ["alice", "default"]
    assert store.get_overrides("alice") == {}


def test_create_fork_carries_overrides(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    store.set_override(
        "default", bot="alpha", block="strategy_params",
        key="range_minutes", value=10, user="tester",
    )
    store.create("bob", fork_from="default")
    overrides = store.get_overrides("bob")
    assert overrides == {"alpha": {"strategy_params": {"range_minutes": 10}}}


def test_create_duplicate_raises(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    store.create("alice")
    with pytest.raises(FileExistsError):
        store.create("alice")


def test_create_unknown_fork_source_raises(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    with pytest.raises(ProfileNotFoundError):
        store.create("alice", fork_from="ghost")


def test_delete_profile_removes_dir(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    store.create("alice")
    store.delete("alice")
    assert "alice" not in store.list_profiles()


def test_delete_default_refused(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    with pytest.raises(ValueError, match="default"):
        store.delete("default")


def test_set_and_get_override_roundtrip(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    store.set_override(
        "default", bot="alpha", block="strategy_params",
        key="range_minutes", value=10, user="tester",
    )
    overrides = store.get_overrides("default")
    assert overrides == {"alpha": {"strategy_params": {"range_minutes": 10}}}


def test_set_override_appends_history(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    store.set_override(
        "default", bot="alpha", block="risk_params",
        key="mll_amount", value=2500.0, user="alice",
    )
    history = store.get_history("default")
    assert len(history) == 1
    row = history[0]
    assert row["bot"] == "alpha"
    assert row["block"] == "risk_params"
    assert row["key"] == "mll_amount"
    assert row["before"] is None
    assert row["after"] == 2500.0
    assert row["user"] == "alice"
    assert "timestamp" in row


def test_set_override_records_before_after_on_change(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    store.set_override(
        "default", "alpha", "strategy_params", "range_minutes", 5, user="alice",
    )
    store.set_override(
        "default", "alpha", "strategy_params", "range_minutes", 10, user="bob",
    )
    history = store.get_history("default")
    assert history[-1]["before"] == 5
    assert history[-1]["after"] == 10
    assert history[-1]["user"] == "bob"


def test_overrides_isolated_across_profiles(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    store.create("alice")
    store.set_override(
        "alice", "alpha", "strategy_params", "range_minutes", 15, user="alice",
    )
    assert store.get_overrides("default") == {}
    assert store.get_overrides("alice") == {
        "alpha": {"strategy_params": {"range_minutes": 15}}
    }


def test_get_prefs_default(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    prefs = store.get_prefs("default")
    assert isinstance(prefs, dict)


def test_set_prefs_roundtrip(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    store.set_prefs("default", {"theme": "dark", "refresh_seconds": 2})
    assert store.get_prefs("default") == {"theme": "dark", "refresh_seconds": 2}


def test_concurrent_writes_do_not_corrupt(tmp_path: Path) -> None:
    """Two threads write different keys; both end up in the YAML."""
    store = ProfileStore(tmp_path, current_user="default")

    def writer(key: str, value: int) -> None:
        store.set_override(
            "default", "alpha", "strategy_params", key, value, user="t",
        )

    threads = [
        threading.Thread(target=writer, args=(f"k{i}", i))
        for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = store.get_overrides("default")["alpha"]["strategy_params"]
    for i in range(8):
        assert final[f"k{i}"] == i


def test_history_uses_jsonl_one_per_line(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    store.set_override("default", "a", "strategy_params", "x", 1, user="t")
    store.set_override("default", "a", "strategy_params", "y", 2, user="t")
    raw = (tmp_path / "default" / "history.jsonl").read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) == 2
    for ln in lines:
        assert isinstance(json.loads(ln), dict)


def test_get_history_for_unknown_profile_raises(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    with pytest.raises(ProfileNotFoundError):
        store.get_history("ghost")


def test_set_override_for_unknown_profile_raises(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, current_user="default")
    with pytest.raises(ProfileNotFoundError):
        store.set_override("ghost", "a", "strategy_params", "x", 1, user="t")


# ---------- ProfileOverlay --------------------------------------------------

def test_overlay_apply_empty_returns_same_values(tmp_path: Path) -> None:
    spec = _spec()
    out = ProfileOverlay.apply(spec, overrides={})
    assert out.strategy_params == spec.strategy_params
    assert out.risk_params == spec.risk_params
    assert out.schedule_params == spec.schedule_params


def test_overlay_changes_strategy_param(tmp_path: Path) -> None:
    spec = _spec()
    out = ProfileOverlay.apply(
        spec, overrides={"strategy_params": {"range_minutes": 10}},
    )
    assert out.strategy_params["range_minutes"] == 10
    # Other keys preserved.
    assert out.strategy_params["atr_mult"] == 1.0


def test_overlay_returns_new_frozen_spec(tmp_path: Path) -> None:
    spec = _spec()
    out = ProfileOverlay.apply(
        spec, overrides={"strategy_params": {"range_minutes": 7}},
    )
    assert out is not spec
    assert spec.strategy_params["range_minutes"] == 5  # original untouched
    # Frozen dataclass — cannot mutate.
    with pytest.raises(AttributeError):
        out.strategy_params = {}  # type: ignore[misc]


def test_overlay_deep_merge_preserves_existing_block_keys(tmp_path: Path) -> None:
    """Strategy_params keys not mentioned in the overlay are preserved."""
    spec = _spec()
    out = ProfileOverlay.apply(
        spec,
        overrides={"strategy_params": {"tp_r_multiple": 3.0}},
    )
    # Overridden.
    assert out.strategy_params["tp_r_multiple"] == 3.0
    # Preserved.
    assert out.strategy_params["range_minutes"] == 5
    assert out.strategy_params["atr_mult"] == 1.0


def test_overlay_rejects_invalid_block(tmp_path: Path) -> None:
    spec = _spec()
    with pytest.raises(ProfileValidationError):
        ProfileOverlay.apply(
            spec, overrides={"unknown_block": {"x": 1}},
        )


def test_overlay_validates_strategy_factory(tmp_path: Path) -> None:
    """An overlay that produces an invalid strategy is rejected."""
    spec = _spec()
    with pytest.raises(ProfileValidationError):
        # range_minutes must be 1..30 per ORBProfile.
        ProfileOverlay.apply(
            spec, overrides={"strategy_params": {"range_minutes": -1}},
        )


def test_overlay_hash_stable_for_equal_specs(tmp_path: Path) -> None:
    spec = _spec()
    h1 = ProfileOverlay.spec_hash(spec)
    h2 = ProfileOverlay.spec_hash(spec)
    assert h1 == h2


def test_overlay_hash_changes_on_override(tmp_path: Path) -> None:
    spec = _spec()
    h_before = ProfileOverlay.spec_hash(spec)
    out = ProfileOverlay.apply(
        spec, overrides={"strategy_params": {"range_minutes": 10}},
    )
    h_after = ProfileOverlay.spec_hash(out)
    assert h_before != h_after
