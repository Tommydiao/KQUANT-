from __future__ import annotations

"""Conservative point-in-time availability for completed market candles."""

from datetime import UTC, datetime, timedelta
from typing import Any, Mapping


MARKET_AVAILABILITY_CONTRACT_VERSION = "market_bar_close_bound_v1"

_INTERVAL_DURATIONS = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
    "1wk": timedelta(days=7),
    "1mo": timedelta(days=31),
}

_INTERVAL_ALIASES = {
    "1m": "1m",
    "min1": "1m",
    "minute": "1m",
    "5m": "5m",
    "min5": "5m",
    "15m": "15m",
    "min15": "15m",
    "1h": "1h",
    "60m": "1h",
    "hour": "1h",
    "hourly": "1h",
    "1d": "1d",
    "day": "1d",
    "daily": "1d",
    "1wk": "1wk",
    "1w": "1wk",
    "week": "1wk",
    "weekly": "1wk",
    "1mo": "1mo",
    "month": "1mo",
    "monthly": "1mo",
}


def parse_utc(value: str | datetime, *, field: str = "timestamp") -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} is required.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be ISO-8601.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed.astimezone(UTC)


def normalize_interval(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("_", "")
    resolved = _INTERVAL_ALIASES.get(normalized)
    if resolved is None:
        raise ValueError(f"Unsupported candle interval: {value!r}")
    return resolved


def candle_available_at(candle_or_open_time: Mapping[str, Any] | str | datetime, interval: Any) -> datetime:
    """Return a conservative UTC bound for when a candle can inform a decision.

    Longbridge historical rows retain their retrieval timestamp separately. A
    completed bar is eligible from the end of its declared interval, not from
    the later local fetch time. Daily, weekly, and monthly bounds are
    deliberately conservative calendar bounds, which prevents same-bar use.
    """

    if isinstance(candle_or_open_time, Mapping):
        explicit = candle_or_open_time.get("market_available_at")
        if explicit:
            return parse_utc(explicit, field="candle.market_available_at")
        open_time = candle_or_open_time.get("open_time")
    else:
        open_time = candle_or_open_time
    start = parse_utc(open_time, field="candle.open_time")
    return start + _INTERVAL_DURATIONS[normalize_interval(interval)]


def candle_available_iso(candle_or_open_time: Mapping[str, Any] | str | datetime, interval: Any) -> str:
    return candle_available_at(candle_or_open_time, interval).isoformat()


def candle_is_available_at(
    candle_or_open_time: Mapping[str, Any] | str | datetime,
    interval: Any,
    cutoff: str | datetime,
) -> bool:
    return candle_available_at(candle_or_open_time, interval) <= parse_utc(cutoff, field="cutoff")


__all__ = [
    "MARKET_AVAILABILITY_CONTRACT_VERSION",
    "candle_available_at",
    "candle_available_iso",
    "candle_is_available_at",
    "normalize_interval",
    "parse_utc",
]
