"""IBExecutionClient — construction + initial state."""
from __future__ import annotations

from bot.execution.ib_client import IBExecutionClient


def test_ib_client_constructs_with_host_port_client_id() -> None:
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=11)
    assert c.host == "127.0.0.1"
    assert c.port == 7497
    assert c.client_id == 11


def test_ib_client_initial_state_is_empty() -> None:
    c = IBExecutionClient(host="127.0.0.1", port=7497, client_id=11)
    # No IB instance until connect()
    assert c._ib is None
    # No qualified contracts yet
    assert c._contracts == {}
    # Idempotency cache empty
    assert c._recent == {}


def test_ib_client_accepts_ib_factory_for_testing() -> None:
    """Dependency injection: tests pass a fake-IB factory."""
    sentinel = object()
    c = IBExecutionClient(
        host="127.0.0.1", port=7497, client_id=11,
        ib_factory=lambda: sentinel,
    )
    # Factory not invoked until connect()
    assert c._ib is None
    # But stored for later use
    assert c._ib_factory() is sentinel
