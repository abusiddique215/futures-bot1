"""Shared pytest fixtures."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest


@pytest.fixture
def utc_now() -> datetime:
    """A fixed, timezone-aware UTC timestamp for tests that need one."""
    return datetime(2026, 5, 22, 14, 30, 0, tzinfo=UTC)
