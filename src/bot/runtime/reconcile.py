"""reconcile() — broker truth vs journal expectation.

The driver MUST refuse to start if broker reality disagrees with the journal's
last known state. The two sides are:

  BrokerState  : positions + open_orders + account_equity as reported by
                 ExecutionClient.get_positions() + get_open_orders() +
                 get_account() at startup.
  JournalState : positions + open_orders + account_equity from the journal's
                 last persisted snapshot.

reconcile() computes a symmetric diff. Any non-empty diff → not ok. The
caller (bot.runtime.main) consults `cfg.halt_on_journal_desync` and exits 5
if not ok and halt is set; otherwise logs CRITICAL and proceeds (operator
override path).

This module is pure data — no I/O, no async. snapshot_broker() and
snapshot_journal() live in main.py (they're async because the underlying
clients are).

Spec: 07-config-and-deploy.md §4.2.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BrokerState:
    """Snapshot of what the broker reports at startup."""
    positions: dict[str, int]                  # symbol → signed qty; absent = flat
    open_orders: dict[str, dict[str, object]]  # client_order_id → broker fields
    account_equity: float


@dataclass(frozen=True)
class JournalState:
    """Snapshot of what the journal believes was last persisted."""
    positions: dict[str, int]                  # symbol → signed qty; absent = flat
    open_orders: dict[str, dict[str, object]]  # client_order_id → recorded fields
    account_equity: float


@dataclass(frozen=True)
class ReconcileResult:
    """Verdict from reconcile().

    `ok` is True iff both diffs are empty. `position_diff` maps each
    disagreeing symbol to (broker_qty, journal_qty); `order_diff` maps each
    disagreeing client_order_id to (broker_dict|None, journal_dict|None).
    None on a side means "absent on that side".
    """
    ok: bool
    position_diff: dict[str, tuple[int, int]] = field(default_factory=dict)
    order_diff: dict[
        str, tuple[dict[str, object] | None, dict[str, object] | None]
    ] = field(default_factory=dict)


def reconcile(broker: BrokerState, journal: JournalState) -> ReconcileResult:
    """Compare broker and journal state — return a ReconcileResult.

    Position-diff rules:
      - A symbol present in one side with qty=0 is treated as absent
        (broker may explicitly report flat positions; journal omits them).
      - Otherwise: any (broker_qty != journal_qty) is a diff.

    Order-diff rules:
      - Union of client_order_ids across both sides.
      - A client_order_id present on one side but not the other → diff with
        the missing side recorded as None.
      - Both sides present but the recorded dicts differ → diff (caller can
        inspect tuple for which fields changed).
    """
    position_diff: dict[str, tuple[int, int]] = {}
    symbols = set(broker.positions) | set(journal.positions)
    for sym in symbols:
        b_qty = broker.positions.get(sym, 0)
        j_qty = journal.positions.get(sym, 0)
        if b_qty != j_qty:
            position_diff[sym] = (b_qty, j_qty)

    order_diff: dict[
        str, tuple[dict[str, object] | None, dict[str, object] | None]
    ] = {}
    coids = set(broker.open_orders) | set(journal.open_orders)
    for coid in coids:
        b_side = broker.open_orders.get(coid)
        j_side = journal.open_orders.get(coid)
        if b_side is None or j_side is None or b_side != j_side:
            order_diff[coid] = (b_side, j_side)

    return ReconcileResult(
        ok=not (position_diff or order_diff),
        position_diff=position_diff,
        order_diff=order_diff,
    )
