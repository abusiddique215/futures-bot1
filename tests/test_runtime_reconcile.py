"""Plan 9 T5: reconcile(broker_state, journal_state) — broker truth.

The driver MUST refuse to start if broker reality and journal expectation
disagree on positions or open orders. Plan 9 main() exit code 5 fires when
ReconcileResult.ok is False and cfg.halt_on_journal_desync.

This module is pure data — no I/O, no async. The async snapshot_broker() /
snapshot_journal() helpers live in main.py (T7); reconcile itself takes
their results and returns a verdict.
"""
from __future__ import annotations

from bot.runtime.reconcile import (
    BrokerState,
    JournalState,
    ReconcileResult,
    reconcile,
)


def test_clean_state_is_ok() -> None:
    bs = BrokerState(
        positions={"MNQ": 2},
        open_orders={"COID-1": {"symbol": "MNQ", "qty": 1}},
        account_equity=50_500.0,
    )
    js = JournalState(
        positions={"MNQ": 2},
        open_orders={"COID-1": {"symbol": "MNQ", "qty": 1}},
        account_equity=50_500.0,
    )
    r = reconcile(bs, js)
    assert isinstance(r, ReconcileResult)
    assert r.ok is True
    assert r.position_diff == {}
    assert r.order_diff == {}


def test_phantom_broker_position_flags_mismatch() -> None:
    """Broker has a position the journal doesn't know about."""
    bs = BrokerState(
        positions={"MNQ": 2},
        open_orders={},
        account_equity=50_000.0,
    )
    js = JournalState(
        positions={},  # journal forgot
        open_orders={},
        account_equity=50_000.0,
    )
    r = reconcile(bs, js)
    assert r.ok is False
    assert r.position_diff == {"MNQ": (2, 0)}
    assert r.order_diff == {}


def test_phantom_journal_position_flags_mismatch() -> None:
    """Journal thinks there's a position the broker doesn't have."""
    bs = BrokerState(
        positions={},
        open_orders={},
        account_equity=50_000.0,
    )
    js = JournalState(
        positions={"MNQ": -1},
        open_orders={},
        account_equity=50_000.0,
    )
    r = reconcile(bs, js)
    assert r.ok is False
    assert r.position_diff == {"MNQ": (0, -1)}


def test_position_quantity_mismatch() -> None:
    bs = BrokerState(
        positions={"MNQ": 3},
        open_orders={},
        account_equity=50_000.0,
    )
    js = JournalState(
        positions={"MNQ": 2},
        open_orders={},
        account_equity=50_000.0,
    )
    r = reconcile(bs, js)
    assert r.ok is False
    assert r.position_diff == {"MNQ": (3, 2)}


def test_flat_position_not_listed_as_diff() -> None:
    """A symbol present in one dict with qty=0 is equivalent to absent."""
    bs = BrokerState(
        positions={"MNQ": 0},  # broker reports flat explicitly
        open_orders={},
        account_equity=50_000.0,
    )
    js = JournalState(
        positions={},  # journal omits flat
        open_orders={},
        account_equity=50_000.0,
    )
    r = reconcile(bs, js)
    assert r.ok is True
    assert r.position_diff == {}


def test_orphan_journal_order_flags_mismatch() -> None:
    """Journal has an open order the broker no longer reports."""
    bs = BrokerState(
        positions={},
        open_orders={},
        account_equity=50_000.0,
    )
    js = JournalState(
        positions={},
        open_orders={"COID-9": {"symbol": "MNQ", "qty": 1, "status": "WORKING"}},
        account_equity=50_000.0,
    )
    r = reconcile(bs, js)
    assert r.ok is False
    assert "COID-9" in r.order_diff
    broker_side, journal_side = r.order_diff["COID-9"]
    assert broker_side is None
    assert journal_side == {"symbol": "MNQ", "qty": 1, "status": "WORKING"}


def test_orphan_broker_order_flags_mismatch() -> None:
    """Broker has an open order the journal doesn't know about."""
    bs = BrokerState(
        positions={},
        open_orders={"COID-7": {"symbol": "MNQ", "qty": 1}},
        account_equity=50_000.0,
    )
    js = JournalState(
        positions={},
        open_orders={},
        account_equity=50_000.0,
    )
    r = reconcile(bs, js)
    assert r.ok is False
    assert "COID-7" in r.order_diff
    broker_side, journal_side = r.order_diff["COID-7"]
    assert broker_side == {"symbol": "MNQ", "qty": 1}
    assert journal_side is None


def test_multiple_diffs_all_reported() -> None:
    """A position diff AND an order diff in the same call — both listed."""
    bs = BrokerState(
        positions={"MNQ": 1},
        open_orders={"BROKER-ONLY": {"symbol": "MNQ"}},
        account_equity=50_100.0,
    )
    js = JournalState(
        positions={"MES": 2},
        open_orders={"JOURNAL-ONLY": {"symbol": "MES"}},
        account_equity=50_100.0,
    )
    r = reconcile(bs, js)
    assert r.ok is False
    assert set(r.position_diff.keys()) == {"MNQ", "MES"}
    assert set(r.order_diff.keys()) == {"BROKER-ONLY", "JOURNAL-ONLY"}


def test_reconcile_result_is_frozen() -> None:
    """ReconcileResult is immutable so it can't be mutated post-decision."""
    r = reconcile(
        BrokerState(positions={}, open_orders={}, account_equity=0.0),
        JournalState(positions={}, open_orders={}, account_equity=0.0),
    )
    import dataclasses
    with __import__("pytest").raises((dataclasses.FrozenInstanceError, AttributeError)):
        r.ok = False  # type: ignore[misc]
