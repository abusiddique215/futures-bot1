"""SignalEvent + SignalSource Protocol — T1."""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from bot.signals.source import SignalEvent, SignalSource


def _ev() -> SignalEvent:
    return SignalEvent(
        received_at=datetime(2026, 5, 23, 14, 0, tzinfo=UTC),
        symbol="NQ",
        side="BUY",
        qty=1,
        limit_price=20_100.0,
        stop_loss=20_070.0,
        take_profit=20_160.0,
        raw_text="BUY NQ @20100 SL=20070 TP=20160",
        source_id="msg-1",
    )


def test_signal_event_is_frozen():
    e = _ev()
    with pytest.raises(FrozenInstanceError):
        e.qty = 999  # type: ignore[misc]


def test_signal_event_requires_tz_aware_timestamp():
    with pytest.raises(TypeError):
        SignalEvent(
            received_at=datetime(2026, 5, 23, 14, 0),  # naive
            symbol="NQ", side="BUY", qty=1,
            limit_price=None, stop_loss=None, take_profit=None,
            raw_text="x", source_id="id",
        )


def test_signal_event_accepts_minimal_fields():
    e = SignalEvent(
        received_at=datetime(2026, 5, 23, 14, 0, tzinfo=UTC),
        symbol="MNQ", side="SELL", qty=2,
        limit_price=None, stop_loss=None, take_profit=None,
        raw_text="", source_id="",
    )
    assert e.side == "SELL"
    assert e.limit_price is None
    assert e.take_profit is None


def test_signal_source_protocol_is_satisfied_by_minimal_class():
    class _Stub:
        async def iter_signals(self) -> AsyncIterator[SignalEvent]:
            if False:
                yield _ev()

    src: SignalSource = _Stub()
    assert isinstance(src, SignalSource)
