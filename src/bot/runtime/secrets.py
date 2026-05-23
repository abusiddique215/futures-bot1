"""load_secrets — per-broker required-env-var validation.

Reads `.env` (via python-dotenv) on top of `os.environ`, then validates the
broker-specific required-var set declared per `cfg.broker`. The return is a
frozen `SecretsDict` whose `__repr__` masks plaintext values — by default we
never want a stack trace to spill an API key into a log.

Required-var matrix (Plan 9 T2):
  sim       → no broker secrets
  ib_paper  → IB_HOST, IB_PORT, IB_CLIENT_ID
  topstepx  → TOPSTEPX_USERNAME, TOPSTEPX_API_KEY, TOPSTEPX_ACCOUNT_NAME

Telegram credentials are loaded opportunistically — their absence does NOT
raise. The TelegramAlerter (Plan 7) no-ops when given a None token, so dev
runs without Telegram work out of the box.

Spec: 07-config-and-deploy.md §3.2.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from dotenv import dotenv_values

from bot.config import BotConfig

# Per-broker required env vars. Keep in sync with each ExecutionClient ctor.
_BROKER_REQUIRED: Final[dict[str, tuple[str, ...]]] = {
    "sim": (),
    "ib_paper": ("IB_HOST", "IB_PORT", "IB_CLIENT_ID"),
    "topstepx": ("TOPSTEPX_USERNAME", "TOPSTEPX_API_KEY", "TOPSTEPX_ACCOUNT_NAME"),
}


class MissingSecretError(RuntimeError):
    """Raised when a required env var is absent for the configured broker."""


@dataclass(frozen=True)
class SecretsDict:
    """Frozen container for runtime secrets.

    Plaintext values are stored on private fields and never appear in `repr`
    or `str` — only the *key names* leak (operators need to know what was
    set). Use `broker_secrets()` / `telegram_token()` / `telegram_chat_id()`
    to read values; broker_secrets() returns a defensive copy.
    """

    _broker: dict[str, str] = field(default_factory=dict, repr=False)
    _telegram_token: str | None = field(default=None, repr=False)
    _telegram_chat_id: str | None = field(default=None, repr=False)

    def broker_secrets(self) -> dict[str, str]:
        """Return a defensive copy of broker env vars."""
        return dict(self._broker)

    def telegram_token(self) -> str | None:
        return self._telegram_token

    def telegram_chat_id(self) -> str | None:
        return self._telegram_chat_id

    def __repr__(self) -> str:
        # Mask values — print only key names plus boolean presence for telegram.
        keys = sorted(self._broker.keys())
        tg_tok = "<set>" if self._telegram_token else "<unset>"
        tg_chat = "<set>" if self._telegram_chat_id else "<unset>"
        return (
            f"SecretsDict(broker_keys={keys!r}, "
            f"telegram_token={tg_tok}, telegram_chat_id={tg_chat})"
        )


def load_secrets(cfg: BotConfig, *, env_path: Path | None = None) -> SecretsDict:
    """Load and validate secrets for `cfg.broker`.

    Reads from `env_path` (if given) overlaid on `os.environ`. The .env file
    overrides existing os.environ entries — matching python-dotenv's
    `override=True` semantics so a developer can locally tweak values
    without exporting them in their shell. Production LaunchAgent deploys
    pass `env_path=None` and rely entirely on `os.environ`.

    Raises MissingSecretError naming the FIRST missing required var (so
    operators see one fix at a time rather than a list).
    """
    env: dict[str, str] = dict(os.environ)
    if env_path is not None:
        for k, v in dotenv_values(env_path).items():
            if v is not None:
                env[k] = v

    required = _BROKER_REQUIRED[cfg.broker]
    broker: dict[str, str] = {}
    for var in required:
        val = env.get(var)
        if val is None or val == "":
            raise MissingSecretError(
                f"Missing required env var for broker={cfg.broker!r}: {var}",
            )
        broker[var] = val

    tg_token = env.get(cfg.telegram.bot_token_env) or None
    tg_chat = env.get(cfg.telegram.chat_id_env) or None
    return SecretsDict(
        _broker=broker,
        _telegram_token=tg_token,
        _telegram_chat_id=tg_chat,
    )
