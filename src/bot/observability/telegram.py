"""TelegramAlerter — outbound POST-only via httpx async client.

VPS-ban-safe: this module NEVER opens an inbound port. No webhook, no Updater,
no polling for inbound updates. Just `POST sendMessage` over httpx. The
`python-telegram-bot` dep is pinned in pyproject for future inbound-command
support but is intentionally not imported here — pulling in
`telegram.ext.Application` would drag in machinery we don't need.

Tests inject an `httpx.MockTransport` so no real HTTP egress happens.
"""
from __future__ import annotations

from typing import Literal

import httpx

Severity = Literal["INFO", "WARN", "CRITICAL"]

_SEVERITY_RANK: dict[Severity, int] = {"INFO": 10, "WARN": 20, "CRITICAL": 30}


class TelegramAlerter:
    """Send a single-line alert to a Telegram chat.

    The class owns its own httpx.AsyncClient (lazily built from `transport` if
    provided — tests pass MockTransport). Long-lived processes should call
    `close()` on shutdown; tests rely on garbage collection.
    """

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        min_severity: Severity = "WARN",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if min_severity not in _SEVERITY_RANK:
            raise ValueError(f"unknown min_severity {min_severity!r}")
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._min_severity = min_severity
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    @property
    def _api_url(self) -> str:
        return f"https://api.telegram.org/bot{self._bot_token}/sendMessage"

    async def send(self, text: str, severity: Severity) -> None:
        """POST the message if `severity` clears the configured floor.

        Below-threshold sends are dropped silently (this is the typical case
        for the chatty INFO-tier journal events).
        """
        if severity not in _SEVERITY_RANK:
            raise ValueError(f"unknown severity {severity!r}")
        if _SEVERITY_RANK[severity] < _SEVERITY_RANK[self._min_severity]:
            return
        payload = {"chat_id": self._chat_id, "text": text}
        await self._client.post(self._api_url, json=payload)

    async def close(self) -> None:
        await self._client.aclose()
