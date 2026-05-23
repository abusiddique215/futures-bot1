"""assert_host_allowed — hostname whitelist for live deployments.

Topstep prohibits trading from VPS / VPN endpoints. The binding ban language
lives in help article 8680268 ("Can I use a VPN?"), NOT in 10305426
(prohibited strategies, which only mentions VPS in passing). The guard:

  - env='live'  → assert socket.gethostname() ∈ cfg.live_hostnames.
                  Empty whitelist is a hard error (fail-closed).
  - env='paper' → skip (Topstep Practice has no VPS restriction; IB paper
                  is irrelevant to Topstep's ToS).
  - env='dev'   → skip (sim broker, no real broker).

This guard is DUPLICATIVE of TopstepXExecutionClient.__init__'s identical
check (Plan 8 T3). Both layers are intentional:
  - Runtime guard (here) fires at process start, before any broker code
    loads — catches misconfiguration even on `--check` smoke runs.
  - Broker-client guard fires at connect() — catches any code path that
    bypasses bot.runtime.main() (e.g. a future plugin that builds the
    client directly).

Spec: 07-config-and-deploy.md §3.6.
Citation: https://help.topstep.com/en/articles/8680268-can-i-use-a-vpn
"""
from __future__ import annotations

import socket
from collections.abc import Callable

from bot.config import BotConfig


class HostNotAllowedError(RuntimeError):
    """Raised when env=live but the current hostname isn't whitelisted."""


def assert_host_allowed(
    cfg: BotConfig,
    *,
    hostname: Callable[[], str] | None = None,
) -> None:
    """Validate the current hostname against `cfg.live_hostnames` when live.

    Tests inject `hostname=lambda: 'fake'` to avoid touching real DNS / OS.
    Production callers pass nothing → socket.gethostname() is used.

    Article 8680268 citation MUST appear in the raised message — the operator
    seeing a CI failure or LaunchAgent log needs a direct link to the rule.
    """
    if cfg.env != "live":
        return

    if not cfg.live_hostnames:
        raise HostNotAllowedError(
            "env='live' but cfg.live_hostnames is empty — VPS-ban fail-closed. "
            "Add allowed hostnames to bot.yml. "
            "See https://help.topstep.com/en/articles/8680268-can-i-use-a-vpn",
        )

    current = (hostname or socket.gethostname)()
    if current not in cfg.live_hostnames:
        raise HostNotAllowedError(
            f"hostname {current!r} not in cfg.live_hostnames "
            f"{cfg.live_hostnames!r} — Topstep VPS/VPN ban applies. "
            "See https://help.topstep.com/en/articles/8680268-can-i-use-a-vpn",
        )
