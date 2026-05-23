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
