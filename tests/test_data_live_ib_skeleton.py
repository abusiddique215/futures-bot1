"""IBLiveBarStream skeleton. Spec 01 §3.3.

Plan 2 ships only the class shape + constructor + a 'not implemented' connect.
Full ib_async integration + reconnect logic lives in Plan 6.
"""
from __future__ import annotations

import pytest


def test_ib_live_bar_stream_constructs() -> None:
    from bot.data.live_ib import IBLiveBarStream
    s = IBLiveBarStream(host="127.0.0.1", port=4002, client_id=7)
    assert s.host == "127.0.0.1"
    assert s.port == 4002
    assert s.client_id == 7


@pytest.mark.asyncio
async def test_connect_raises_not_implemented_in_plan_2() -> None:
    """Plan 2 ships a stub; Plan 6 implements the real connect()."""
    from bot.data.live_ib import IBLiveBarStream
    s = IBLiveBarStream(host="127.0.0.1", port=4002, client_id=7)
    with pytest.raises(NotImplementedError, match="Plan 6"):
        await s.connect()
