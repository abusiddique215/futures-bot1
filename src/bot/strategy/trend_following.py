"""TrendFollowingStrategy — EMA-pullback entry, ATR-bracketed exit, EoD flat.

Plan 16. PropBot's signal generator. Designed under the VSL's "Trend [Daily
Exit]" framing: enter on confirmed trend (fast EMA above/below slow EMA) when
price pulls back to the fast EMA; exit at +reward_ratio R, trend reversal
(EMAs cross back), or the session_end_ct cutoff.

EMA convention: alpha = 2/(period+1), seeded with the SMA of the first
`period` closes (the most common convention; matches TradingView's `ta.ema`).

ATR convention: simple average of the last 14 True Ranges, matching
`bot.strategy.orb._compute_atr` so reports compare cleanly across bots.

Trading-day boundary: `_topstep_day_key` (17:00 CT). Reused from ORB; the
max-trades-per-day counter resets at that boundary.

Symbol form: any form accepted by `bot.markets.get_market` works (bare root
like "MNQ" or contract form like "MNQH26"). Tick size is looked up via the
registry, so the strategy doesn't need a hard-coded symbol-set.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from bot.markets.registry import get_market
from bot.types import AccountState, Bar, Bracket, OrderIntent

_CT = ZoneInfo("America/Chicago")
# Topstep trading day boundary: 17:00 CT (mirrors orb._SESSION_DAY_OFFSET).
_SESSION_DAY_OFFSET = timedelta(hours=17)
# Chop filter: if |fast_ema - slow_ema| < CHOP_ATR_MULT * ATR, no entry.
_CHOP_ATR_MULT = 0.1


def _topstep_day_key(ts: datetime) -> date:
    """Topstep trading day = date of (ts in CT) shifted back by 17 hours."""
    ct = ts.astimezone(_CT)
    shifted = ct - _SESSION_DAY_OFFSET
    return shifted.date()


class TrendFollowingStrategy:
    """EMA-pullback trend follower with daily-exit cutoff.

    Parameters
    ----------
    fast_ema, slow_ema:
        EMA periods. Convention: fast < slow; ``fast > slow`` ⇒ uptrend.
    pullback_atr_mult:
        Entry is armed when |bar.close - fast_ema| <= pullback_atr_mult * ATR
        in the direction of the trend.
    reward_ratio:
        Take-profit distance = ``reward_ratio * stop_distance``.
    max_trades_per_day:
        Cap on entries per Topstep trading day. Resets at 17:00 CT.
    symbol:
        Contract symbol (bare root "MNQ" or contract form "MNQH26"). Used
        verbatim on emitted intents; tick size resolved via the markets
        registry.
    atr_period:
        ATR window. Default 14.
    session_end_ct:
        Daily flat cutoff in Central Time. Any open position at or after
        this wall-clock time generates a MARKET close intent.
    """

    def __init__(
        self,
        *,
        fast_ema: int = 20,
        slow_ema: int = 50,
        pullback_atr_mult: float = 0.5,
        reward_ratio: float = 1.5,
        max_trades_per_day: int = 1,
        symbol: str = "MNQ",
        atr_period: int = 14,
        session_end_ct: time = time(14, 30),
    ) -> None:
        if fast_ema <= 0 or slow_ema <= 0:
            raise ValueError("EMA periods must be positive")
        if fast_ema >= slow_ema:
            raise ValueError("fast_ema must be < slow_ema")
        if pullback_atr_mult <= 0:
            raise ValueError("pullback_atr_mult must be > 0")
        if reward_ratio <= 0:
            raise ValueError("reward_ratio must be > 0")
        if max_trades_per_day < 1:
            raise ValueError("max_trades_per_day must be >= 1")
        if atr_period < 1:
            raise ValueError("atr_period must be >= 1")

        self._fast_period = fast_ema
        self._slow_period = slow_ema
        self._pullback_atr_mult = pullback_atr_mult
        self._reward_ratio = reward_ratio
        self._max_trades_per_day = max_trades_per_day
        self._symbol = symbol
        self._atr_period = atr_period
        self._session_end_ct = session_end_ct

        # EMA state — None until SMA-seeded.
        self._fast_ema: float | None = None
        self._slow_ema: float | None = None
        # Seed buffers hold the first `period` closes, then we lock in SMA.
        self._fast_seed: list[float] = []
        self._slow_seed: list[float] = []
        # ATR uses the same convention as orb._compute_atr — keep period+1 bars.
        self._recent_bars: deque[Bar] = deque(maxlen=atr_period + 1)
        self._atr: float | None = None

        self._day_key: date | None = None
        self._trades_today: int = 0
        # Open position: (side, entry, stop_price, tp_price). None when flat.
        self._position: tuple[Literal["BUY", "SELL"], float, float, float] | None = None
        self._intent_counter: int = 0

    # ---- Strategy protocol ----------------------------------------------------

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        _ = state  # strategy is state-agnostic — only consumes bars
        self._maybe_roll_day(bar.timestamp)
        self._update_indicators(bar)

        # Open position → check for exit first (priority: EoD > TP/SL > reversal).
        if self._position is not None:
            exit_intent = self._maybe_exit(bar)
            if exit_intent is not None:
                return [exit_intent]
            return []

        # No position: look for entry.
        if self._fast_ema is None or self._slow_ema is None or self._atr is None:
            return []  # warming up
        if self._trades_today >= self._max_trades_per_day:
            return []
        if self._is_after_cutoff(bar.timestamp):
            return []  # don't open new positions after session_end_ct

        side = self._entry_side()
        if side is None:
            return []
        if not self._pullback_armed(bar, side):
            return []

        return [self._open_intent(bar, side=side, atr=self._atr)]

    # ---- Day / cutoff bookkeeping --------------------------------------------

    def _maybe_roll_day(self, ts: datetime) -> None:
        key = _topstep_day_key(ts)
        if self._day_key != key:
            self._day_key = key
            self._trades_today = 0
            # Note: indicators persist across days — trend bots don't reset
            # EMAs nightly. Only the per-day trade cap resets.

    def _is_after_cutoff(self, ts: datetime) -> bool:
        return ts.astimezone(_CT).time() >= self._session_end_ct

    # ---- Indicator updates ----------------------------------------------------

    def _update_indicators(self, bar: Bar) -> None:
        self._fast_ema = self._step_ema(
            self._fast_ema, self._fast_seed, self._fast_period, bar.close,
        )
        self._slow_ema = self._step_ema(
            self._slow_ema, self._slow_seed, self._slow_period, bar.close,
        )
        self._recent_bars.append(bar)
        self._atr = self._compute_atr()

    @staticmethod
    def _step_ema(
        current: float | None, seed_buf: list[float], period: int, close: float,
    ) -> float | None:
        """One EMA step. Returns the new EMA value or None if still seeding."""
        if current is not None:
            alpha = 2.0 / (period + 1)
            return alpha * close + (1.0 - alpha) * current
        # Still seeding — accumulate up to `period` closes, then lock in SMA.
        seed_buf.append(close)
        if len(seed_buf) < period:
            return None
        return sum(seed_buf) / period

    def _compute_atr(self) -> float | None:
        """ATR = simple average of last `atr_period` True Ranges.

        Matches `bot.strategy.orb._compute_atr` exactly.
        """
        bars = list(self._recent_bars)
        if len(bars) < self._atr_period + 1:
            return None
        trs: list[float] = []
        for i in range(1, len(bars)):
            prev_close = bars[i - 1].close
            h = bars[i].high
            low = bars[i].low
            trs.append(max(h - low, abs(h - prev_close), abs(low - prev_close)))
        last = trs[-self._atr_period:]
        return sum(last) / self._atr_period

    # ---- Entry logic ----------------------------------------------------------

    def _entry_side(self) -> Literal["BUY", "SELL"] | None:
        """Trend direction, or None during chop."""
        assert self._fast_ema is not None
        assert self._slow_ema is not None
        assert self._atr is not None
        spread = self._fast_ema - self._slow_ema
        if abs(spread) < _CHOP_ATR_MULT * self._atr:
            return None
        return "BUY" if spread > 0 else "SELL"

    def _pullback_armed(self, bar: Bar, side: Literal["BUY", "SELL"]) -> bool:
        """Price is within `pullback_atr_mult` * ATR of the fast EMA, on the
        trend's side (long: bar.low touches the EMA from above; short: bar.high
        touches from below)."""
        assert self._fast_ema is not None
        assert self._atr is not None
        threshold = self._pullback_atr_mult * self._atr
        if side == "BUY":
            return bar.low <= self._fast_ema + threshold
        return bar.high >= self._fast_ema - threshold

    def _open_intent(
        self, bar: Bar, *, side: Literal["BUY", "SELL"], atr: float,
    ) -> OrderIntent:
        market = get_market(self._symbol)
        tick = market.tick_size
        # Stop = fast_ema - 1*ATR for longs (mirror for shorts). Convert the
        # resulting price distance to ticks for the broker-agnostic Bracket.
        assert self._fast_ema is not None
        entry = bar.close
        if side == "BUY":
            stop_price = self._fast_ema - atr
            stop_distance = max(entry - stop_price, tick)
        else:
            stop_price = self._fast_ema + atr
            stop_distance = max(stop_price - entry, tick)
        stop_loss_ticks = max(1, round(stop_distance / tick))
        take_profit_ticks = max(1, round(stop_loss_ticks * self._reward_ratio))

        if side == "BUY":
            tp_price = entry + take_profit_ticks * tick
            sl_price = entry - stop_loss_ticks * tick
        else:
            tp_price = entry - take_profit_ticks * tick
            sl_price = entry + stop_loss_ticks * tick

        self._position = (side, entry, sl_price, tp_price)
        self._trades_today += 1
        self._intent_counter += 1
        return OrderIntent(
            symbol=self._symbol,
            side=side,
            quantity=1,
            order_type="BRACKET",
            client_order_id=f"trend-{self._day_key}-{self._intent_counter}",
            timestamp=bar.timestamp,
            bracket=Bracket(
                stop_loss_ticks=stop_loss_ticks,
                take_profit_ticks=take_profit_ticks,
            ),
        )

    # ---- Exit logic -----------------------------------------------------------

    def _maybe_exit(self, bar: Bar) -> OrderIntent | None:
        """Priority: EoD cutoff > TP/SL hit > trend reversal."""
        assert self._position is not None
        side, _entry, stop_price, tp_price = self._position

        # 1. EoD flat — unconditional.
        if self._is_after_cutoff(bar.timestamp):
            return self._close_intent(bar, side)

        # 2. TP / SL hit — bar's range reaches the bracket level.
        hit_tp = (
            (side == "BUY" and bar.high >= tp_price)
            or (side == "SELL" and bar.low <= tp_price)
        )
        hit_sl = (
            (side == "BUY" and bar.low <= stop_price)
            or (side == "SELL" and bar.high >= stop_price)
        )
        if hit_tp or hit_sl:
            return self._close_intent(bar, side)

        # 3. Trend reversal — EMAs cross back through the chop band.
        if self._fast_ema is not None and self._slow_ema is not None:
            spread = self._fast_ema - self._slow_ema
            if side == "BUY" and spread <= 0:
                return self._close_intent(bar, side)
            if side == "SELL" and spread >= 0:
                return self._close_intent(bar, side)

        return None

    def _close_intent(self, bar: Bar, side: Literal["BUY", "SELL"]) -> OrderIntent:
        close_side: Literal["BUY", "SELL"] = "SELL" if side == "BUY" else "BUY"
        self._intent_counter += 1
        intent = OrderIntent(
            symbol=self._symbol,
            side=close_side,
            quantity=1,
            order_type="MARKET",
            client_order_id=f"trend-{self._day_key}-{self._intent_counter}",
            timestamp=bar.timestamp,
        )
        self._position = None
        return intent
