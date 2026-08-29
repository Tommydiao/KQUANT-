from __future__ import annotations

"""Read-only classification of the independent market-data collector."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


COLLECTION_HEARTBEAT_STALE_SECONDS = 180.0


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def classify_collection_session(
    value: dict[str, Any],
    *,
    now: datetime | None = None,
    stale_after_seconds: float = COLLECTION_HEARTBEAT_STALE_SECONDS,
) -> dict[str, Any]:
    """Classify a session without treating a stale marker as a live process."""

    result = dict(value)
    if str(result.get("status") or "").lower() != "running":
        return result
    current = now or datetime.now(UTC)
    current = current if current.tzinfo else current.replace(tzinfo=UTC)
    heartbeat = _parse_time(result.get("heartbeat_at") or result.get("started_at"))
    if heartbeat is None:
        result["status"] = "stale"
        result["collector_liveness"] = "stale"
        result["failed_checks"] = ["collector_heartbeat_missing"]
        return result
    age = max(0.0, (current - heartbeat.astimezone(UTC)).total_seconds())
    result["heartbeat_age_seconds"] = round(age, 3)
    if age > max(30.0, float(stale_after_seconds)):
        result["status"] = "stale"
        result["collector_liveness"] = "stale"
        result["failed_checks"] = ["collector_heartbeat_stale"]
    else:
        result["collector_liveness"] = "running"
    return result


def read_collection_session(
    outputs_dir: Path,
    *,
    now: datetime | None = None,
    stale_after_seconds: float = COLLECTION_HEARTBEAT_STALE_SECONDS,
) -> dict[str, Any]:
    """Read the active marker first, then the last completed report."""

    running_path = Path(outputs_dir) / "crypto_collection_running.json"
    latest_path = Path(outputs_dir) / "crypto_collection_latest.json"
    if running_path.exists():
        try:
            value = json.loads(running_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return classify_collection_session(
                    value, now=now, stale_after_seconds=stale_after_seconds
                )
        except (OSError, UnicodeError, ValueError, TypeError):
            return {
                "status": "stale",
                "collector_liveness": "stale",
                "failed_checks": ["collector_marker_invalid"],
            }
    if latest_path.exists():
        try:
            value = json.loads(latest_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return {
                    **value,
                    "status": "completed",
                    "collector_liveness": "completed",
                }
        except (OSError, UnicodeError, ValueError, TypeError):
            return {
                "status": "stale",
                "collector_liveness": "stale",
                "failed_checks": ["collection_report_invalid"],
            }
    return {
        "status": "not_collected",
        "collector_liveness": "not_collected",
        "market_data_only": True,
        "paper_or_order_access": False,
    }


def read_collection_gate(
    outputs_dir: Path,
    *,
    now: datetime | None = None,
    stale_after_seconds: float = COLLECTION_HEARTBEAT_STALE_SECONDS,
) -> dict[str, Any]:
    """Return the persisted continuous-collection Gate from one source of truth."""

    session = read_collection_session(
        outputs_dir,
        now=now,
        stale_after_seconds=stale_after_seconds,
    )
    status = str(session.get("status") or "").lower()
    if status == "completed":
        return session.get("collection_gate") or {
            "status": "NO_GO",
            "evidence_scope": "independent_collector_session",
            "failed_checks": ["invalid_collection_report"],
        }
    if status == "stale":
        return {
            "status": "NO_GO",
            "evidence_scope": "independent_collector_session",
            "failed_checks": list(session.get("failed_checks") or ["collector_stale"]),
            "heartbeat": session,
        }
    return {
        "status": "PENDING",
        "evidence_scope": "independent_collector_session",
        "failed_checks": ["collector_report_pending"],
        "heartbeat": session,
    }


__all__ = [
    "COLLECTION_HEARTBEAT_STALE_SECONDS",
    "classify_collection_session",
    "read_collection_gate",
    "read_collection_session",
]
