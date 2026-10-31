"""HTTP clock diagnostics only; never correct source events or the host clock."""
from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import math


def date_header_evidence(headers: dict, started: datetime, received: datetime, elapsed: float) -> dict:
    headers = {key.lower(): value for key, value in headers.items()}
    result = {"request_started_at": started.isoformat(), "received_at": received.isoformat(),
              "round_trip_seconds": elapsed, "source_event_time": None,
              "evidence_class": "HTTP_DATE_DIAGNOSTIC_ONLY", "strict_quote_evidence": False,
              "date_header": headers.get("date"), "age_header": headers.get("age"),
              "cache_status": headers.get("cf-cache-status") or headers.get("x-cache")}
    try:
        remote = parsedate_to_datetime(headers["date"])
        if remote.tzinfo is None:
            raise ValueError('missing_remote_timezone')
        remote = remote.astimezone(UTC)
        if started.tzinfo is None or received.tzinfo is None or received < started:
            raise ValueError("unordered_local_clock")
        if not math.isfinite(elapsed) or elapsed < 0 or abs((received - started).total_seconds() - elapsed) > 1:
            raise ValueError("local_clock_changed_during_request")
        age = float(headers.get("age", "0"))
        if not math.isfinite(age) or age != 0 or "hit" in str(result["cache_status"]).lower():
            raise ValueError("cached_response")
        # HTTP Date has one-second precision; bounds include it and the entire RTT.
        result.update(status="observed_not_authoritative", remote_http_date=remote.isoformat(),
            remote_minus_local_lower_seconds=(remote - received).total_seconds() - 1,
            remote_minus_local_upper_seconds=(remote - started).total_seconds() + 1)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        result.update(status="unusable", reason=str(exc) if isinstance(exc, ValueError) else "missing_or_invalid_date")
    return result
