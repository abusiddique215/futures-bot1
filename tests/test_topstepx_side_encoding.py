"""Required defensive unit test: TopstepX side encoding is inverted.

Spec 02 §3.4. This test is non-negotiable per Plan 8 T2 — every PR
touching topstepx_client.py MUST keep it green. If the values flip,
every order placed against a real Topstep account silently loses money.

Search term: SIDE_BUY=0 footgun.
"""
from __future__ import annotations

import pytest

from bot.execution.topstepx_constants import (
    SIDE_BUY,
    SIDE_SELL,
    topstepx_side,
)


def test_topstepx_side_encoding_is_inverted_from_intuition() -> None:
    """SIDE_BUY MUST be 0; SIDE_SELL MUST be 1.

    DO NOT change these values. TopstepX inverts the conventional 0/1
    encoding (0=Bid=BUY, 1=Ask=SELL). The intuitive reading (0=sell,
    1=buy) is exactly wrong. A wrong value here = silent real-money loss.
    """
    assert SIDE_BUY == 0, "TopstepX: 0 is BUY (Bid). Do not change."
    assert SIDE_SELL == 1, "TopstepX: 1 is SELL (Ask). Do not change."


def test_topstepx_side_mapper_returns_zero_for_buy() -> None:
    assert topstepx_side("BUY") == 0


def test_topstepx_side_mapper_returns_one_for_sell() -> None:
    assert topstepx_side("SELL") == 1


def test_topstepx_side_constants_are_distinct() -> None:
    """Belt-and-braces: catch a refactor that collapses both to the same value."""
    assert SIDE_BUY != SIDE_SELL


def test_topstepx_side_rejects_unknown_side() -> None:
    """Defensive: anything outside BUY/SELL raises rather than silently
    falling through to 0 (which would mean BUY)."""
    with pytest.raises(KeyError):
        topstepx_side("HOLD")  # type: ignore[arg-type]
