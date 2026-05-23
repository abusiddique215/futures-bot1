"""iCloud-tree startup check.

Emits a WARN telemetry alert if the project is checked out under macOS
iCloud Drive (`~/Library/Mobile Documents/...`). SQLite WAL is unsafe on
iCloud (sync layer corrupts -wal / -shm sidecars under contention) and
LaunchAgents stored on iCloud may not exist on disk when launchd loads
them on login. We WARN rather than block — dev/backtest on iCloud is
inconvenient but not fatal, and the operator may have reason to keep the
tree there.

Spec: 07-config-and-deploy.md §3.6.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class _Bus(Protocol):
    """Minimal telemetry surface — matches bot.observability.bus.TelemetryBus."""
    def alert(self, kind: str, **kw: object) -> None: ...


_ICLOUD_MARKER = "Mobile Documents"


def check_icloud_tree(cwd: Path, bus: _Bus | None) -> bool:
    """Return True iff `cwd` lives inside macOS iCloud Drive. Emit WARN if so.

    The marker we look for is the literal directory name "Mobile Documents"
    anywhere in the resolved path. macOS uses that name for every iCloud
    container regardless of the user-facing folder ("iCloud Drive",
    "Documents", "Desktop").
    """
    is_icloud = _ICLOUD_MARKER in cwd.parts
    if is_icloud and bus is not None:
        bus.alert(
            "ICLOUD_TREE_WARNING",
            severity="WARN",
            reason=(
                f"Project tree {str(cwd)!r} is under iCloud Drive "
                f"('Mobile Documents'). SQLite WAL is unsafe here — the iCloud "
                f"sync layer can corrupt -wal/-shm sidecars under contention, "
                f"and LaunchAgents stored on iCloud may be missing when launchd "
                f"loads them. Move the project to local disk before live install."
            ),
            cwd=str(cwd),
        )
    return is_icloud
