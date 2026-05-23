"""IBExecutionClient — reconnect with exponential backoff + 5-minute deadline."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from bot.execution.ib_client import IBExecutionClient
from tests.fakes.fake_ib import FakeIB


class _ClockedFakeIB(FakeIB):
    """FakeIB whose connectAsync fails N times before succeeding."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_n_times = 0
        self._attempts = 0

    async def connectAsync(self, host: str, port: int, clientId: int) -> None:
        self._attempts += 1
        if self._attempts <= self.fail_n_times:
            raise ConnectionError(f"simulated failure #{self._attempts}")
        self.connect_calls.append((host, port, clientId))
        self.connected = True


async def test_reconnect_succeeds_after_two_failures() -> None:
    """Backoff schedule [1, 2, 4, ...]; attempt 3 succeeds — slept = [1, 2]."""
    fake = _ClockedFakeIB()
    fake.fail_n_times = 2

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake, sleep=fake_sleep)
    await c.reconnect()

    assert slept == [1, 2]
    assert fake.connected is True
    assert c._reconnect_failed is False


async def test_reconnect_gives_up_after_5_minute_deadline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After 5 minutes elapse without success, give up + emit telemetry alert."""
    fake = _ClockedFakeIB()
    fake.fail_n_times = 10_000  # never succeeds

    slept: list[float] = []
    t = [datetime(2026, 5, 22, 14, 30, tzinfo=UTC)]

    def fake_now() -> datetime:
        return t[0]

    async def advancing_sleep(seconds: float) -> None:
        slept.append(seconds)
        t[0] = t[0] + timedelta(seconds=seconds)

    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake,
                          sleep=advancing_sleep, now=fake_now)

    with caplog.at_level(logging.ERROR, logger="bot.execution.ib_client"):
        await c.reconnect()

    assert sum(slept) >= 300
    assert fake.connected is False
    assert c._reconnect_failed is True
    # Telemetry alert: structured ERROR log
    assert any("reconnect" in r.message.lower() for r in caplog.records)


async def test_reconnect_backoff_schedule_caps_at_60s() -> None:
    """1, 2, 4, 8, 16, 32, 60, 60, 60, …"""
    fake = _ClockedFakeIB()
    fake.fail_n_times = 9  # 10th attempt succeeds

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake, sleep=fake_sleep)
    await c.reconnect()

    expected_prefix = [1, 2, 4, 8, 16, 32, 60, 60, 60]
    assert slept == expected_prefix


async def test_reconnect_factory_returns_fresh_ib_on_each_attempt() -> None:
    """Each reconnect attempt builds a fresh IB instance through the factory."""
    created: list[Any] = []

    def factory() -> Any:
        f = _ClockedFakeIB()
        f.fail_n_times = 0  # immediate success on first call
        created.append(f)
        return f

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=factory, sleep=fake_sleep)
    await c.reconnect()
    # First reconnect with backoff
    assert len(created) == 1
    assert created[0].connected is True
