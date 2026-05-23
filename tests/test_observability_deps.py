"""Plan 7 T1: smoke-test that observability deps are importable.

These three deps (loguru, telegram, aiosqlite) plus httpx (transitive for
telegram-bot but used directly by TelegramAlerter in T6) are added in T1.
This test fails fast in CI if a deploy step forgets to `pip install -e .`.
"""
from __future__ import annotations


def test_loguru_importable() -> None:
    from loguru import logger
    assert logger is not None


def test_telegram_importable() -> None:
    import telegram
    # ge 21.4 per pyproject; the lib also vendors py.typed
    assert tuple(int(p) for p in telegram.__version__.split(".")[:2]) >= (21, 4)


def test_aiosqlite_importable() -> None:
    import aiosqlite
    assert tuple(int(p) for p in aiosqlite.__version__.split(".")[:2]) >= (0, 20)


def test_httpx_importable() -> None:
    import httpx
    assert tuple(int(p) for p in httpx.__version__.split(".")[:2]) >= (0, 27)
