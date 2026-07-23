from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


UTC = timezone.utc


def parse_as_of(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _bar_open_time(candle: dict[str, Any]) -> datetime | None:
    raw = candle.get("open_time")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return parse_as_of(raw)
    except ValueError:
        return None


def slice_completed_candles_as_of(candles: list[dict[str, Any]], as_of: str | datetime) -> list[dict[str, Any]]:
    """Return only valid completed bars whose recorded timestamp is not in the future."""
    cutoff = parse_as_of(as_of)
    rows = []
    for candle in candles:
        stamp = _bar_open_time(candle)
        if stamp is None or stamp > cutoff or candle.get("bar_state") == "forming_candle":
            continue
        rows.append(dict(candle))
    return sorted(rows, key=lambda item: str(item.get("open_time") or ""))


def replay_metadata(*, as_of: str | datetime, daily: list[dict[str, Any]], hourly: list[dict[str, Any]]) -> dict[str, Any]:
    cutoff = parse_as_of(as_of)
    return {
        "as_of": cutoff.isoformat(),
        "no_future_data": True,
        "daily_completed_bars": len(daily),
        "hourly_completed_bars": len(hourly),
        "daily_last_open_time": daily[-1].get("open_time") if daily else None,
        "hourly_last_open_time": hourly[-1].get("open_time") if hourly else None,
    }
