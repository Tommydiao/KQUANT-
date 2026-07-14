from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .longbridge_provider import longbridge_runtime
from .market_clock import is_early_close, is_trading_day, session_bounds_utc
from .stock_store import connect


def _configured() -> bool:
    return all(
        os.getenv(name)
        for name in ("LONGBRIDGE_APP_KEY", "LONGBRIDGE_APP_SECRET", "LONGBRIDGE_ACCESS_TOKEN")
    )


def _dates(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(item)[:10] for item in value}
    return {str(value)[:10]}


def _longbridge_day(day: date, timeout_seconds: int) -> tuple[bool, bool]:
    from longbridge.openapi import Market  # type: ignore

    response = longbridge_runtime().trading_days(Market.US, day, day, timeout_seconds)
    trading = getattr(response, "trading_days", None)
    half = getattr(response, "half_trading_days", None)
    if trading is None and isinstance(response, (tuple, list)):
        trading = response[0] if response else []
        half = response[1] if len(response) > 1 else []
    key = day.isoformat()
    return key in _dates(trading), key in _dates(half)


def market_schedule(day: date, db_path: Path, timeout_seconds: int = 5) -> dict[str, Any]:
    cached: dict[str, Any] | None = None
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM market_calendar_cache WHERE market_date = ?",
            (day.isoformat(),),
        ).fetchone()
        cached = dict(row) if row else None
    if cached and (cached["source"] == "longbridge" or not _configured()):
        return {
            "market_date": day.isoformat(),
            "is_trading_day": bool(cached["is_trading_day"]),
            "is_early_close": bool(cached["is_half_day"]),
            "regular_open_utc": cached["regular_open_utc"],
            "regular_close_utc": cached["regular_close_utc"],
            "calendar_source": cached["source"],
            "cache_hit": True,
        }
    source = "exchange_calendars:XNYS"
    try:
        trading, half = _longbridge_day(day, timeout_seconds) if _configured() else (is_trading_day(day), is_early_close(day))
        if _configured():
            source = "longbridge"
    except Exception:
        trading, half = is_trading_day(day), is_early_close(day)
    market_open = market_close = None
    if trading:
        market_open_dt, market_close_dt = session_bounds_utc(day)
        market_open, market_close = market_open_dt.isoformat(), market_close_dt.isoformat()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO market_calendar_cache(
              market_date, is_trading_day, is_half_day, source,
              regular_open_utc, regular_close_utc, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                day.isoformat(), int(trading), int(half), source,
                market_open, market_close, datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    return {
        "market_date": day.isoformat(),
        "is_trading_day": trading,
        "is_early_close": half,
        "regular_open_utc": market_open,
        "regular_close_utc": market_close,
        "calendar_source": source,
        "cache_hit": False,
    }
