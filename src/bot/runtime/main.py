"""bot.runtime.main — 8-step startup orchestrator.

The single entry point that ties everything together. Spec 07 §3.6 enumerates
the contract:

  1. cfg = load_config(args.config)
  2. secrets = load_secrets(cfg)                    — exit 3 on missing
  3. assert_host_allowed(cfg)                       — exit 4 on mismatch
  4. journal = await open_journal(cfg.journal_path)
  5. broker  = await connect_broker(cfg, secrets)
  6. bs = await snapshot_broker(broker); js = await snapshot_journal(journal)
  7. rr = reconcile(bs, js); if not rr.ok and cfg.halt_on_journal_desync:
       log CRITICAL + exit 5
  8. runtime = hydrate_runtime(...); await run_event_loop(runtime)

The orchestrator is 100% testable: every external dep is injected (load_config,
open_journal, connect_broker, event_loop, hostname, bus, cwd). Production
callers pass nothing; defaults wire to the concrete helpers.

Exit codes (POSIX):
  0  EXIT_OK
  3  EXIT_SECRETS_MISSING
  4  EXIT_HOST_DENIED
  5  EXIT_RECONCILE_FAIL

Note: the dual pricing path ($49+$149 vs $95+$0) is surfaced in the startup
banner so the operator sees both Topstep subscription options at the start
of every session. The VPS/VPN ban references article 8680268.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Final, Protocol

from bot.config import BotConfig
from bot.config import load_config as _default_load_config
from bot.runtime.host_guard import HostNotAllowedError, assert_host_allowed
from bot.runtime.hydrate import RuntimeState, hydrate_runtime
from bot.runtime.icloud_check import check_icloud_tree
from bot.runtime.reconcile import (
    BrokerState,
    JournalState,
    ReconcileResult,
    reconcile,
)
from bot.runtime.secrets import MissingSecretError, SecretsDict, load_secrets

log = logging.getLogger(__name__)

EXIT_OK: Final[int] = 0
EXIT_SECRETS_MISSING: Final[int] = 3
EXIT_HOST_DENIED: Final[int] = 4
EXIT_RECONCILE_FAIL: Final[int] = 5


class _Bus(Protocol):
    def alert(self, kind: str, **kw: object) -> None: ...


class _NullBus:
    def alert(self, kind: str, **kw: object) -> None:
        _ = (kind, kw)


# ---- Default broker / journal openers ---------------------------------------

async def _default_open_journal(path: str) -> Any:
    """Default journal opener — async because aiosqlite is async."""
    from bot.journal import Journal
    j = await Journal.connect(path)
    await j.apply_migrations()
    return j


async def _default_connect_broker(cfg: BotConfig, secrets: SecretsDict) -> Any:
    """Dispatch to the broker named in cfg.broker.

    sim       → SimExecutionClient (no creds)
    ib_paper  → IBExecutionClient(host, port, client_id)
    topstepx  → TopstepXExecutionClient (full ctor + client_factory)

    Each branch calls await client.connect() before returning so the
    caller gets a connected, ready-to-use broker.
    """
    if cfg.broker == "sim":
        from bot.backtest.sim_client import SimExecutionClient
        client: Any = SimExecutionClient()
        await client.connect()
        return client

    if cfg.broker == "ib_paper":
        from bot.execution.ib_client import IBExecutionClient
        bs = secrets.broker_secrets()
        client = IBExecutionClient(
            host=bs["IB_HOST"],
            port=int(bs["IB_PORT"]),
            client_id=int(bs["IB_CLIENT_ID"]),
        )
        await client.connect()
        return client

    if cfg.broker == "topstepx":
        from bot.execution.topstepx_client import TopstepXExecutionClient
        bs = secrets.broker_secrets()
        # Map cfg.env ('dev'|'paper'|'live') → TopstepX-client env ('paper'|'live').
        # broker_matches_env validator already forbids env='dev' + broker=topstepx
        # in production configs, but keep the mapping explicit for clarity.
        tx_env: str = "live" if cfg.env == "live" else "paper"

        def _factory() -> Any:
            # project_x_py.ProjectX takes runtime kwargs sourced from env;
            # we pass the secrets the client already validated via env vars.
            import project_x_py  # mypy: ignore_missing_imports → returns Any
            return project_x_py.ProjectX(
                username=bs["TOPSTEPX_USERNAME"],
                api_key=bs["TOPSTEPX_API_KEY"],
            )

        client = TopstepXExecutionClient(
            username=bs["TOPSTEPX_USERNAME"],
            api_key=bs["TOPSTEPX_API_KEY"],
            account_name=bs["TOPSTEPX_ACCOUNT_NAME"],
            env=tx_env,  # type: ignore[arg-type]
            client_factory=_factory,
            live_hostname_whitelist=cfg.live_hostnames or None,
        )
        await client.connect()
        return client

    raise ValueError(f"unknown broker {cfg.broker!r}")


# ---- Snapshot helpers (async because clients are) ---------------------------

async def snapshot_broker(broker: Any) -> BrokerState:
    """Snapshot what the broker currently reports."""
    positions = await broker.get_positions()
    open_orders = await broker.get_open_orders()
    account = await broker.get_account()
    return BrokerState(
        positions={p.symbol: p.signed_qty for p in positions},
        open_orders={
            o.client_order_id: {
                "symbol": o.symbol,
                "side": o.side,
                "quantity": o.quantity,
                "order_type": o.order_type,
                "status": o.status,
            }
            for o in open_orders
        },
        account_equity=account.equity,
    )


async def snapshot_journal(journal: Any) -> JournalState:
    """Snapshot what the journal believes the world looks like."""
    positions = await journal.get_open_positions()
    open_orders = await journal.get_open_orders()
    last_equity = await journal.get_last_equity_snapshot()
    return JournalState(
        positions={p.symbol: p.signed_qty for p in positions},
        open_orders={
            o.client_order_id: {
                "symbol": o.symbol,
                "side": o.side,
                "quantity": o.quantity,
                "order_type": o.order_type,
                "status": o.status,
            }
            for o in open_orders
        },
        account_equity=last_equity.equity if last_equity is not None else 0.0,
    )


# ---- Default factories for Strategy + BarSource (Plan 10 T5) ---------------

def _resolve_strategy(cfg: BotConfig) -> Any:
    """Build the Strategy for `cfg.strategy`.

    Plan 10 ships the wiring with a PlaceholderStrategy default — the
    LiveTradingLoop is fully exercised in tests + smoke runs without
    requiring real ORB warmup bars. The ORB factory (ORBProfile YAML →
    OpeningRangeBreakoutStrategy) lands in a follow-up plan; intentionally
    out of scope here to keep T5 to a single concern (loop wiring).
    """
    _ = cfg
    from bot.backtest.strategy import PlaceholderStrategy
    return PlaceholderStrategy()


def _resolve_bar_source(cfg: BotConfig, broker: Any) -> Any:
    """Build the LiveBarSource for `cfg.broker` + `cfg.data.live_source`.

    For `broker=sim` (dev / smoke / backtest) the default is an EMPTY
    SimBarSource — the LiveTradingLoop iterates zero bars and exits
    immediately, keeping the Plan 9 `--check` smoke test green. Real
    live sources (IBLiveBarStream, TopstepX market-data adapter) are
    wired in their respective broker-integration plans.
    """
    _ = (cfg, broker)
    from bot.runtime.bar_source import SimBarSource
    return SimBarSource([])


# ---- Default event loop (Plan 10 T5: real LiveTradingLoop) ------------------

async def _default_event_loop(state: RuntimeState) -> None:
    """Construct + run a LiveTradingLoop driven by `state`'s broker/journal.

    Strategy + bar source come from the resolver factories above. For
    `env=dev` + `broker=sim` the default bar source is empty, so this
    function returns immediately — preserving the Plan 9 smoke test.

    Plan 10 T5 wired this in; Plan 9 shipped a no-op stub here.
    """
    from bot.backtest.tracker import AccountStateTracker
    from bot.observability.bus import NoopTelemetryBus
    from bot.runtime.live_loop import LiveTradingLoop

    gate = _build_gate(state)
    tracker = AccountStateTracker(
        start_balance=state.equity,
        is_combine=state.cfg.risk_policy.startswith("combine"),
    )
    loop = LiveTradingLoop(
        strategy=_resolve_strategy(state.cfg),
        gate=gate,
        tracker=tracker,
        broker=state.broker,
        journal=state.journal,
        telemetry=NoopTelemetryBus(),
        heartbeat_path=state.cfg.heartbeat_path,
        symbol=state.cfg.data.symbol_primary,
    )
    await loop.run(_resolve_bar_source(state.cfg, state.broker))


def _build_gate(state: RuntimeState) -> Any:
    """Construct a TopstepRiskGate wired to the runtime broker + a no-op news
    calendar. The full news calendar load (YAML) is Plan 5 territory; the
    risk gate accepts any object satisfying the NewsCalendar Protocol.
    """
    from bot.observability.bus import NoopTelemetryBus
    from bot.risk.combine_drawdown import CombineIntradayDrawdown
    from bot.risk.config import RiskConfig
    from bot.risk.gate import TopstepRiskGate

    class _NoopNews:
        def in_window(self, now: Any) -> bool:
            _ = now
            return False

        def max_position_during_window(self) -> int:
            return 1

    risk_cfg = RiskConfig(env="backtest", accounts_managed=1)
    policy = CombineIntradayDrawdown(50_000, 2_000, 5)
    return TopstepRiskGate(
        policy=policy,
        news_calendar=_NoopNews(),
        execution_client=state.broker,
        telemetry=NoopTelemetryBus(),
        config=risk_cfg,
    )


# ---- The orchestrator -------------------------------------------------------

def _emit_startup_banner(bus: _Bus, cfg: BotConfig) -> None:
    """Emit the startup banner with dual Topstep pricing paths visible.

    Operators see both paths in every session log:
      Path A: $49 Combine + $149/mo Funded subscription
      Path B: $95 LifeTime Combine + $0 Funded subscription
    """
    bus.alert(
        "STARTUP_BANNER",
        severity="INFO",
        reason=(
            "bot.runtime starting | "
            f"env={cfg.env} broker={cfg.broker} account={cfg.account_id} | "
            "Topstep pricing options: $49 Combine + $149/mo Funded, "
            "OR $95 LifeTime Combine + $0 Funded sub | "
            "VPS/VPN ban: article 8680268"
        ),
    )


async def main(
    *,
    config_path: Path,
    check_only: bool = False,
    # Injection seams (defaults wire to the real helpers):
    load_config_fn: Callable[[Path], BotConfig] | None = None,
    open_journal_fn: Callable[[str], Awaitable[Any]] | None = None,
    connect_broker_fn: Callable[[BotConfig, SecretsDict], Awaitable[Any]] | None = None,
    event_loop_fn: Callable[[RuntimeState], Awaitable[None]] | None = None,
    bar_source_fn: Callable[[BotConfig, Any], Any] | None = None,
    strategy_fn: Callable[[BotConfig], Any] | None = None,
    hostname_fn: Callable[[], str] | None = None,
    bus: _Bus | None = None,
    cwd: Path | None = None,
    env_file: Path | None = None,
) -> int:
    """Execute the 8-step startup contract. Returns a POSIX exit code.

    All external deps are injectable for testing. Production callers pass
    nothing; defaults dispatch to the real helpers. `bar_source_fn` /
    `strategy_fn` let Plan 10 tests drive the loop with synthetic bars
    + a one-shot strategy without monkey-patching the resolver module
    globals.
    """
    _load_config = load_config_fn or _default_load_config
    _open_journal = open_journal_fn or _default_open_journal
    _connect_broker = connect_broker_fn or _default_connect_broker
    # When a custom bar_source/strategy is supplied, build an event loop that
    # uses it. Otherwise fall through to _default_event_loop (which uses the
    # module-level resolvers).
    if event_loop_fn is not None:
        _event_loop = event_loop_fn
    elif bar_source_fn is not None or strategy_fn is not None:
        _bs_fn = bar_source_fn or _resolve_bar_source
        _st_fn = strategy_fn or _resolve_strategy
        async def _custom_event_loop(state: RuntimeState) -> None:
            from bot.backtest.tracker import AccountStateTracker
            from bot.observability.bus import NoopTelemetryBus
            from bot.runtime.live_loop import LiveTradingLoop
            gate = _build_gate(state)
            tracker = AccountStateTracker(
                start_balance=state.equity,
                is_combine=state.cfg.risk_policy.startswith("combine"),
            )
            loop = LiveTradingLoop(
                strategy=_st_fn(state.cfg),
                gate=gate, tracker=tracker,
                broker=state.broker, journal=state.journal,
                telemetry=NoopTelemetryBus(),
                heartbeat_path=state.cfg.heartbeat_path,
                symbol=state.cfg.data.symbol_primary,
            )
            await loop.run(_bs_fn(state.cfg, state.broker))
        _event_loop = _custom_event_loop
    else:
        _event_loop = _default_event_loop
    _bus: _Bus = bus or _NullBus()
    _cwd = cwd or Path.cwd()

    # Step 1: load config
    cfg = _load_config(config_path)
    _emit_startup_banner(_bus, cfg)

    # iCloud-tree warning — must fire before journal open since SQLite WAL is
    # what gets corrupted. WARN only.
    check_icloud_tree(_cwd, _bus)

    # Step 2: load secrets — exit 3 on missing
    try:
        secrets = load_secrets(cfg, env_path=env_file)
    except MissingSecretError as e:
        log.critical("missing secret: %s", e)
        _bus.alert("STARTUP_FAIL", severity="CRITICAL", reason=str(e),
                   exit_code=EXIT_SECRETS_MISSING)
        return EXIT_SECRETS_MISSING

    # Step 3: hostname guard — exit 4 on mismatch
    try:
        assert_host_allowed(cfg, hostname=hostname_fn)
    except HostNotAllowedError as e:
        log.critical("host denied: %s", e)
        _bus.alert("STARTUP_FAIL", severity="CRITICAL", reason=str(e),
                   exit_code=EXIT_HOST_DENIED)
        return EXIT_HOST_DENIED

    # Step 4: open journal
    journal = await _open_journal(cfg.journal_path)

    # Step 5: connect broker
    broker = await _connect_broker(cfg, secrets)

    try:
        # Step 6: snapshot both sides
        bs_state = await snapshot_broker(broker)
        js_state = await snapshot_journal(journal)

        # Step 7: reconcile — exit 5 if dirty and halt_on_journal_desync
        rr: ReconcileResult = reconcile(bs_state, js_state)
        if not rr.ok:
            msg = (
                f"reconcile mismatch: positions={rr.position_diff!r}, "
                f"orders={rr.order_diff!r}"
            )
            log.critical(msg)
            _bus.alert(
                "RECONCILE_MISMATCH",
                severity="CRITICAL",
                reason=msg,
                position_diff=rr.position_diff,
                order_diff=rr.order_diff,
            )
            if cfg.halt_on_journal_desync:
                return EXIT_RECONCILE_FAIL
            log.critical("halt_on_journal_desync=False — proceeding despite mismatch")

        # Step 8: hydrate + event loop
        runtime = await hydrate_runtime(
            rr=ReconcileResult(ok=True),  # passed clean since we either passed or overrode
            broker_state=bs_state,
            journal_state=js_state,
            cfg=cfg,
            secrets=secrets,
            broker=broker,
            journal=journal,
        )
        if not check_only:
            await _event_loop(runtime)
        return EXIT_OK
    finally:
        # Cleanup runs on every exit path (happy, exception, --check return).
        try:
            await broker.disconnect()
        except Exception as e:
            log.warning("broker.disconnect raised during cleanup: %s", e)
        try:
            await journal.close()
        except Exception as e:
            log.warning("journal.close raised during cleanup: %s", e)
