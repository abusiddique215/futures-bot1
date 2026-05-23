"""Opening Range Breakout strategy + ORBProfile.

The Strategy emits BUY/SELL bracketed intents after the opening range completes
and price closes outside the range. Stop is `atr_mult x ATR`, take-profit is
`tp_r_multiple x stop_distance`. Session-time logic uses America/New_York.

Spec: Plan 5.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from bot.constants import MIN_TICK
from bot.types import AccountState, Bar, Bracket, OrderIntent

_ET = ZoneInfo("America/New_York")
_CT = ZoneInfo("America/Chicago")
# Topstep trading day boundary: 17:00 CT (per spec 00 §5).
_SESSION_DAY_OFFSET = timedelta(hours=17)


class ORBProfile(BaseModel):
    """Per-profile ORB tuning. Loaded from YAML by ``profile_loader.load_orb_profile``."""

    model_config = ConfigDict(validate_default=True)

    symbol: Literal["MNQ", "NQ"] = "MNQ"
    quantity: int = Field(default=1, ge=1)
    range_minutes: int = Field(default=5, ge=1, le=30)
    atr_period: int = Field(default=14, ge=1)
    atr_mult: float = Field(default=1.0, gt=0)
    tp_r_multiple: float = Field(default=2.0, gt=0)
    session_start_et: time = time(9, 30)
    cutoff_time_et: time | None = None
    max_trades_per_day: int = Field(default=1, ge=1)


def _compute_atr(bars: list[Bar], period: int) -> float | None:
    """ATR = simple average of the last ``period`` True Ranges.

    True Range = max(high-low, |high - prev_close|, |low - prev_close|).
    Requires ``period + 1`` bars (one prior close + ``period`` TRs). Returns
    ``None`` when fewer than ``period + 1`` bars are available.
    """
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        h = bars[i].high
        low = bars[i].low
        tr = max(h - low, abs(h - prev_close), abs(low - prev_close))
        trs.append(tr)
    last = trs[-period:]
    return sum(last) / period


def _topstep_day_key(ts: datetime) -> date:
    """Topstep trading day = date of (ts in CT) shifted back by 17 hours.

    A bar at 17:00 CT marks the start of the next trading day. We map
    timestamps before 17:00 CT to the same calendar date and timestamps at or
    after 17:00 CT to the next calendar date by subtracting 17h then taking the
    CT date.
    """
    ct = ts.astimezone(_CT)
    shifted = ct - _SESSION_DAY_OFFSET
    return shifted.date()


class OpeningRangeBreakoutStrategy:
    """5-minute Opening Range Breakout state machine.

    Builds the opening range during the first ``range_minutes`` of the ET
    session. After the range completes, a bar closing above ``range_high``
    emits a BUY bracket; below ``range_low`` emits a SELL bracket. Stop
    distance comes from ATR * ``atr_mult``; take-profit is
    ``tp_r_multiple * stop_distance``. We track our own open position so we
    can emit a closing intent when ``bar.high`` (long) or ``bar.low`` (short)
    crosses TP/SL — the engine does not auto-simulate bracket fills.
    """

    def __init__(self, profile: ORBProfile) -> None:
        self._profile = profile
        self._day_key: date | None = None
        self._range_high: float | None = None
        self._range_low: float | None = None
        self._bars_in_range: int = 0
        # ATR window needs period+1 bars; deque caps storage.
        self._recent_bars: deque[Bar] = deque(maxlen=profile.atr_period + 1)
        self._trades_today: int = 0
        # Our own open trade: (side, entry, stop_price, tp_price). None when flat.
        self._position: tuple[str, float, float, float] | None = None
        self._intent_counter: int = 0

    # ---- Strategy protocol ----------------------------------------------------

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        day_key = _topstep_day_key(bar.timestamp)
        if self._day_key != day_key:
            self._reset_day(day_key)

        self._recent_bars.append(bar)

        # If we hold an open position, look only for exit. We do not stack signals.
        if self._position is not None:
            exit_intent = self._maybe_emit_exit(bar)
            if exit_intent is not None:
                return [exit_intent]
            return []

        et_time = bar.timestamp.astimezone(_ET).time()
        if et_time < self._profile.session_start_et:
            return []

        # Range build phase.
        if self._bars_in_range < self._profile.range_minutes:
            self._update_range(bar)
            self._bars_in_range += 1
            return []

        # Post-range gating: per-day cap + cutoff time.
        if self._trades_today >= self._profile.max_trades_per_day:
            return []
        cutoff = self._profile.cutoff_time_et
        if cutoff is not None and et_time >= cutoff:
            return []

        atr = _compute_atr(list(self._recent_bars), self._profile.atr_period)
        if atr is None:
            return []

        assert self._range_high is not None
        assert self._range_low is not None
        if bar.close > self._range_high:
            return [self._open_intent(bar, side="BUY", atr=atr)]
        if bar.close < self._range_low:
            return [self._open_intent(bar, side="SELL", atr=atr)]
        return []

    # ---- Internals ------------------------------------------------------------

    def _reset_day(self, day_key: date) -> None:
        self._day_key = day_key
        self._range_high = None
        self._range_low = None
        self._bars_in_range = 0
        self._recent_bars.clear()
        self._trades_today = 0
        self._position = None

    def _update_range(self, bar: Bar) -> None:
        self._range_high = (
            bar.high if self._range_high is None else max(self._range_high, bar.high)
        )
        self._range_low = (
            bar.low if self._range_low is None else min(self._range_low, bar.low)
        )

    def _open_intent(self, bar: Bar, *, side: Literal["BUY", "SELL"], atr: float) -> OrderIntent:
        symbol = self._profile.symbol
        tick = MIN_TICK[symbol]
        stop_loss_ticks = round(atr * self._profile.atr_mult / tick)
        if stop_loss_ticks < 1:
            stop_loss_ticks = 1
        take_profit_ticks = round(stop_loss_ticks * self._profile.tp_r_multiple)
        entry = bar.close
        if side == "BUY":
            stop_price = entry - stop_loss_ticks * tick
            tp_price = entry + take_profit_ticks * tick
        else:
            stop_price = entry + stop_loss_ticks * tick
            tp_price = entry - take_profit_ticks * tick

        self._position = (side, entry, stop_price, tp_price)
        self._trades_today += 1
        self._intent_counter += 1
        return OrderIntent(
            symbol=symbol,
            side=side,
            quantity=self._profile.quantity,
            order_type="BRACKET",
            client_order_id=f"orb-{self._day_key}-{self._intent_counter}",
            timestamp=bar.timestamp,
            bracket=Bracket(
                stop_loss_ticks=stop_loss_ticks,
                take_profit_ticks=take_profit_ticks,
            ),
        )

    def _maybe_emit_exit(self, bar: Bar) -> OrderIntent | None:
        assert self._position is not None
        side, _entry, stop_price, tp_price = self._position
        hit_long_tp = side == "BUY" and bar.high >= tp_price
        hit_long_sl = side == "BUY" and bar.low <= stop_price
        hit_short_tp = side == "SELL" and bar.low <= tp_price
        hit_short_sl = side == "SELL" and bar.high >= stop_price
        if not (hit_long_tp or hit_long_sl or hit_short_tp or hit_short_sl):
            return None
        close_side: Literal["BUY", "SELL"] = "SELL" if side == "BUY" else "BUY"
        self._intent_counter += 1
        intent = OrderIntent(
            symbol=self._profile.symbol,
            side=close_side,
            quantity=self._profile.quantity,
            order_type="MARKET",
            client_order_id=f"orb-{self._day_key}-{self._intent_counter}",
            timestamp=bar.timestamp,
        )
        self._position = None
        return intent
