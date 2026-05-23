"""Plan 9 T1: smoke-test that runtime deps are importable.

`python-dotenv` is added in T1 to power `load_secrets()` (T2). This test
fails fast in CI if a deploy step forgets to `pip install -e .`.
"""
from __future__ import annotations


def test_dotenv_importable() -> None:
    from dotenv import dotenv_values, load_dotenv

    assert callable(load_dotenv)
    assert callable(dotenv_values)
