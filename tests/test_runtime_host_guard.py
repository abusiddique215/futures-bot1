"""Plan 9 T3: assert_host_allowed — hostname VPS-guard.

For env='live': socket.gethostname() MUST be in cfg.live_hostnames. Empty
whitelist + env=live is a hard error (fail-closed misconfiguration). For
paper / dev: skip the check entirely.

This is DUPLICATIVE of TopstepXExecutionClient.__init__'s guard (Plan 8
T3) on purpose — defense in depth, two layers. The runtime guard fires
first at startup; the broker guard catches anyone who reaches connect()
through a different code path. Don't refactor away.

Citation: Topstep article 8680268 (Can I use a VPN?) — the binding ban
language lives there, NOT in 10305426 (prohibited strategies).
"""
from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from bot.config import BotConfig, DataConfig
from bot.runtime.host_guard import HostNotAllowedError, assert_host_allowed


def _cfg(env: str, broker: str, hostnames: list[str]) -> BotConfig:
    return BotConfig(
        env=env,  # type: ignore[arg-type]
        broker=broker,  # type: ignore[arg-type]
        account_id="acct-0",
        strategy="orb",
        strategy_profile=Path("config/profiles/surge.yml"),
        risk_policy="combine_50k",
        data=DataConfig(
            historical_root=Path("data/parquet"),
            historical_vendor="firstratedata",
            live_source="ib",
        ),
        news_calendar=Path("config/news_calendar.yml"),
        flat_by_warning_ct=time(14, 0),
        flat_by_force_ct=time(15, 10),
        live_hostnames=hostnames,
    )


def test_paper_skips_check() -> None:
    cfg = _cfg("paper", "ib_paper", hostnames=[])
    # No raise even with empty whitelist and bogus hostname.
    assert_host_allowed(cfg, hostname=lambda: "random-laptop.local")


def test_dev_skips_check() -> None:
    cfg = _cfg("dev", "sim", hostnames=[])
    assert_host_allowed(cfg, hostname=lambda: "random-laptop.local")


def test_live_allowed_hostname_passes() -> None:
    cfg = _cfg("live", "topstepx", hostnames=["mac-mini-01.local"])
    assert_host_allowed(cfg, hostname=lambda: "mac-mini-01.local")


def test_live_denied_hostname_raises() -> None:
    cfg = _cfg("live", "topstepx", hostnames=["mac-mini-01.local"])
    with pytest.raises(HostNotAllowedError, match="vps-trader-01"):
        assert_host_allowed(cfg, hostname=lambda: "vps-trader-01.cloud")


def test_live_empty_whitelist_is_fail_closed() -> None:
    """Empty live_hostnames in env=live is a misconfiguration, not permissive."""
    cfg = _cfg("live", "topstepx", hostnames=[])
    with pytest.raises(HostNotAllowedError, match="empty"):
        assert_host_allowed(cfg, hostname=lambda: "mac-mini-01.local")


def test_error_message_cites_article_8680268() -> None:
    """The Topstep VPS/VPN ban citation MUST appear in the error message."""
    cfg = _cfg("live", "topstepx", hostnames=["mac-mini-01.local"])
    with pytest.raises(HostNotAllowedError, match="8680268"):
        assert_host_allowed(cfg, hostname=lambda: "vps-trader-01.cloud")
