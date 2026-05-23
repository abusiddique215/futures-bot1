"""Plan 9 T2: load_secrets() — per-broker required-var validation.

Reads .env via python-dotenv, returns a frozen SecretsDict that masks
plaintext values from repr. Missing required vars raise MissingSecretError.

Required-var matrix (see runtime/secrets.py docstring):
  sim       → no broker secrets
  ib_paper  → IB_HOST, IB_PORT, IB_CLIENT_ID
  topstepx  → TOPSTEPX_USERNAME, TOPSTEPX_API_KEY, TOPSTEPX_ACCOUNT_NAME
  telegram block always reads TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
    (the env-var NAMES come from cfg.telegram.{bot_token_env, chat_id_env})

The Path argument to load_secrets is optional — if None, only os.environ
is consulted (production deploys set env vars via LaunchAgent's
EnvironmentVariables block, not via .env).
"""
from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from bot.config import BotConfig, DataConfig, TelegramConfig
from bot.runtime.secrets import MissingSecretError, SecretsDict, load_secrets


def _cfg(broker: str, env: str = "dev") -> BotConfig:
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
        telegram=TelegramConfig(),
        news_calendar=Path("config/news_calendar.yml"),
        flat_by_warning_ct=time(14, 0),
        flat_by_force_ct=time(15, 10),
    )


def test_sim_needs_no_broker_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even with TELEGRAM_* missing, sim should succeed when telegram is omitted.
    # But our default TelegramConfig still expects the env vars to exist; sim
    # path validates ONLY broker requirements — telegram secrets are loaded
    # opportunistically (None if missing).
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    secrets = load_secrets(_cfg("sim"), env_path=None)
    assert isinstance(secrets, SecretsDict)
    assert secrets.broker_secrets() == {}


def test_ib_paper_requires_three_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IB_HOST", "127.0.0.1")
    monkeypatch.setenv("IB_PORT", "7497")
    monkeypatch.setenv("IB_CLIENT_ID", "11")
    secrets = load_secrets(_cfg("ib_paper", env="paper"), env_path=None)
    bs = secrets.broker_secrets()
    assert bs["IB_HOST"] == "127.0.0.1"
    assert bs["IB_PORT"] == "7497"
    assert bs["IB_CLIENT_ID"] == "11"


def test_ib_paper_missing_var_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IB_HOST", "127.0.0.1")
    monkeypatch.setenv("IB_PORT", "7497")
    monkeypatch.delenv("IB_CLIENT_ID", raising=False)
    with pytest.raises(MissingSecretError, match="IB_CLIENT_ID"):
        load_secrets(_cfg("ib_paper", env="paper"), env_path=None)


def test_topstepx_requires_three_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOPSTEPX_USERNAME", "alice")
    monkeypatch.setenv("TOPSTEPX_API_KEY", "secret-xyz")
    monkeypatch.setenv("TOPSTEPX_ACCOUNT_NAME", "PRACTICE-1")
    secrets = load_secrets(_cfg("topstepx", env="paper"), env_path=None)
    bs = secrets.broker_secrets()
    assert bs["TOPSTEPX_USERNAME"] == "alice"
    assert bs["TOPSTEPX_API_KEY"] == "secret-xyz"
    assert bs["TOPSTEPX_ACCOUNT_NAME"] == "PRACTICE-1"


def test_topstepx_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOPSTEPX_USERNAME", "alice")
    monkeypatch.delenv("TOPSTEPX_API_KEY", raising=False)
    monkeypatch.setenv("TOPSTEPX_ACCOUNT_NAME", "PRACTICE-1")
    with pytest.raises(MissingSecretError, match="TOPSTEPX_API_KEY"):
        load_secrets(_cfg("topstepx", env="paper"), env_path=None)


def test_telegram_secrets_opportunistic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Telegram secrets are loaded if present; their absence does NOT raise.

    The TelegramAlerter (Plan 7) handles a None token by no-op'ing — the
    bot still runs without Telegram in dev.
    """
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    secrets = load_secrets(_cfg("sim"), env_path=None)
    assert secrets.telegram_token() is None
    assert secrets.telegram_chat_id() is None

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    secrets2 = load_secrets(_cfg("sim"), env_path=None)
    assert secrets2.telegram_token() == "tok"
    assert secrets2.telegram_chat_id() == "12345"


def test_secrets_repr_masks_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Frozen SecretsDict must not leak plaintext in repr / str."""
    monkeypatch.setenv("TOPSTEPX_USERNAME", "alice")
    monkeypatch.setenv("TOPSTEPX_API_KEY", "TOP-SECRET-KEY-DO-NOT-LEAK")
    monkeypatch.setenv("TOPSTEPX_ACCOUNT_NAME", "PRACTICE-1")
    secrets = load_secrets(_cfg("topstepx", env="paper"), env_path=None)
    r = repr(secrets)
    s = str(secrets)
    assert "TOP-SECRET-KEY-DO-NOT-LEAK" not in r
    assert "TOP-SECRET-KEY-DO-NOT-LEAK" not in s
    # But the var names themselves are allowed (operators need to know what's set).
    assert "TOPSTEPX_API_KEY" in r


def test_secrets_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """SecretsDict is immutable — no attribute mutation after construction."""
    secrets = load_secrets(_cfg("sim"), env_path=None)
    with pytest.raises((AttributeError, TypeError)):
        secrets.foo = "bar"  # type: ignore[attr-defined]


def test_env_path_loads_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When env_path is given, vars from .env override os.environ defaults."""
    # Start from a clean slate — nothing in os.environ.
    monkeypatch.delenv("TOPSTEPX_USERNAME", raising=False)
    monkeypatch.delenv("TOPSTEPX_API_KEY", raising=False)
    monkeypatch.delenv("TOPSTEPX_ACCOUNT_NAME", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "TOPSTEPX_USERNAME=fromfile\n"
        "TOPSTEPX_API_KEY=keyfromfile\n"
        "TOPSTEPX_ACCOUNT_NAME=PRACTICE-Z\n",
    )
    secrets = load_secrets(_cfg("topstepx", env="paper"), env_path=env_file)
    bs = secrets.broker_secrets()
    assert bs["TOPSTEPX_USERNAME"] == "fromfile"
    assert bs["TOPSTEPX_API_KEY"] == "keyfromfile"
    assert bs["TOPSTEPX_ACCOUNT_NAME"] == "PRACTICE-Z"


def test_broker_secrets_returns_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """broker_secrets() returns a defensive copy — mutating the result does
    not leak back into the SecretsDict."""
    monkeypatch.setenv("IB_HOST", "127.0.0.1")
    monkeypatch.setenv("IB_PORT", "7497")
    monkeypatch.setenv("IB_CLIENT_ID", "11")
    secrets = load_secrets(_cfg("ib_paper", env="paper"), env_path=None)
    bs1 = secrets.broker_secrets()
    bs1["IB_HOST"] = "10.0.0.1"
    bs2 = secrets.broker_secrets()
    assert bs2["IB_HOST"] == "127.0.0.1"


