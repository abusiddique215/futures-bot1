"""Tolerant regex-based parser for Discord signal messages.

Accepts (case-insensitively):
  BUY NQ @20100 SL=20070 TP=20160
  LONG MNQH26 limit 20100 stop 20070 target 20160
  SHORT 1 NQ at 20100 stop 20130 tp 20040
  🟢 BUY NQ @20100 SL=20070 TP=20160          # emoji prefixes tolerated

Returns `None` on unparseable input (logged INFO by callers — typos are
normal in a chat channel). The parser is deliberately conservative: it
requires a side keyword followed by a price; everything else is optional
and defaults documented per field.

Quantities default to 1 when omitted. Symbol defaults to `default_symbol`
when no contract code is present in the message.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from bot.signals.source import SignalEvent, SignalSide

log = logging.getLogger(__name__)


_SIDE_BUY = re.compile(r"\b(buy|long)\b", re.IGNORECASE)
_SIDE_SELL = re.compile(r"\b(sell|short)\b", re.IGNORECASE)

# Symbol: NQ, MNQ, ES, MES, GC, MGC plus optional month-year code (e.g. MNQH26).
# Two letters minimum, optionally followed by 3 char month/year.
_SYMBOL = re.compile(r"\b(M?(?:NQ|ES|GC))([FGHJKMNQUVXZ]\d{1,2})?\b")

# A number = digits with optional comma-thousands and optional decimal.
# e.g. 20100, 20,100, 20100.25, 20,100.5.
# Order matters: try the comma form first (it requires ≥1 comma group so
# it only matches "20,100") — if no commas present, fall through to plain
# digits. The plain alternative is `\d+(?:\.\d+)?` which greedily eats all
# adjacent digits.
_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"

# Entry price: prefixed by '@', 'at', or 'limit'.
_LIMIT = re.compile(rf"(?:@|\bat\b|\blimit\b)\s*{_NUM}", re.IGNORECASE)
# Stop loss: prefixed by 'sl', 'stop', or 'stop loss'.
_STOP = re.compile(rf"\b(?:sl|stop(?:\s+loss)?)\s*[:=]?\s*{_NUM}", re.IGNORECASE)
# Take profit: prefixed by 'tp', 'target', or 'take profit'.
_TP = re.compile(rf"\b(?:tp|target|take\s+profit)\s*[:=]?\s*{_NUM}", re.IGNORECASE)

# Quantity directly after the side keyword: BUY 3 NQ ...
_SIDE_THEN_QTY = re.compile(r"\b(?:buy|long|sell|short)\s+(\d+)\s+[A-Z]",
                            re.IGNORECASE)


def _to_float(s: str) -> float:
    return float(s.replace(",", ""))


def parse_signal_message(
    text: str,
    *,
    default_symbol: str,
    received_at: datetime,
    source_id: str,
) -> SignalEvent | None:
    """Parse a single message into a `SignalEvent` or return None.

    See module docstring for accepted formats. The caller is responsible
    for supplying a tz-aware `received_at` and a stable `source_id`
    (e.g. Discord message ID).
    """
    if not text or not text.strip():
        return None

    is_buy = _SIDE_BUY.search(text) is not None
    is_sell = _SIDE_SELL.search(text) is not None
    if is_buy == is_sell:
        # Either both present (ambiguous) or neither present — give up.
        log.info("signal parse: no unambiguous side in %r", text)
        return None
    side: SignalSide = "BUY" if is_buy else "SELL"

    limit_match = _LIMIT.search(text)
    if limit_match is None:
        log.info("signal parse: no entry price in %r", text)
        return None
    limit_price = _to_float(limit_match.group(1))

    symbol_match = _SYMBOL.search(text)
    if symbol_match is not None:
        symbol = symbol_match.group(0)
    else:
        symbol = default_symbol

    qty_match = _SIDE_THEN_QTY.search(text)
    qty = int(qty_match.group(1)) if qty_match is not None else 1

    stop_match = _STOP.search(text)
    stop_loss = _to_float(stop_match.group(1)) if stop_match is not None else None

    tp_match = _TP.search(text)
    take_profit = _to_float(tp_match.group(1)) if tp_match is not None else None

    return SignalEvent(
        received_at=received_at,
        symbol=symbol,
        side=side,
        qty=qty,
        limit_price=limit_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        raw_text=text,
        source_id=source_id,
    )
