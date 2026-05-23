"""hydrate_runtime — compose RuntimeState from snapshots + handles.

Called once at startup after a clean reconcile. Bundles the persistent
runtime context (broker handle, journal handle, cfg, secrets) with the
immediate state (positions, equity, PnL, high-water) the event loop needs
to begin trading. The event loop reads `state.broker.place_order(...)` and
`state.journal.record_*(...)` directly — RuntimeState is a façade, not a
copy.

Composition rules (spec 07 §3.6):
  - positions          ← BrokerState (broker is truth)
  - equity             ← BrokerState.account_equity
  - realized_pnl_today ← journal.get_last_equity_snapshot().realized_pnl_today
                         (0.0 if no snapshot yet — cold start)
  - high_water_equity  ← journal.get_last_equity_snapshot().high_water_equity
                         (broker.account_equity as seed on cold start)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot.config import BotConfig
from bot.runtime.reconcile import BrokerState, JournalState, ReconcileResult
from bot.runtime.secrets import SecretsDict


@dataclass(frozen=True)
class RuntimeState:
    """Composed view passed into the event loop.

    `broker` and `journal` are typed `Any` because RuntimeState is built
    from concrete clients (SimExecutionClient, IBExecutionClient,
    TopstepXExecutionClient) plus the Journal — formally it'd be
    `ExecutionClient | None`, but the event loop just needs the methods.
    """
    cfg: BotConfig
    secrets: SecretsDict
    broker: Any
    journal: Any
    positions: dict[str, int]
    equity: float
    realized_pnl_today: float
    high_water_equity: float


async def hydrate_runtime(
    *,
    rr: ReconcileResult,
    broker_state: BrokerState,
    journal_state: JournalState,
    cfg: BotConfig,
    secrets: SecretsDict,
    broker: Any,
    journal: Any,
) -> RuntimeState:
    """Build the RuntimeState. Raises ValueError if rr.ok is False.

    The caller (main()) is expected to short-circuit before reaching here on
    a bad reconcile — but we guard defensively so any direct caller (tests,
    future code) can't smuggle around the safety net.
    """
    if not rr.ok:
        raise ValueError(
            f"hydrate_runtime called with ReconcileResult.ok=False; "
            f"position_diff={rr.position_diff}, order_diff={rr.order_diff}",
        )

    last_snap = await journal.get_last_equity_snapshot()
    if last_snap is None:
        realized = 0.0
        high_water = broker_state.account_equity
    else:
        realized = float(last_snap.realized_pnl_today)
        high_water = float(last_snap.high_water_equity)

    return RuntimeState(
        cfg=cfg,
        secrets=secrets,
        broker=broker,
        journal=journal,
        positions=dict(broker_state.positions),
        equity=broker_state.account_equity,
        realized_pnl_today=realized,
        high_water_equity=high_water,
    )
