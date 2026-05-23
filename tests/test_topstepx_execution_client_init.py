"""TopstepXExecutionClient constructor + hostname VPS-guard.

Spec 02 §3.3 connect-flow step 1 + 00 D14.

The hostname guard is the D14 VPS-ban defense: if env="live" the client
must refuse to start on any host not in the whitelist. Paper env skips
the check (running on dev laptop is fine).
"""
from __future__ import annotations

import pytest

from bot.execution.topstepx_client import TopstepXExecutionClient
from tests.fakes.fake_projectx import FakeProjectX


def _make_client(
    *,
    env: str = "paper",
    live_hostname_whitelist: list[str] | None = None,
    hostname: str = "test-host",
) -> TopstepXExecutionClient:
    fake = FakeProjectX()
    return TopstepXExecutionClient(
        username="u",
        api_key="k",
        account_name="acct-A",
        env=env,  # type: ignore[arg-type]
        live_hostname_whitelist=live_hostname_whitelist,
        client_factory=lambda: fake,
        hostname=lambda: hostname,
    )


def test_paper_env_allows_any_host() -> None:
    """env='paper' bypasses the hostname guard (dev laptop is fine)."""
    client = _make_client(env="paper", hostname="random-laptop")
    assert client.env == "paper"
    assert client.account_name == "acct-A"


def test_live_env_with_matching_hostname_succeeds() -> None:
    """env='live' + hostname in whitelist constructs normally."""
    client = _make_client(
        env="live",
        live_hostname_whitelist=["mac-pro", "backup-mac"],
        hostname="mac-pro",
    )
    assert client.env == "live"


def test_live_env_with_blocked_hostname_raises() -> None:
    """env='live' + hostname NOT in whitelist raises RuntimeError.

    This is the VPS-ban guard: if someone (or some script) tries to start
    the live client on an unrecognized host, we refuse fail-closed before
    any auth attempt.
    """
    with pytest.raises(RuntimeError, match="hostname"):
        _make_client(
            env="live",
            live_hostname_whitelist=["mac-pro"],
            hostname="random-cloud-vm",
        )


def test_live_env_without_whitelist_raises() -> None:
    """env='live' with no whitelist at all is fail-closed.

    The whole point of the guard is to enumerate allowed hosts; an
    unconfigured whitelist on live env is a misconfiguration that
    MUST refuse to start.
    """
    with pytest.raises(RuntimeError, match="whitelist"):
        _make_client(env="live", live_hostname_whitelist=None, hostname="any-host")


def test_live_env_with_empty_whitelist_raises() -> None:
    """An empty list is treated the same as None."""
    with pytest.raises(RuntimeError, match="whitelist"):
        _make_client(env="live", live_hostname_whitelist=[], hostname="any-host")


def test_invalid_env_value_raises() -> None:
    """Only 'paper' and 'live' are accepted."""
    with pytest.raises(ValueError, match="env"):
        TopstepXExecutionClient(
            username="u",
            api_key="k",
            account_name="acct",
            env="staging",  # type: ignore[arg-type]
            client_factory=lambda: FakeProjectX(),
        )
