"""Plan 7 T6: TelegramAlerter — outbound-only POST via httpx.

Polling-mode safe: this lib NEVER opens an inbound port. We just POST to
sendMessage. Tests mock httpx.AsyncClient via MockTransport so no real HTTP
egress happens.
"""
from __future__ import annotations

import httpx
import pytest

from bot.observability.telegram import TelegramAlerter

# Severity ranking the alerter uses internally — tests reach for it indirectly
# via send() being filtered.


def _make_transport(captured: list[dict]) -> httpx.MockTransport:
    """Build a MockTransport that records each request body + returns 200 OK."""
    async def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        captured.append({
            "url": str(request.url),
            "body": body,
        })
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    return httpx.MockTransport(handler)


async def test_send_posts_to_telegram_api():
    captured: list[dict] = []
    transport = _make_transport(captured)
    alerter = TelegramAlerter(
        bot_token="TOKEN-X",
        chat_id="123456",
        min_severity="INFO",
        transport=transport,
    )

    await alerter.send("hello", severity="INFO")

    assert len(captured) == 1
    # URL is api.telegram.org/bot<TOKEN>/sendMessage
    assert "api.telegram.org" in captured[0]["url"]
    assert "/botTOKEN-X/sendMessage" in captured[0]["url"]
    body = captured[0]["body"]
    assert "123456" in body
    assert "hello" in body


async def test_send_filters_below_min_severity():
    captured: list[dict] = []
    transport = _make_transport(captured)
    alerter = TelegramAlerter(
        bot_token="t", chat_id="c", min_severity="WARN", transport=transport,
    )
    await alerter.send("debug noise", severity="INFO")
    await alerter.send("warn loud", severity="WARN")
    await alerter.send("crit very", severity="CRITICAL")

    bodies = [c["body"] for c in captured]
    assert len(bodies) == 2
    assert any("warn loud" in b for b in bodies)
    assert any("crit very" in b for b in bodies)
    assert not any("debug noise" in b for b in bodies)


async def test_critical_passes_all_filters():
    captured: list[dict] = []
    transport = _make_transport(captured)
    for min_sev in ("INFO", "WARN", "CRITICAL"):
        captured.clear()
        alerter = TelegramAlerter(
            bot_token="t", chat_id="c", min_severity=min_sev, transport=transport,
        )
        await alerter.send("boom", severity="CRITICAL")
        assert len(captured) == 1, f"min_severity={min_sev} dropped CRITICAL"


@pytest.mark.parametrize("severity", ["INFO", "WARN", "CRITICAL"])
async def test_send_accepts_all_severities(severity):
    captured: list[dict] = []
    transport = _make_transport(captured)
    alerter = TelegramAlerter(
        bot_token="t", chat_id="c", min_severity="INFO", transport=transport,
    )
    await alerter.send("x", severity=severity)
    assert len(captured) == 1


async def test_invalid_severity_raises():
    transport = _make_transport([])
    alerter = TelegramAlerter(
        bot_token="t", chat_id="c", min_severity="INFO", transport=transport,
    )
    with pytest.raises(ValueError, match="unknown severity"):
        await alerter.send("x", severity="GREEN")  # type: ignore[arg-type]


async def test_send_uses_chat_id_in_body():
    captured: list[dict] = []
    transport = _make_transport(captured)
    alerter = TelegramAlerter(
        bot_token="t", chat_id="42424242", min_severity="INFO", transport=transport,
    )
    await alerter.send("hi", severity="INFO")
    assert "42424242" in captured[0]["body"]
