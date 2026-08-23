from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping, Sequence


COLLECTION_GATE_VERSION = "crypto_collection_gate_v1.0.0"


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def evaluate_collection_gate(
    *,
    started_at: str,
    ended_at: str,
    requested_hours: float,
    required_symbols: Sequence[str],
    streams: Sequence[Mapping[str, Any]],
    providers: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate one collector session independently of persisted history."""

    start = _parse_time(started_at)
    end = _parse_time(ended_at)
    observed_hours = ((end - start).total_seconds() / 3600.0) if start and end and end >= start else None
    minimum_hours = max(23.0, float(requested_hours) * 0.95)
    required = {str(symbol).strip().upper() for symbol in required_symbols if str(symbol).strip()}
    eligible_streams = [
        item for item in streams
        if item.get("span_hours") is not None and float(item["span_hours"]) >= minimum_hours
    ]
    eligible_symbols = {
        str(item.get("instrument_id", "")).rsplit(":", 1)[-1].upper()
        for item in eligible_streams
    }
    sequence_gaps = sum(int(value.get("sequence_gaps") or 0) for value in providers.values())
    checks = [
        {
            "id": "session_duration",
            "passed": observed_hours is not None and observed_hours >= minimum_hours,
            "observed_hours": round(observed_hours, 4) if observed_hours is not None else None,
            "required_hours": minimum_hours,
        },
        {
            "id": "core_symbol_coverage",
            "passed": required.issubset(eligible_symbols),
            "missing_symbols": sorted(required - eligible_symbols),
            "eligible_symbols": sorted(eligible_symbols),
        },
        {
            "id": "sequence_integrity",
            "passed": sequence_gaps == 0,
            "sequence_gaps": sequence_gaps,
        },
    ]
    failed = [item["id"] for item in checks if not item["passed"]]
    return {
        "version": COLLECTION_GATE_VERSION,
        "status": "PASS" if not failed else "NO_GO",
        "passed": not failed,
        "evidence_scope": "independent_collector_session",
        "started_at": started_at,
        "ended_at": ended_at,
        "requested_hours": float(requested_hours),
        "minimum_hours": minimum_hours,
        "observed_hours": round(observed_hours, 4) if observed_hours is not None else None,
        "required_symbols": sorted(required),
        "eligible_symbols": sorted(eligible_symbols),
        "failed_checks": failed,
        "checks": checks,
        "note": "This gate never treats persisted backfill span as proof of one continuous session.",
    }
