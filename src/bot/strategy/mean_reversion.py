"""Bollinger-band + RSI mean-reversion strategy with mid-band exits.

Reusable across markets (designed for Plans 17 / 18 / 20). The constructor
takes every tunable as a kwarg; all market-specific data (tick size,
contract symbol) is resolved at construction time from
`bot.markets.MARKETS`, so the same class handles GC, ES, NQ etc. without
hardcoded constants inside.

Entry logic:
    * Long when bar.close <= lower BB and RSI <= rsi_oversold.
    * Short when bar.close >= upper BB and RSI >= rsi_overbought.

Exit logic (per open position, every bar after entry):
    * Mid-band cross — bar.high reaches BB middle (long) or bar.low reaches
      BB middle (short). The mid is dynamic; exits move with the band.
    * Stop loss — fixed distance set at entry equal to
      ``stddev_at_entry * reward_ratio`` rounded to ticks (min 1 tick).
    * No schedule cutoff here — the FleetRuntime's Schedule wrapper handles
      session-window gating before bars reach the strategy. We only exit on
      mid or stop.

Daily cap: max_trades_per_day counts ENTRIES, applied per Topstep trading
day (17:00 CT → 17:00 CT) — matching ORB's `_topstep_day_key`.

`reward_ratio` parameter:
    Controls stop distance as a multiple of the BB stddev at entry. 1.0 =
    stop placed roughly at the opposite side of one stddev from entry.
    Plans 18/20 can dial it tighter (0.5) or wider (2.0) to fit a market's
    chop profile. TP is NOT derived from reward_ratio — mid-band exits are
    dynamic.
"""
from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

from bot.markets.registry import get_market
from bot.types import AccountState, Bar, Bracket, OrderIntent

_CT: Final[ZoneInfo] = ZoneInfo("America/Chicago")
_SESSION_DAY_OFFSET: Final[timedelta] = timedelta(hours=17)


def _topstep_day_key(ts: datetime) -> date:
    """Topstep trading day = (ts in CT) - 17h, then take the date.

    Mirrors `bot.strategy.orb._topstep_day_key`. Kept local to avoid
    cross-strategy coupling; both strategies use the same Topstep day rule.
    """
    ct = ts.astimezone(_CT)
    shifted = ct - _SESSION_DAY_OFFSET
    return shifted.date()


def _sma(values: list[float]) -> float:
    return sum(values) / len(values)


