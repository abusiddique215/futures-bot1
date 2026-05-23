"""TopstepXExecutionClient — live broker adapter for Topstep accounts.

Implements ExecutionClient Protocol via project-x-py 3.5.9.

SAFETY-CRITICAL. This adapter touches real-money Topstep Combine + Funded
accounts. Several defenses MUST stay in place:

  1. Side encoding — see bot.execution.topstepx_constants (SIDE_BUY=0 footgun).
  2. Hostname VPS-guard — env='live' fails closed unless socket.gethostname()
     is in the configured whitelist (D14 VPS ban).
  3. 90-second reconnect deadline — stricter than IB paper's 5 min. On expiry
     escalate to risk-gate force-flatten.
  4. JWT pre-refresh at 22h.

Dependency injection: tests pass `client_factory=lambda: FakeProjectX()` to
swap the real project_x_py ProjectX for an in-memory fake. No CI test
touches the network — the real broker only runs in a manual live-paper
verify by the operator before going live.

Spec: 02-execution-clients.md §3.3, §3.4, §3.7, §3.8.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Final, Literal

log = logging.getLogger(__name__)

# JWT lifetime is ~24h per spec §3.3; we re-auth 2h early to absorb clock
# skew + transient outages. 22 * 3600 = 79_200.
JWT_REFRESH_INTERVAL_SECONDS: Final[int] = 22 * 60 * 60


class TopstepXExecutionClient:
    """ExecutionClient backed by project-x-py against TopstepX (live rail).

    Construction is cheap — no network. `connect()` does the auth + suite-open.
    For tests, pass `client_factory` returning a FakeProjectX; production
    passes a lambda that builds a real `project_x_py.ProjectX` from env.
    """

    def __init__(
        self,
        *,
        username: str,
        api_key: str,
        account_name: str,
        env: Literal["paper", "live"],
        client_factory: Callable[[], Any],
        live_hostname_whitelist: Iterable[str] | None = None,
        hostname: Callable[[], str] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if env not in ("paper", "live"):
            raise ValueError(
                f"env must be 'paper' or 'live', got {env!r}",
            )

        # Materialize the whitelist so we can introspect it cheaply.
        whitelist: list[str] | None
        if live_hostname_whitelist is None:
            whitelist = None
        else:
            whitelist = list(live_hostname_whitelist)

        # Hostname VPS-guard. Live env is fail-closed: a missing or empty
        # whitelist is a misconfiguration, not a permissive default.
        if env == "live":
            if not whitelist:
                raise RuntimeError(
                    "env='live' requires a non-empty live_hostname_whitelist "
                    "(VPS-ban guard). Refusing to start.",
                )
            current = (hostname or socket.gethostname)()
            if current not in whitelist:
                raise RuntimeError(
                    f"hostname {current!r} not in live_hostname_whitelist "
                    f"{whitelist!r} — VPS-ban guard fail-closed.",
                )

        self.username = username
        self.api_key = api_key
        self.account_name = account_name
        self.env: Literal["paper", "live"] = env
        self._client_factory = client_factory
        self._live_hostname_whitelist = whitelist
        self._hostname_fn = hostname or socket.gethostname
        self._sleep: Callable[[float], Awaitable[None]] = sleep or asyncio.sleep

        # Connect-time state, populated by connect():
        self._client: Any | None = None
        self._suite: Any | None = None
        self._account_id: int | None = None
        self._jwt_refresh_task: asyncio.Task[None] | None = None

    # ---- public read-only state ----------------------------------------

    @property
    def account_id(self) -> int | None:
        return self._account_id

    # ---- connect / disconnect ------------------------------------------

    async def connect(self, symbol: str = "MNQ") -> None:
        """Authenticate + resolve account_id + open the trading suite.

        Spec 02 §3.3 connect-flow:
          1. (already enforced in __init__) hostname guard.
          2. Build the SDK client via injected factory.
          3. authenticate() → JWT.
          4. list_accounts() → match by configured account_name.
          5. open trading suite for `symbol`.
          6. Schedule the 22h JWT pre-refresh task.

        Raises RuntimeError if no account matches account_name.
        """
        self._client = self._client_factory()
        await self._client.authenticate()

        accounts = await self._client.list_accounts()
        for acct in accounts:
            if acct.name == self.account_name:
                self._account_id = acct.id
                break
        else:
            raise RuntimeError(
                f"No TopstepX account named {self.account_name!r} found. "
                f"Got: {[a.name for a in accounts]!r}",
            )

        self._suite = await self._client.create_suite(
            symbol=symbol, account_id=self._account_id,
        )

        # Start the JWT pre-refresh task. MUST be done here (not in __init__)
        # so there's a running event loop to attach to.
        self._jwt_refresh_task = asyncio.create_task(self._jwt_refresh_loop())

    async def disconnect(self) -> None:
        """Cancel the JWT refresh task and tear down the suite.

        Safe to call multiple times.
        """
        if self._jwt_refresh_task is not None:
            self._jwt_refresh_task.cancel()
            try:
                await self._jwt_refresh_task
            except (asyncio.CancelledError, Exception):
                # Cancellation is the expected path; suppress.
                pass
            self._jwt_refresh_task = None

        if self._suite is not None:
            await self._suite.disconnect()

    # ---- JWT pre-refresh ------------------------------------------------

    async def _jwt_refresh_loop(self) -> None:
        """Re-authenticate every 22h. Runs until cancelled by disconnect().

        On authenticate() failure, log and continue — the reactive 401 path
        in connect/place_order will recover. We don't want a transient
        network blip during a refresh to crash the live process.
        """
        try:
            while True:
                await self._sleep(JWT_REFRESH_INTERVAL_SECONDS)
                if self._client is None:
                    return
                try:
                    await self._client.authenticate()
                    log.info("topstepx JWT pre-refresh ok")
                except Exception as exc:
                    log.warning("topstepx JWT pre-refresh failed: %s", exc)
        except asyncio.CancelledError:
            return
