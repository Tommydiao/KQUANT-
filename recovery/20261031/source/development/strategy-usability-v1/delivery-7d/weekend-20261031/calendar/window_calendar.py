"""Read-only calendar/denominator adapter; does not register or execute tasks."""
from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

from first_hour import WINDOW_ID, schedule
from kquant.market_clock import is_early_close, session_bounds_utc
from kquant.options_opening_trend import exit_times

DISPLAY = ZoneInfo("Asia/Shanghai")
EXCHANGE = ZoneInfo("America/New_York")
POSITION_STATES = frozenset({"COMPLETE", "WAIT_INPUT", "DATA_BLOCKED", "NOT_APPLICABLE",
                             "DEADLINE_UNPROCESSED", "ATTRIBUTED_SYSTEM_OMISSION"})


def instant(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("AWARE_INSTANT_REQUIRED")
    return value.astimezone(UTC)


def budget_date(value: datetime, timezone: str = "Asia/Shanghai") -> str:
    """A date bucket, never an elapsed-hour or local-hour bucket."""
    return instant(value).astimezone(ZoneInfo(timezone)).date().isoformat()


def _times(value: datetime) -> dict:
    value = instant(value)
    return {"utc": value.isoformat(), "exchange": value.astimezone(EXCHANGE).isoformat(),
            "display": value.astimezone(DISPLAY).isoformat()}


def window(day: date, denominator: dict) -> dict:
    actual = schedule(day)
    items = denominator["items"]
    registered = [item["symbol"] for item in items]
    applicable = list(denominator["applicable"])
    if len(set(registered)) != len(registered) or len(set(applicable)) != len(applicable):
        raise ValueError("DENOMINATOR_DUPLICATE")
    if not set(applicable) <= set(registered):
        raise ValueError("APPLICABLE_OUTSIDE_REGISTERED_SCOPE")
    count = len(actual["checkpoints"])
    result = {"schema": "FIRST_HOUR_CALENDAR_AUDIT_V1", "window_id": actual["window_id"],
              "session": day.isoformat(), "state": actual["state"],
              "calendar_source": "exchange_calendars:XNYS", "registered": len(items),
              "applicable": len(applicable), "unresolved": len(items) - len(applicable),
              "scope_hash": denominator["scope_hash"], "checkpoint_count": count,
              "positions_per_variant": len(applicable) * 2 * count,
              "identity_unresolved_positions_per_variant": (len(items) - len(applicable)) * 2 * count,
              "scheduled_or_registered": False, "checkpoints": []}
    if not count:
        return result
    opening, closing = session_bounds_utc(day)
    result.update(opening=_times(opening), closing=_times(closing), early_close=is_early_close(day),
                  prewarm=_times(opening - timedelta(minutes=60)),
                  readiness=_times(opening - timedelta(minutes=5)),
                  cutoff=_times(actual["cutoff"]), reconciliation_at=_times(actual["reconciliation_at"]))
    for cp in actual["checkpoints"]:
        if not opening < cp["at"] < actual["cutoff"] or not cp["at"] < cp["deadline"] <= min(cp["at"] + timedelta(seconds=300), actual["cutoff"]):
            raise ValueError("ORIGINAL_WINDOW_DEADLINE_INVALID")
        result["checkpoints"].append({"at": _times(cp["at"]), "deadline": _times(cp["deadline"])})
    return result


def position_id(*, session: str, strategy_version: str, symbol: str, right: str,
                checkpoint: datetime, scope_hash: str) -> str:
    if right not in {"CALL", "PUT"}:
        raise ValueError("INVALID_DIRECTION")
    if instant(checkpoint).astimezone(EXCHANGE).date().isoformat() != session:
        raise ValueError("CHECKPOINT_SESSION_MISMATCH")
    payload = [WINDOW_ID, strategy_version, scope_hash, session, symbol, right, instant(checkpoint).isoformat()]
    return sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def expected_positions(day: date, denominator: dict, strategy_version: str) -> set[str]:
    return {position_id(session=day.isoformat(), strategy_version=strategy_version, symbol=symbol,
                        right=right, checkpoint=cp["at"], scope_hash=denominator["scope_hash"])
            for symbol in denominator["applicable"] for right in ("CALL", "PUT")
            for cp in schedule(day)["checkpoints"]}


def reconcile(expected: set[str], records: list[dict]) -> dict:
    """Audit explicit outcomes only; missing historical rows are not proof of loss."""
    latest = {}
    for row in records:
        key = row["position_id"]
        if key not in expected or row["state"] not in POSITION_STATES:
            raise ValueError("RECONCILIATION_SCOPE_OR_STATE_INVALID")
        revision = row["revision"]
        if type(revision) is not int or revision < 0:
            raise ValueError("INVALID_REVISION")
        old = latest.get(key)
        if old and old["revision"] == revision and row != old:
            raise ValueError("CONFLICTING_SAME_REVISION")
        if old is None or revision > old["revision"]:
            latest[key] = row
    counts = Counter(row["state"] for row in latest.values())
    return {"expected": len(expected), "recorded_positions": len(latest),
            "raw_records_including_revisions": len(records),
            "outcomes": {state: counts[state] for state in sorted(POSITION_STATES)},
            "missing_evidence_positions": len(expected - latest.keys()),
            "unattributed_system_omission_count": None,
            "missing_evidence_is_not_no_trigger_or_proven_loss": True}


def manual_exit(day: date, entered: datetime, policy: dict) -> dict:
    opening, closing = session_bounds_utc(day)
    entered = instant(entered)
    if not opening <= entered < closing:
        raise ValueError("ENTRY_OUTSIDE_SESSION")
    result = exit_times(opening, closing, entered, policy=policy)
    return {key: _times(datetime.fromisoformat(value)) for key, value in result.items()}


def seconds_remaining(deadline: datetime, now: datetime) -> float:
    return max(0.0, (instant(deadline) - instant(now)).total_seconds())
