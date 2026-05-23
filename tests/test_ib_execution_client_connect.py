"""IBExecutionClient.connect — async connect + MNQ contract resolution."""
from __future__ import annotations

from bot.execution.ib_client import IBExecutionClient
from tests.fakes.fake_ib import FakeIB


async def test_connect_invokes_connectasync_with_constructor_params() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="1.2.3.4", port=7497, client_id=42,
                          ib_factory=lambda: fake)
    await c.connect()
    assert fake.connect_calls == [("1.2.3.4", 7497, 42)]
    assert fake.connected is True


async def test_connect_resolves_mnq_front_month_contract() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    # MNQ contract qualified and cached.
    assert "MNQ" in c._contracts
    mnq = c._contracts["MNQ"]
    assert mnq.symbol == "MNQ"
    assert mnq.exchange == "CME"
    # FakeIB stamps conId=12345 on qualified contracts.
    assert mnq.conId == 12345


async def test_connect_stores_ib_instance() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    assert c._ib is None
    await c.connect()
    assert c._ib is fake


async def test_disconnect_calls_ib_disconnect() -> None:
    fake = FakeIB()
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=1,
                          ib_factory=lambda: fake)
    await c.connect()
    await c.disconnect()
    assert fake.connected is False
