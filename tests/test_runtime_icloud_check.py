"""Plan 9 T4: iCloud-tree warning at startup.

SQLite WAL mode is unsafe on iCloud Drive (the sync layer occasionally
corrupts -wal / -shm sidecars), and LaunchAgents in an iCloud-tree may not
exist on disk when launchd tries to load them. Operator should move the
project to local disk before live install. The check is WARN, not ERROR —
operator decides; dev/backtest on iCloud is annoying but not fatal.

This module's `check_icloud_tree(cwd, alerter)` returns True iff the path
contains "Mobile Documents" and emits a WARN-level telemetry alert.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bot.runtime.icloud_check import check_icloud_tree


class _FakeBus:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, dict[str, object]]] = []

    def alert(self, kind: str, **kw: object) -> None:
        self.alerts.append((kind, kw))


def test_icloud_path_triggers_warning() -> None:
    bus = _FakeBus()
    cwd = Path("/Users/alice/Library/Mobile Documents/com~apple~CloudDocs/project")
    is_icloud = check_icloud_tree(cwd, bus)
    assert is_icloud is True
    assert len(bus.alerts) == 1
    kind, payload = bus.alerts[0]
    assert kind == "ICLOUD_TREE_WARNING"
    assert payload.get("severity") == "WARN"
    # Message should explain WHY (SQLite WAL + LaunchAgent).
    reason = str(payload.get("reason", ""))
    assert "iCloud" in reason or "Mobile Documents" in reason


def test_local_disk_path_no_warning() -> None:
    bus = _FakeBus()
    cwd = Path("/Users/alice/projects/topstep-bot")
    is_icloud = check_icloud_tree(cwd, bus)
    assert is_icloud is False
    assert bus.alerts == []


def test_alternate_icloud_paths_detected() -> None:
    """Any path containing 'Mobile Documents' is iCloud-tree, regardless of
    the trailing iCloudDrive folder name (varies by macOS version)."""
    bus = _FakeBus()
    cwd = Path("/Users/bob/Library/Mobile Documents/com~apple~Preview/topstep")
    is_icloud = check_icloud_tree(cwd, bus)
    assert is_icloud is True
    assert bus.alerts[0][0] == "ICLOUD_TREE_WARNING"


def test_bus_without_alert_method_does_not_crash() -> None:
    """A None bus is tolerated — log-only mode for very-early startup."""
    cwd = Path("/Users/alice/Library/Mobile Documents/com~apple~CloudDocs/project")
    # Should not raise — function tolerates None bus.
    result = check_icloud_tree(cwd, None)
    assert result is True


@pytest.mark.parametrize("p", [
    "/tmp",
    "/Volumes/External/projects",
    "/opt/topstep-bot",
])
def test_non_icloud_paths_no_warning(p: str) -> None:
    bus = _FakeBus()
    assert check_icloud_tree(Path(p), bus) is False
    assert bus.alerts == []
