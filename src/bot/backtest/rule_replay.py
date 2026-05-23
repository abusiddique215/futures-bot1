"""RuleReplayReporter — replays approved intents through a fresh TopstepRiskGate.

If the live or backtest run was correct, every intent the strategy emitted that
was approved at the time should still be approved by the gate on replay. Any
denial surfaced here means EITHER (a) the original gate had a bug, OR (b) the
gate was bypassed somewhere it shouldn't have been. The reporter is a
belt-and-suspenders check on top of the gate, run every backtest by default.

A fresh gate is built per `replay()` call via `gate_factory`. Per-intent
state is provided by the caller (typically a snapshot from the engine), so the
gate's CombineIntradayDrawdown state-machine is *not* re-run — only the
approve_or_deny pre-trade checks are evaluated. Re-running on_tick across the
historical state stream is out of scope for v1.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from bot.risk.gate import TopstepRiskGate
from bot.types import AccountState, ApprovedOrder, OrderDenied, OrderIntent


@dataclass(frozen=True)
class RuleReplayResult:
    total_intents_replayed: int
    violations: list[OrderDenied] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return len(self.violations) == 0


class RuleReplayReporter:
    """Replay an (intent, state) stream through a fresh TopstepRiskGate."""

    def __init__(self, gate_factory: Callable[[], TopstepRiskGate]) -> None:
        self._gate_factory = gate_factory

    def replay(
        self,
        intents_with_states: Iterable[tuple[OrderIntent, AccountState]],
    ) -> RuleReplayResult:
        gate = self._gate_factory()
        violations: list[OrderDenied] = []
        count = 0
        for intent, state in intents_with_states:
            count += 1
            decision = gate.approve_or_deny(intent, state)
            if isinstance(decision, OrderDenied):
                violations.append(decision)
            else:
                assert isinstance(decision, ApprovedOrder)  # exhaustive
        return RuleReplayResult(
            total_intents_replayed=count,
            violations=violations,
        )
