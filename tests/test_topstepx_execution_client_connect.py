"""TopstepXExecutionClient.connect() + JWT pre-refresh.

Spec 02 §3.3 connect-flow steps 2-6 + the 22h JWT re-auth from §3.3
"Reconnect strategy" / 00 critical item.

Tests use a FakeProjectX so no real network. JWT pre-refresh is verified
deterministically by passing an injectable `sleep` that fires the
refresh as soon as the background task awaits.
"""
from __future__ import annotations

import asyncio

import pytest

from bot.execution.topstepx_client import (
    JWT_REFRESH_INTERVAL_SECONDS,
    TopstepXExecutionClient,
)
from tests.fakes.fake_projectx import FakeAccount, FakeProjectX


def _make_client(fake: FakeProjectX, **overrides: object) -> TopstepXExecutionClient:
    kwargs: dict[str, object] = {
        "username": "u",
        "api_key": "k",
        "account_name": "acct-A",
        "env": "paper",
        "client_factory": lambda: fake,
    }
    kwargs.update(overrides)
    return TopstepXExecutionClient(**kwargs)  # type: ignore[arg-type]


async def test_connect_authenticates_and_opens_suite() -> None:
    """connect() runs authenticate, looks up the account by name, and
    opens a TradingSuite for the configured symbol."""
    fake = FakeProjectX(accounts=[
        FakeAccount(id=42, name="acct-A"),
        FakeAccount(id=99, name="other"),
    ])
    client = _make_client(fake)

    await client.connect(symbol="MNQ")

    assert fake.authenticate_calls == 1
    assert client.account_id == 42
    assert fake.suite is not None
    assert fake.suite.symbol == "MNQ"


async def test_connect_raises_when_account_name_not_found() -> None:
    """If TOPSTEPX_ACCOUNT_NAME doesn't match any account, fail loudly
    rather than silently picking the first account (which could be the
    wrong rail — Practice vs Combine vs Funded)."""
    fake = FakeProjectX(accounts=[FakeAccount(id=1, name="acct-B")])
    client = _make_client(fake)

    with pytest.raises(RuntimeError, match="acct-A"):
        await client.connect(symbol="MNQ")


async def test_connect_starts_jwt_refresh_task() -> None:
    """The background JWT pre-refresh task is created at connect()
    (NOT in __init__, where there's no running event loop)."""
    fake = FakeProjectX(accounts=[FakeAccount(id=1, name="acct-A")])
    client = _make_client(fake)

    await client.connect(symbol="MNQ")

    assert client._jwt_refresh_task is not None
    assert not client._jwt_refresh_task.done()

    await client.disconnect()


async def test_jwt_refresh_re_authenticates_after_interval() -> None:
    """On each 22h wakeup, the refresh task calls authenticate() again.

    Test uses an injected sleep that yields control immediately on first
    call then cancels the task — so we observe re-auth without a real
    22h wait.
    """
    fake = FakeProjectX(accounts=[FakeAccount(id=1, name="acct-A")])
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        # Yield control so the refresh task can run authenticate(), then
        # raise CancelledError on the next sleep to stop the loop.
        if len(sleeps) >= 2:
            raise asyncio.CancelledError
        await asyncio.sleep(0)

    client = _make_client(fake, sleep=fake_sleep)
    await client.connect(symbol="MNQ")

    # Let the refresh task run.
    assert client._jwt_refresh_task is not None
    try:
        await asyncio.wait_for(client._jwt_refresh_task, timeout=1.0)
    except (asyncio.CancelledError, TimeoutError):
        pass

    # First sleep was for the full 22h interval.
    assert sleeps[0] == JWT_REFRESH_INTERVAL_SECONDS
    # authenticate was called once for connect + at least once for the refresh.
    assert fake.authenticate_calls >= 2


async def test_disconnect_cancels_jwt_refresh_task() -> None:
    """disconnect() must cancel the background refresh task and close
    the suite — otherwise tests leak a dangling Task into asyncio."""
    fake = FakeProjectX(accounts=[FakeAccount(id=1, name="acct-A")])
    client = _make_client(fake)
    await client.connect(symbol="MNQ")
    refresh_task = client._jwt_refresh_task
    assert refresh_task is not None

    await client.disconnect()

    assert refresh_task.cancelled() or refresh_task.done()
    assert fake.suite is not None
    assert fake.suite.disconnect_calls == 1


async def test_jwt_refresh_interval_is_22_hours() -> None:
    """The pre-refresh interval is 22 hours (spec §3.3): JWT lifetime is
    ~24h; we refresh 2h early to absorb clock skew + outages."""
    assert JWT_REFRESH_INTERVAL_SECONDS == 22 * 60 * 60
