from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .stock_store import connect


DEFAULT_MONTHLY_SYMBOL_QUOTA = 100
MAX_DOCUMENTED_MONTHLY_SYMBOL_QUOTA = 3000


def _month_key(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m")


def _next_month_start(now: datetime | None = None) -> str:
    """Return the next UTC calendar-month boundary without calling a provider."""

    current = (now or datetime.now(UTC)).astimezone(UTC)
    year = current.year + (1 if current.month == 12 else 0)
    month = 1 if current.month == 12 else current.month + 1
    return datetime(year, month, 1, tzinfo=UTC).isoformat()


def _monthly_symbol_quota(value: int | None = None) -> int:
    raw = value if value is not None else os.getenv("KQUANT_LONGBRIDGE_MONTHLY_SYMBOL_CAP", DEFAULT_MONTHLY_SYMBOL_QUOTA)
    try:
        quota = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("KQUANT_LONGBRIDGE_MONTHLY_SYMBOL_CAP must be an integer.") from exc
    if not 1 <= quota <= MAX_DOCUMENTED_MONTHLY_SYMBOL_QUOTA:
        raise ValueError(
            f"Longbridge monthly symbol cap must be between 1 and {MAX_DOCUMENTED_MONTHLY_SYMBOL_QUOTA}."
        )
    return quota


def backfill_quota_status(
    *,
    db_path: Path,
    requested_symbols: list[str] | None = None,
    monthly_symbol_cap: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a conservative local audit of Longbridge monthly symbol usage.

    Longbridge charges historical K-line access by unique symbol per calendar
    month. KQUANT cannot query a provider-side balance, so a provider quota
    error is a local lock for the current month, not a promise that the next
    month is already available.
    """

    month = _month_key(now)
    quota = _monthly_symbol_quota(monthly_symbol_cap)
    requested = sorted({str(symbol).upper().strip() for symbol in (requested_symbols or []) if str(symbol).strip()})
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT i.symbol
            FROM market_backfill_job_items AS i
            INNER JOIN market_backfill_jobs AS j ON j.job_id = i.job_id
            WHERE substr(j.requested_at, 1, 7) = ?
            """,
            (month,),
        ).fetchall()
        provider_quota_error = conn.execute(
            """
            SELECT 1
            FROM market_backfill_job_items AS i
            INNER JOIN market_backfill_jobs AS j ON j.job_id = i.job_id
            WHERE substr(j.requested_at, 1, 7) = ?
              AND (i.last_error LIKE '%301607%' OR i.result_json LIKE '%301607%')
            LIMIT 1
            """,
            (month,),
        ).fetchone()
    tracked = {str(row["symbol"]).upper() for row in rows}
    new_symbols = sorted(set(requested) - tracked)
    remaining = max(0, quota - len(tracked))
    provider_quota_locked = provider_quota_error is not None
    allowed = not provider_quota_locked and len(new_symbols) <= remaining
    if provider_quota_locked:
        status = "provider_quota_exhausted"
    elif not allowed:
        status = "blocked_new_symbols_exceed_cap"
    elif len(tracked) > quota:
        status = "tracked_usage_exceeds_default_reuse_only"
    else:
        status = "ready"
    return {
        "month": month,
        "configured_monthly_symbol_cap": quota,
        "documented_cap_range": [DEFAULT_MONTHLY_SYMBOL_QUOTA, MAX_DOCUMENTED_MONTHLY_SYMBOL_QUOTA],
        "tracked_unique_symbols": len(tracked),
        "requested_unique_symbols": len(requested),
        "new_unique_symbols": len(new_symbols),
        "remaining_new_symbol_capacity": remaining,
        "status": status,
        "allowed": allowed,
        "provider_remaining_quota_known": False,
        "provider_quota_lock": provider_quota_locked,
        "provider_error_code": "301607" if provider_quota_locked else None,
        "next_recheck_at": _next_month_start(now) if provider_quota_locked else None,
        "recovery_action": "recheck_next_calendar_month" if provider_quota_locked else "bounded_preflight_available",
        "read_only_market_data": True,
    }


__all__ = [
    "DEFAULT_MONTHLY_SYMBOL_QUOTA",
    "MAX_DOCUMENTED_MONTHLY_SYMBOL_QUOTA",
    "backfill_quota_status",
]