def _stddev(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(var)


def _wilder_rsi(closes: list[float], period: int) -> float | None:
    """Wilder's RSI. Returns None until `period + 1` closes are available."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [-min(d, 0.0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


@dataclass
class _OpenPosition:
    side: Literal["BUY", "SELL"]
    entry: float
    stop_price: float


class MeanReversionStrategy:
    """Bollinger-band + RSI mean-reversion with dynamic mid-band exits.

    See module docstring for entry/exit logic + reuse-across-markets notes.
    """

    def __init__(
        self,
        *,
        bb_period: int = 20,
        bb_stddev: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        reward_ratio: float = 1.0,
        max_trades_per_day: int = 3,
        symbol: str = "GC",
        quantity: int = 1,
    ) -> None:
        if bb_period < 2:
            raise ValueError("bb_period must be >= 2")
        if rsi_period < 1:
            raise ValueError("rsi_period must be >= 1")
        if quantity < 1:
            raise ValueError("quantity must be >= 1")
        if max_trades_per_day < 1:
            raise ValueError("max_trades_per_day must be >= 1")
        if reward_ratio <= 0:
            raise ValueError("reward_ratio must be > 0")
        # Resolve tick size at construction — raises KeyError for unregistered
        # symbols. This is the load-bearing assertion that the strategy is
        # market-agnostic.
        self._tick_size = get_market(symbol).tick_size

        self.symbol = symbol
        self.quantity = quantity
        self._bb_period = bb_period
        self._bb_stddev = bb_stddev
        self._rsi_period = rsi_period
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._reward_ratio = reward_ratio
        self._max_trades_per_day = max_trades_per_day

        # We need enough closes for both the BB window and the RSI window.
        window = max(bb_period, rsi_period + 1)
        self._closes: deque[float] = deque(maxlen=window)
        self._day_key: date | None = None
        self._trades_today: int = 0
        self._position: _OpenPosition | None = None
        self._intent_counter: int = 0

    # ---- Strategy protocol -------------------------------------------------

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        _ = state  # unused; strategy is stateless wrt account
        day_key = _topstep_day_key(bar.timestamp)
        if self._day_key != day_key:
            self._day_key = day_key
            self._trades_today = 0
            # Open positions cross trading-day boundaries — do NOT auto-flat
            # here; the schedule/risk gate is responsible for forced exits.

        self._closes.append(bar.close)

        bands = self._bollinger()
        # Exit logic runs whenever we have a position, even pre-BB-warmup
        # (stop is still active).
        if self._position is not None:
            exit_intent = self._maybe_emit_exit(bar, bands)
            if exit_intent is not None:
                return [exit_intent]
            return []

        if bands is None:
            return []
        if self._trades_today >= self._max_trades_per_day:
            return []
        rsi = _wilder_rsi(list(self._closes), self._rsi_period)
        if rsi is None:
            return []

        lower, mid, upper, sigma = bands
        _ = mid
        if bar.close <= lower and rsi <= self._rsi_oversold:
            return [self._open_intent(bar, side="BUY", sigma=sigma)]
        if bar.close >= upper and rsi >= self._rsi_overbought:
            return [self._open_intent(bar, side="SELL", sigma=sigma)]
        return []

    # ---- Internals ---------------------------------------------------------

    def _bollinger(self) -> tuple[float, float, float, float] | None:
        """Return (lower, mid, upper, sigma) or None until warmed up."""
        if len(self._closes) < self._bb_period:
            return None
        window = list(self._closes)[-self._bb_period:]
        mid = _sma(window)
        sigma = _stddev(window, mid)
        if sigma == 0:
            return None
        offset = self._bb_stddev * sigma
        return (mid - offset, mid, mid + offset, sigma)

    def _open_intent(
        self, bar: Bar, *, side: Literal["BUY", "SELL"], sigma: float,
    ) -> OrderIntent:
        stop_loss_ticks = max(1, round(sigma * self._reward_ratio / self._tick_size))
        entry = bar.close
        if side == "BUY":
            stop_price = entry - stop_loss_ticks * self._tick_size
        else:
            stop_price = entry + stop_loss_ticks * self._tick_size
        self._position = _OpenPosition(side=side, entry=entry, stop_price=stop_price)
        self._trades_today += 1
        self._intent_counter += 1
        # take-profit ticks: 1 sigma at entry, rounded; the BRACKET attached
        # below is informational for live brokers — sim engine + mid-band exit
        # logic do the actual closing.
        tp_ticks = max(1, round(sigma / self._tick_size))
        return OrderIntent(
            symbol=self.symbol,
            side=side,
            quantity=self.quantity,
            order_type="BRACKET",
            client_order_id=f"mr-{self._day_key}-{self._intent_counter}-entry",
            timestamp=bar.timestamp,
            bracket=Bracket(stop_loss_ticks=stop_loss_ticks, take_profit_ticks=tp_ticks),
        )

    def _maybe_emit_exit(
        self,
        bar: Bar,
        bands: tuple[float, float, float, float] | None,
    ) -> OrderIntent | None:
        assert self._position is not None
        pos = self._position
        close_side: Literal["BUY", "SELL"] = "SELL" if pos.side == "BUY" else "BUY"

        # Stop loss takes precedence (worst case for the trade).
        if pos.side == "BUY" and bar.low <= pos.stop_price:
            return self._emit_close(bar, close_side, tag="stop")
        if pos.side == "SELL" and bar.high >= pos.stop_price:
            return self._emit_close(bar, close_side, tag="stop")

        # Mid-band cross — only when BB is still warm.
        if bands is not None:
            _, mid, _, _ = bands
            if pos.side == "BUY" and bar.high >= mid:
                return self._emit_close(bar, close_side, tag="mid")
            if pos.side == "SELL" and bar.low <= mid:
                return self._emit_close(bar, close_side, tag="mid")
        return None

    def _emit_close(
        self, bar: Bar, side: Literal["BUY", "SELL"], *, tag: str,
    ) -> OrderIntent:
        self._intent_counter += 1
        intent = OrderIntent(
            symbol=self.symbol,
            side=side,
            quantity=self.quantity,
            order_type="MARKET",
            client_order_id=f"mr-{self._day_key}-{self._intent_counter}-exit-{tag}",
            timestamp=bar.timestamp,
        )
        self._position = None
        return intent
