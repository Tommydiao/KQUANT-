"""Pure closed-bar policy for the V2.0 dual-regime research candidate.

One instance per symbol. The caller owns positions, fills, timeouts (72/36
bars), cash, and pending orders. Call on_bar even while entries are suppressed.
The hourly argument is an externally verified complete hour ending exactly at
the supplied five-minute bar's close; it must only be supplied once.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Any


STRATEGY_VERSION = "crypto_spot_dual_regime_v1.0.0"
TRANSITION = "TRANSITION"
UP_TREND = "UP_TREND"
RANGE = "RANGE"
MAX_HOLD_BARS = {UP_TREND: 72, RANGE: 36}


@dataclass(frozen=True)
class Bar:
    start: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0

    def __post_init__(self) -> None:
        if type(self.start) is not int or self.start < 0:
            raise ValueError("start must be nonnegative integer UTC epoch seconds")
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(isfinite(v) for v in values):
            raise ValueError("bar values must be finite")
        if (self.low <= 0 or self.volume < 0
                or not self.low <= self.open <= self.high
                or not self.low <= self.close <= self.high):
            raise ValueError("invalid OHLCV")


@dataclass
class _Indicators:
    count: int = 0
    previous_close: float | None = None
    atr: float | None = None
    tr_seed: float = 0.0
    ema: float | None = None
    ema_seed: float = 0.0
    emas: list[float] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)

    def update(self, bar: Bar, *, hourly: bool = False) -> None:
        tr = bar.high - bar.low
        if self.previous_close is not None:
            tr = max(tr, abs(bar.high - self.previous_close),
                     abs(bar.low - self.previous_close))
        self.count += 1
        if self.count <= 14:
            self.tr_seed += tr
            if self.count == 14:
                self.atr = self.tr_seed / 14
        else:
            self.atr = (self.atr * 13 + tr) / 14
        self.previous_close = bar.close
        if hourly:
            if self.count <= 50:
                self.ema_seed += bar.close
                if self.count == 50:
                    self.ema = self.ema_seed / 50
            else:
                self.ema += (2 / 51) * (bar.close - self.ema)
            if self.ema is not None:
                self.emas = (self.emas + [self.ema])[-4:]
            self.closes = (self.closes + [bar.close])[-25:]

    @property
    def slope(self) -> float:
        return self.emas[-1] - self.emas[-4]

    @property
    def er(self) -> float:
        changes = sum(abs(b - a) for a, b in zip(self.closes, self.closes[1:]))
        return abs(self.closes[-1] - self.closes[0]) / changes if changes else 0.0


def expected_net_values(entry: float, stop: float, target: float) -> tuple[float, float]:
    """Return (net target profit, unit net stop loss), always BASE 10bp/5bp."""
    buy = entry * 1.0005
    win, loss = target * 0.9995, stop * 0.9995
    return win - buy - 0.001 * (buy + win), buy - loss + 0.001 * (buy + loss)


class DualRegimeKernel:
    """Deterministic mutable state; snapshots are detached JSON-compatible dicts.

    ready means continuous warmup and positive ATRs, not permission to trade.
    entry_ready additionally requires an active mode and completed cooldown.
    Set allow_entries=False for a position, pending order, or portfolio veto;
    this suppresses signals only, never indicator/state/cooldown updates.
    """

    def __init__(self, candidate: str = "A") -> None:
        if candidate not in ("A", "B"):
            raise ValueError("candidate must be A or B")
        self.candidate = candidate
        self.mode = TRANSITION
        self.box: dict[str, Any] | None = None
        self.confirm_mode = TRANSITION
        self.confirm_count = 0
        self.five = _Indicators()
        self.hour = _Indicators()
        self.five_bars: list[Bar] = []
        self.hour_bars: list[Bar] = []
        self.last_exit_time: int | None = None
        self.cooldown_remaining = 0
        self.exit_bar_pending = False
        self.pending_invalidation = False

    @property
    def ready(self) -> bool:
        return (self.five.count >= 100 and self.hour.count >= 250
                and (self.five.atr or 0) > 0 and (self.hour.atr or 0) > 0)

    @property
    def entry_ready(self) -> bool:
        return self.ready and self.mode != TRANSITION and self.cooldown_remaining == 0

    def _invalidate(self) -> None:
        self.mode = TRANSITION
        self.box = None
        self.confirm_mode = TRANSITION
        self.confirm_count = 0

    def record_exit(self, time: int, stopped: bool = False, mode: str = "") -> None:
        """Record an actual exit epoch, before on_bar for that enclosing bar.

        The enclosing exit bar never counts, whether an open-gap exit is stamped
        at its start or an intrabar exit at its close. Twelve subsequent whole
        5m intervals must close before entry is ready.
        RANGE stop exits invalidate immediately; the next decision reports it.
        Call once per exit, including target, timeout and external risk exits.
        """
        if type(time) is not int or time < 0:
            raise ValueError("exit time must be nonnegative integer seconds")
        if mode not in ("", UP_TREND, RANGE):
            raise ValueError("unknown exit mode")
        if self.last_exit_time is not None and time < self.last_exit_time:
            raise ValueError("exit times must be chronological")
        self.last_exit_time = time
        self.cooldown_remaining = 12
        self.exit_bar_pending = True
        if stopped and mode == RANGE:
            self._invalidate()
            self.pending_invalidation = True

    def _update_mode(self, close_time: int, reasons: list[str]) -> bool:
        h = self.hour
        close, ema, slope, er, atr = h.previous_close, h.ema, h.slope, h.er, h.atr
        if self.mode == UP_TREND:
            if close > ema and slope >= 0 and er >= 0.25:
                return False
            self._invalidate()
            reasons.append("TREND_INVALIDATED")
            return True
        if self.mode == RANGE:
            if er < 0.30 and abs(slope) <= 0.50 * atr:
                return False
            self._invalidate()
            reasons.append("RANGE_INVALIDATED")
            return True
        qualified = TRANSITION
        if close > ema and slope > 0 and er >= 0.35:
            qualified = UP_TREND
        elif er <= 0.20 and abs(slope) <= 0.25 * atr:
            qualified = RANGE
        if qualified == TRANSITION:
            self.confirm_mode, self.confirm_count = TRANSITION, 0
            return False
        self.confirm_count = self.confirm_count + 1 if qualified == self.confirm_mode else 1
        self.confirm_mode = qualified
        if self.confirm_count < 2:
            reasons.append("AWAITING_SECOND_HOUR")
            return False
        if qualified == RANGE:
            upper = max(b.high for b in self.hour_bars[-24:])
            lower = min(b.low for b in self.hour_bars[-24:])
            if upper <= lower:
                self._invalidate()
                reasons.append("BOX_NONPOSITIVE_WIDTH")
                return False
            self.box = {"upper": upper, "lower": lower, "width": upper - lower,
                        "midpoint": (upper + lower) / 2, "atr": atr,
                        "effective_at": close_time, "expires_at": close_time + 86400}
        self.mode = qualified
        self.confirm_mode, self.confirm_count = TRANSITION, 0
        reasons.append("MODE_ENTERED_" + qualified)
        return False

    def _signal(self, bar: Bar, reasons: list[str]) -> dict[str, Any] | None:
        if self.mode == UP_TREND:
            if bar.close <= max(b.high for b in self.five_bars[-21:-1]):
                reasons.append("TREND_NOT_TRIGGERED")
                return None
            stop = min(b.low for b in self.five_bars[-6:]) - 0.25 * self.five.atr
            target = bar.close + (2.5 if self.candidate == "A" else 3.0) * (bar.close - stop)
            minimum = 2.0
            trigger = "TREND_BREAKOUT"
        else:
            box = self.box
            previous = self.five_bars[-2]
            if previous.start < box["effective_at"]:
                reasons.append("RANGE_SIGNAL_BEFORE_EFFECTIVE")
                return None
            line = box["lower"] + 0.15 * box["width"]
            if not (previous.close <= line < bar.close
                    <= box["lower"] + 0.25 * box["width"]):
                reasons.append("RANGE_NOT_TRIGGERED")
                return None
            stop = box["lower"] - 0.20 * box["atr"]
            target = box["lower"] + (0.5 if self.candidate == "A" else 0.6) * box["width"]
            minimum = 1.5
            trigger = "RANGE_RECLAIM"
        distance = bar.close - stop
        if distance <= 0 or stop <= 0 or target <= bar.close:
            reasons.append("INVALID_PRICE_SPACE")
            return None
        if self.mode == RANGE and (target - bar.close) / distance < 1.8:
            reasons.append("GROSS_RR_INSUFFICIENT")
            return None
        profit, risk = expected_net_values(bar.close, stop, target)
        if risk <= 0 or profit <= 0 or profit / risk < minimum:
            reasons.append("NET_RR_INSUFFICIENT")
            return None
        reasons.append(trigger)
        return {"entry_reference": bar.close, "stop": stop, "target": target,
                "expected_net_rr": profit / risk, "unit_net_risk": risk,
                "mode": self.mode, "signal_time": bar.start + 300,
                "reason_codes": [trigger]}

    def on_bar(self, bar: Bar, hourly: Bar | None = None, *,
               allow_entries: bool = True) -> dict[str, Any]:
        """Consume one closed 5m bar, optionally its just-closed complete 1H.

        Misaligned, duplicate, backward or future inputs raise ValueError before
        mutation. Missing 5m/1H data resets both warmups; no synthetic bars.
        mode_invalidated is a one-decision exit/cancel flag, including gap and
        recorded range-stop events. A suppressed decision cannot be replayed.
        """
        if not isinstance(bar, Bar) or bar.start % 300:
            raise ValueError("bar must be a UTC-aligned 5m Bar")
        close_time = bar.start + 300
        if hourly is not None and (not isinstance(hourly, Bar)
                                   or hourly.start % 3600
                                   or hourly.start + 3600 != close_time):
            raise ValueError("hourly must end exactly at the 5m close")
        if self.five_bars and bar.start <= self.five_bars[-1].start:
            raise ValueError("5m bars must be unique and chronological")
        if hourly is not None and self.hour_bars and hourly.start <= self.hour_bars[-1].start:
            raise ValueError("hourly bars must be unique and chronological")
        reasons: list[str] = []
        invalidated = self.pending_invalidation
        self.pending_invalidation = False
        if invalidated:
            reasons.append("RANGE_STOP_INVALIDATED")
        gap = bool(self.five_bars and bar.start != self.five_bars[-1].start + 300)
        missing_hour = close_time % 3600 == 0 and hourly is None
        hour_gap = bool(hourly is not None and self.hour_bars
                        and hourly.start != self.hour_bars[-1].start + 3600)
        if gap or missing_hour or hour_gap:
            invalidated = invalidated or self.mode != TRANSITION
            self._invalidate()
            self.five, self.hour = _Indicators(), _Indicators()
            self.five_bars, self.hour_bars = [], []
            reasons.append("DATA_GAP_RESET")
        # A frozen box is checked against this 5m path before any hourly change.
        if self.mode == RANGE:
            box = self.box
            if (bar.low < box["lower"] - 0.20 * box["atr"]
                    or bar.high > box["upper"] + 0.20 * box["atr"]):
                self._invalidate()
                invalidated = True
                reasons.append("BOX_PRICE_INVALIDATED")
            elif close_time >= box["expires_at"]:
                self._invalidate()
                invalidated = True
                reasons.append("BOX_EXPIRED")
        self.five.update(bar)
        self.five_bars = (self.five_bars + [bar])[-21:]
        if hourly is not None:
            self.hour.update(hourly, hourly=True)
            self.hour_bars = (self.hour_bars + [hourly])[-25:]
        exit_bar = False
        if self.exit_bar_pending and close_time >= self.last_exit_time:
            exit_bar = bar.start <= self.last_exit_time
            self.exit_bar_pending = False
        if self.cooldown_remaining and not exit_bar and bar.start >= self.last_exit_time:
            self.cooldown_remaining -= 1
        if not self.ready:
            if self.mode != TRANSITION:
                invalidated = True
            self._invalidate()
            reasons.append("WARMUP_INCOMPLETE" if self.five.count < 100 or self.hour.count < 250
                           else "ATR_NONPOSITIVE")
        elif hourly is not None and not invalidated:
            invalidated = self._update_mode(close_time, reasons)
        signal = None
        if self.mode == TRANSITION:
            reasons.append("STATE_UNCONFIRMED")
        if self.cooldown_remaining:
            reasons.append("COOLDOWN")
        if not allow_entries:
            reasons.append("ENTRIES_SUPPRESSED")
        if self.entry_ready and allow_entries and not invalidated:
            signal = self._signal(bar, reasons)
        return {"mode": self.mode, "signal": signal, "reason_codes": reasons,
                "mode_invalidated": invalidated, "ready": self.ready,
                "entry_ready": self.entry_ready and allow_entries and not invalidated}

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, versioned JSON checkpoint (no I/O)."""
        result = deepcopy(vars(self))
        result.update(schema_version=1, strategy_version=STRATEGY_VERSION,
                      five=asdict(self.five), hour=asdict(self.hour),
                      five_bars=[asdict(b) for b in self.five_bars],
                      hour_bars=[asdict(b) for b in self.hour_bars])
        return result

    @classmethod
    def from_dict(cls, state: dict[str, Any]) -> DualRegimeKernel:
        """Restore a checkpoint created by to_dict; reject incompatible schemas."""
        data = deepcopy(state)
        if data.pop("schema_version", None) != 1 or data.pop("strategy_version", None) != STRATEGY_VERSION:
            raise ValueError("incompatible kernel checkpoint")
        obj = cls(data["candidate"])
        if data.keys() != vars(obj).keys():
            raise ValueError("invalid kernel checkpoint fields")
        data["five"] = _Indicators(**data["five"])
        data["hour"] = _Indicators(**data["hour"])
        data["five_bars"] = [Bar(**b) for b in data["five_bars"]]
        data["hour_bars"] = [Bar(**b) for b in data["hour_bars"]]
        if data["mode"] not in (TRANSITION, UP_TREND, RANGE):
            raise ValueError("invalid checkpoint mode")
        if (data["mode"] == RANGE) != (data["box"] is not None):
            raise ValueError("inconsistent checkpoint box")
        vars(obj).update(data)
        return obj


__all__ = ["Bar", "DualRegimeKernel", "STRATEGY_VERSION", "TRANSITION",
           "UP_TREND", "RANGE", "MAX_HOLD_BARS", "expected_net_values"]
