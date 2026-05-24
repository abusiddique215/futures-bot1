"""parse_signal_message — tolerant Discord-message parser. T2."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot.signals.parser import parse_signal_message
from bot.signals.source import SignalEvent

_TS = datetime(2026, 5, 23, 14, 0, tzinfo=UTC)


def _parse(text: str, default_symbol: str = "MNQH26") -> SignalEvent | None:
    return parse_signal_message(text, default_symbol=default_symbol,
                                 received_at=_TS, source_id="m1")


# ---- Four canonical formats ------------------------------------------------

def test_format_a_buy_nq_with_at():
    ev = _parse("BUY NQ @20100 SL=20070 TP=20160")
    assert ev is not None
    assert ev.side == "BUY"
    assert ev.symbol == "NQ"
    assert ev.qty == 1
    assert ev.limit_price == 20_100.0
    assert ev.stop_loss == 20_070.0
    assert ev.take_profit == 20_160.0


def test_format_b_long_mnqh26_keywords():
    ev = _parse("LONG MNQH26 limit 20100 stop 20070 target 20160")
    assert ev is not None
    assert ev.side == "BUY"
    assert ev.symbol == "MNQH26"
    assert ev.limit_price == 20_100.0
    assert ev.stop_loss == 20_070.0
    assert ev.take_profit == 20_160.0


def test_format_c_short_with_qty():
    ev = _parse("SHORT 1 NQ at 20100 stop 20130 tp 20040")
    assert ev is not None
    assert ev.side == "SELL"
    assert ev.symbol == "NQ"
    assert ev.qty == 1
    assert ev.limit_price == 20_100.0
    assert ev.stop_loss == 20_130.0
    assert ev.take_profit == 20_040.0


def test_format_d_emoji_prefixed():
    ev = _parse("🟢 BUY NQ @20100 SL=20070 TP=20160")
    assert ev is not None
    assert ev.side == "BUY"
    assert ev.symbol == "NQ"
    assert ev.limit_price == 20_100.0


def test_red_emoji_short():
    ev = _parse("🔴 SHORT MNQH26 @20100 SL=20130 TP=20040")
    assert ev is not None
    assert ev.side == "SELL"


# ---- Edge cases ------------------------------------------------------------

def test_junk_returns_none():
    assert _parse("hello world") is None
    assert _parse("") is None
    assert _parse("good morning everyone, gonna be a great trading day") is None


def test_missing_tp_defaults_to_none():
    ev = _parse("BUY NQ @20100 SL=20070")
    assert ev is not None
    assert ev.take_profit is None
    assert ev.stop_loss == 20_070.0


def test_missing_sl_and_tp():
    ev = _parse("BUY NQ @20100")
    assert ev is not None
    assert ev.stop_loss is None
    assert ev.take_profit is None
    assert ev.limit_price == 20_100.0


def test_case_insensitive():
    for text in ("buy NQ @20100", "Buy NQ @20100", "BUY nq @20100"):
        ev = _parse(text)
        assert ev is not None, text
        assert ev.side == "BUY"


def test_numeric_with_comma():
    ev = _parse("BUY NQ @20,100 SL=20,070 TP=20,160")
    assert ev is not None
    assert ev.limit_price == 20_100.0
    assert ev.stop_loss == 20_070.0
    assert ev.take_profit == 20_160.0


def test_numeric_decimal():
    ev = _parse("BUY MNQ @20100.25 SL=20070.5 TP=20160.0")
    assert ev is not None
    assert ev.limit_price == 20_100.25
    assert ev.stop_loss == 20_070.5
    assert ev.take_profit == 20_160.0


def test_no_explicit_symbol_uses_default():
    ev = _parse("BUY @20100 SL=20070 TP=20160", default_symbol="MNQH26")
    assert ev is not None
    assert ev.symbol == "MNQH26"


def test_qty_defaults_to_one_when_omitted():
    ev = _parse("BUY NQ @20100 SL=20070 TP=20160")
    assert ev is not None
    assert ev.qty == 1


def test_explicit_qty_parsed():
    ev = _parse("BUY 3 NQ @20100 SL=20070 TP=20160")
    assert ev is not None
    assert ev.qty == 3


def test_returns_carries_raw_text_and_source_id():
    raw = "🟢 BUY NQ @20100 SL=20070 TP=20160"
    ev = _parse(raw)
    assert ev is not None
    assert ev.raw_text == raw
    assert ev.source_id == "m1"


@pytest.mark.parametrize("text", [
    "this is a random message",
    "20100 at NQ",  # no side keyword
    "SELL",         # side only, nothing else
])
def test_unparseable_inputs(text):
    assert _parse(text) is None
