"""Smoke test: verify ib_async 2.1.0 API surface is intact.

Plan 6 was specced against ib_async 1.x; we install 2.1.0. Before building
IBExecutionClient on top of these APIs, assert they are present and have the
signatures we rely on. If any method is renamed in a future bump, this test
fails loudly with a pointer to the spot in Plan 6 that needs adapting.

This test does NOT touch the network — it only inspects class attributes /
signatures on instantiated objects.
"""
from __future__ import annotations

import inspect

from ib_async import IB, Future, LimitOrder, MarketOrder
from ib_async.order import BracketOrder


def test_core_imports_present() -> None:
    """Imports we rely on in Plan 6 must resolve."""
    # MarketOrder / LimitOrder are constructible with action + qty
    mo = MarketOrder(action="BUY", totalQuantity=1)
    assert mo.action == "BUY"
    assert mo.totalQuantity == 1

    lo = LimitOrder(action="SELL", totalQuantity=2, lmtPrice=100.0)
    assert lo.action == "SELL"
    assert lo.totalQuantity == 2
    assert lo.lmtPrice == 100.0

    # Future contract for MNQ
    f = Future(symbol="MNQ", exchange="CME")
    assert f.symbol == "MNQ"
    assert f.exchange == "CME"


def test_ib_connectasync_signature() -> None:
    """ib.connectAsync(host, port, clientId) — params unchanged from 1.x."""
    sig = inspect.signature(IB.connectAsync)
    params = sig.parameters
    assert "host" in params
    assert "port" in params
    assert "clientId" in params


def test_ib_has_required_methods() -> None:
    """The eight surfaces IBExecutionClient + IBLiveBarStream rely on."""
    ib = IB()
    assert hasattr(ib, "connectAsync")
    assert hasattr(ib, "disconnect")
    assert hasattr(ib, "qualifyContractsAsync")
    assert hasattr(ib, "placeOrder")
    assert hasattr(ib, "cancelOrder")
    assert hasattr(ib, "bracketOrder")
    assert hasattr(ib, "reqRealTimeBars")
    assert hasattr(ib, "positions")
    assert hasattr(ib, "openOrders")
    assert hasattr(ib, "accountSummary")


def test_bracketorder_returns_3_tuple_shape() -> None:
    """BracketOrder is a NamedTuple (parent, takeProfit, stopLoss).

    We rely on this shape in Task 5 to set orderRef on each leg.
    """
    assert BracketOrder._fields == ("parent", "takeProfit", "stopLoss")


def test_reqrealtimebars_signature() -> None:
    """reqRealTimeBars(contract, barSize, whatToShow, useRTH) — needed in Task 9."""
    ib = IB()
    sig = inspect.signature(ib.reqRealTimeBars)
    params = sig.parameters
    assert "contract" in params
    assert "barSize" in params
    assert "whatToShow" in params
    assert "useRTH" in params


def test_disconnected_event_exists() -> None:
    """ib.disconnectedEvent — needed in Task 8 for reconnect handler."""
    ib = IB()
    assert hasattr(ib, "disconnectedEvent")
