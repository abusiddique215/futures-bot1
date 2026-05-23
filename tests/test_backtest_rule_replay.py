"""RuleReplayReporter — re-runs intent stream through a fresh TopstepRiskGate.

Catches the case where the original strategy run somehow bypassed the gate (or
where a gate-bug shipped an approval that retrospectively shouldn't have been
given). The reporter takes a `gate_factory` so each `replay()` call gets a
fresh gate — no leaked state across reporter invocations.

Tests synthesize intent+state pairs by hand. No engine, no parquet.
"""
from __future__ import annotations

from datetime import UTC, datetime

from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.config import RiskConfig
from bot.risk.gate import TopstepRiskGate
from bot.types import AccountState, Bracket, OrderIntent


class _NoNews:
    def in_window(self, now: datetime) -> bool:
        return False

    def max_position_during_window(self) -> int:
        return 1


class _Telemetry:
    def alert(self, kind: str, **kw: object) -> None:
        pass


class _NullExec:
    """Minimal ExecutionClient stand-in; the gate stores the ref but doesn't
    call it during approve_or_deny (only force_flatten uses it)."""

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def place_order(self, intent: object) -> object: ...
    async def cancel_order(self, client_order_id: str) -> object: ...
    async def cancel_all(self, symbol: str) -> object: ...
    async def get_positions(self) -> object: ...
    async def get_open_orders(self) -> object: ...
    async def get_account(self) -> object: ...


def _make_gate() -> TopstepRiskGate:
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    cfg = RiskConfig(env="backtest", accounts_managed=1)
    return TopstepRiskGate(
        policy=policy,
        news_calendar=_NoNews(),
        execution_client=_NullExec(),  # type: ignore[arg-type]
        telemetry=_Telemetry(),
        config=cfg,
    )


def _state(
    *,
    open_positions: dict[str, int] | None = None,
    equity: float = 50_000.0,
    ts: datetime | None = None,
) -> AccountState:
    return AccountState(
        equity=equity,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions=open_positions or {},
        pending_intent_count=0,
        high_water_equity=50_000.0,
        is_combine=True,
        timestamp=ts or datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
    )


def _intent(
    side: str,
    qty: int,
    coid: str,
    ts: datetime,
    with_bracket: bool = True,
) -> OrderIntent:
    return OrderIntent(
        symbol="MNQ",
        side=side,  # type: ignore[arg-type]
        quantity=qty,
        order_type="MARKET",
        client_order_id=coid,
        timestamp=ts,
        bracket=Bracket(stop_loss_ticks=40, take_profit_ticks=80) if with_bracket else None,
    )


def test_replay_clean_stream_no_violations() -> None:
    """A reasonable open-then-close emits zero rule violations."""
    from bot.backtest.rule_replay import RuleReplayReporter
    ts = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    pairs = [
        (_intent("BUY", 1, "o-1", ts), _state(ts=ts)),
        (_intent("SELL", 1, "c-1", ts, with_bracket=False),
         _state(open_positions={"MNQ": 1}, ts=ts)),
    ]
    reporter = RuleReplayReporter(gate_factory=_make_gate)
    result = reporter.replay(pairs)
    assert result.total_intents_replayed == 2
    assert result.violations == []
    assert result.clean is True


def test_replay_detects_max_position_violation() -> None:
    """An intent that would push position above the 50-MNQ cap is denied with
    rule=MAX_POSITION."""
    from bot.backtest.rule_replay import RuleReplayReporter
    ts = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    # Existing |position| = 50 (cap), BUY 1 more → projected 51 > 50.
    pairs = [
        (_intent("BUY", 1, "over-cap", ts),
         _state(open_positions={"MNQ": 50}, ts=ts)),
    ]
    reporter = RuleReplayReporter(gate_factory=_make_gate)
    result = reporter.replay(pairs)
    assert result.total_intents_replayed == 1
    assert result.clean is False
    assert len(result.violations) == 1
    assert result.violations[0].rule == "MAX_POSITION"


def test_replay_uses_fresh_gate_per_call() -> None:
    """Two back-to-back replay() calls must not share gate state — calling
    replay() with a violation must NOT leak the strategy-disabled latch to a
    second replay() call on a clean stream."""
    from bot.backtest.rule_replay import RuleReplayReporter
    ts = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    reporter = RuleReplayReporter(gate_factory=_make_gate)

    # First replay: clean.
    first = reporter.replay([(_intent("BUY", 1, "ok-1", ts), _state(ts=ts))])
    assert first.clean is True

    # Second replay would fail rule 4 on a stale, shared gate if state leaked.
    second_pairs = [
        (_intent("BUY", 1, "over-cap", ts),
         _state(open_positions={"MNQ": 50}, ts=ts)),
    ]
    second = reporter.replay(second_pairs)
    assert len(second.violations) == 1
    assert second.violations[0].rule == "MAX_POSITION"

    # Third replay on a fresh stream: clean again, proving the gate was reset.
    third = reporter.replay([(_intent("BUY", 1, "ok-2", ts), _state(ts=ts))])
    assert third.clean is True
