"""TopstepXExecutionClient.reconnect — 90s deadline + force-flatten escalation.

Spec 02 §3.3 (reconnect) + §3.7 + 00 critical-item #2.

The 90-second deadline is STRICTER than IB paper's 5 minutes because
TopstepX positions are real money under a trailing MLL that ticks on
unrealized P&L. Every second of unhedged exposure during a disconnect
narrows the survival margin.

On deadline expiry the adapter MUST:
  - set _reconnect_failed = True
  - invoke the force_flatten callback with reason "LIVE_BROKER_DOWN"
  - log CRITICAL
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from bot.execution.topstepx_client import (
    RECONNECT_BACKOFF_SECONDS,
    RECONNECT_DEADLINE_SECONDS,
    TopstepXExecutionClient,
)
from tests.fakes.fake_projectx import FakeAccount, FakeProjectX


def _make_client(
    fake: FakeProjectX,
    *,
    sleep: object | None = None,
    now: object | None = None,
    force_flatten: object | None = None,
) -> TopstepXExecutionClient:
    return TopstepXExecutionClient(
        username="u", api_key="k", account_name="acct-A",
        env="paper", client_factory=lambda: fake,
        sleep=sleep,  # type: ignore[arg-type]
        now=now,  # type: ignore[arg-type]
        force_flatten=force_flatten,  # type: ignore[arg-type]
    )


def test_reconnect_constants_match_spec() -> None:
    """spec §3.3 + 00 #2: deadline is 90 seconds; backoff schedule is
    1, 2, 4, 8, 16, 32, 60 (cap)."""
    assert RECONNECT_DEADLINE_SECONDS == 90
    assert RECONNECT_BACKOFF_SECONDS == (1, 2, 4, 8, 16, 32, 60)


async def test_reconnect_succeeds_on_first_try() -> None:
    """Happy path: connect succeeds the first time — no backoff, no
    force-flatten, deadline never trips."""
    fake = FakeProjectX(accounts=[FakeAccount(id=1, name="acct-A")])
    sleeps: list[float] = []
    flatten_calls: list[str] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)
        await asyncio.sleep(0)

    async def fake_flatten(reason: str) -> None:
        flatten_calls.append(reason)

    client = _make_client(fake, sleep=fake_sleep, force_flatten=fake_flatten)

    await client.reconnect()

    assert client._reconnect_failed is False
    assert flatten_calls == []
    assert sleeps == []  # no backoff needed
    await client.disconnect()


async def test_reconnect_force_flattens_after_90s_deadline() -> None:
    """If connect() keeps failing past 90s wall-clock, the adapter
    MUST set _reconnect_failed and invoke the force_flatten callback.
    """
    fake = FakeProjectX(accounts=[FakeAccount(id=1, name="acct-A")])
    fake.authenticate_error = RuntimeError("network down")

    # Drive 'now' forward deterministically. Each reconnect attempt
    # spends a fake 30s; after 3 attempts we exceed 90s.
    times: list[datetime] = [
        datetime(2026, 5, 22, 14, 0, 0, tzinfo=UTC),
        datetime(2026, 5, 22, 14, 0, 30, tzinfo=UTC),
        datetime(2026, 5, 22, 14, 1, 0, tzinfo=UTC),
        datetime(2026, 5, 22, 14, 1, 31, tzinfo=UTC),  # >90s elapsed
        datetime(2026, 5, 22, 14, 2, 0, tzinfo=UTC),
    ]
    time_idx = [0]

    def fake_now() -> datetime:
        idx = min(time_idx[0], len(times) - 1)
        time_idx[0] += 1
        return times[idx]

    async def fake_sleep(_: float) -> None:
        # Yield so the JWT-refresh background task (if any) can run and
        # we can be cancelled on disconnect.
        await asyncio.sleep(0)

    flatten_calls: list[str] = []

    async def fake_flatten(reason: str) -> None:
        flatten_calls.append(reason)

    client = _make_client(
        fake, sleep=fake_sleep, now=fake_now, force_flatten=fake_flatten,
    )

    await client.reconnect()

    assert client._reconnect_failed is True
    assert flatten_calls == ["LIVE_BROKER_DOWN"]


async def test_reconnect_without_callback_just_sets_flag() -> None:
    """If no force_flatten callback was injected, deadline expiry still
    sets _reconnect_failed = True (the host engine can poll it)."""
    fake = FakeProjectX(accounts=[FakeAccount(id=1, name="acct-A")])
    fake.authenticate_error = RuntimeError("nope")

    start = datetime(2026, 5, 22, 14, 0, 0, tzinfo=UTC)
    times = [start, start + timedelta(seconds=95)]
    idx = [0]

    def fake_now() -> datetime:
        i = min(idx[0], len(times) - 1)
        idx[0] += 1
        return times[i]

    async def fake_sleep(_: float) -> None:
        # Yield so the JWT-refresh background task (if any) can run and
        # we can be cancelled on disconnect.
        await asyncio.sleep(0)

    client = _make_client(fake, sleep=fake_sleep, now=fake_now)

    await client.reconnect()

    assert client._reconnect_failed is True


async def test_reconnect_backoff_progression() -> None:
    """The sleeps follow 1, 2, 4, 8, 16, 32, 60, 60, ... until either
    success or deadline."""
    fake = FakeProjectX(accounts=[FakeAccount(id=1, name="acct-A")])
    fake.authenticate_error = RuntimeError("nope")

    # Make 'now' increment by 100s on the 9th call so deadline triggers
    # after we've observed the first several backoff steps.
    start = datetime(2026, 5, 22, 14, 0, 0, tzinfo=UTC)
    call_count = [0]

    def fake_now() -> datetime:
        n = call_count[0]
        call_count[0] += 1
        if n < 8:
            return start
        return start + timedelta(seconds=200)

    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)
        await asyncio.sleep(0)

    client = _make_client(fake, sleep=fake_sleep, now=fake_now)
    await client.reconnect()

    # Verify the backoff prefix matches the schedule.
    assert sleeps[:7] == [1, 2, 4, 8, 16, 32, 60]
