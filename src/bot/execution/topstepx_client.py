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

import socket
from collections.abc import Callable, Iterable
from typing import Any, Literal


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

        # Connect-time state, populated by connect():
        self._client: Any | None = None
        self._suite: Any | None = None
        self._account_id: int | None = None
