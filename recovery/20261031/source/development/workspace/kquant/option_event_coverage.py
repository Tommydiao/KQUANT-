"""Reviewed option-only calendar coverage; absence of rows is not absence of events."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .stock_store import connect
from .option_calendar_source import source_observations

CATEGORIES = ("earnings", "dividends", "corporate", "macro")


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Calendar timestamps require an explicit timezone.")
    return result.astimezone(UTC)


def validate_events(events, *, coverage_start: datetime, coverage_end: datetime,
                    risk_state: str | None = None) -> None:
    if not isinstance(events, list):
        raise ValueError("EVENTS_MUST_BE_ARRAY")
    blocking = False
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("EVENT_MUST_BE_OBJECT")
        if (not isinstance(event.get("name"), str) or not event["name"].strip()
                or not isinstance(event.get("blocks_entry"), bool)):
            raise ValueError("EVENT_NAME_AND_BLOCKING_FLAG_REQUIRED")
        try:
            if not all(isinstance(event.get(key), str) for key in ("start_at", "end_at")):
                raise ValueError("TIME_STRING_REQUIRED")
            start, end = timestamp(event["start_at"]), timestamp(event["end_at"])
        except ValueError as error:
            raise ValueError("EVENT_TIME_INVALID_OR_TIMEZONE_MISSING") from error
        if not coverage_start <= start <= end <= coverage_end:
            raise ValueError("EVENT_OUTSIDE_COVERAGE_WINDOW")
        blocking = blocking or event["blocks_entry"]
    if risk_state == "KNOWN_BLOCKER" and not blocking:
        raise ValueError("KNOWN_BLOCKER_NEEDS_BLOCKING_EVENT")
    if risk_state == "CLEAR" and blocking:
        raise ValueError("CLEAR_CANNOT_CONTAIN_BLOCKER")


def import_coverage(db_path: Path, payload: dict, *, now: datetime | None = None) -> str:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    item = dict(payload)
    for field in ("symbol", "category", "reviewer", "source_url", "source_hash"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise ValueError(f"Missing {field}.")
    if item["category"] not in CATEGORIES or urlparse(item["source_url"]).scheme != "https":
        raise ValueError("Use a registered category and HTTPS source URL.")
    if len(item["source_hash"]) != 64 or any(c not in "0123456789abcdef" for c in item["source_hash"]):
        raise ValueError("source_hash must be the SHA256 of the reviewed source content.")
    times = {key: timestamp(item[key]) for key in (
        "coverage_start", "coverage_end", "available_at", "reviewed_at", "valid_until"
    )}
    if not times["coverage_start"] < times["coverage_end"]:
        raise ValueError("Invalid coverage window.")
    if not times["available_at"] <= times["reviewed_at"] <= current < times["valid_until"]:
        raise ValueError("Review is future-dated or expired.")
    if item.get("review_status") != "reviewed" or not isinstance(item.get("events"), list):
        raise ValueError("Explicit reviewed status and events list are required.")
    if not isinstance(item.get('coverage_complete', True), bool):
        raise ValueError('coverage_complete must be boolean.')
    if not item.get('coverage_complete', True) and not item['events']:
        raise ValueError('Partial coverage must identify known events, not imply an empty calendar.')
    if not item["events"] and item.get("no_events_confirmed") is not True:
        raise ValueError("An empty calendar must explicitly confirm no events in its coverage window.")
    validate_events(item["events"], coverage_start=times["coverage_start"],
                    coverage_end=times["coverage_end"], risk_state=item.get("risk_state"))
    encoded = json.dumps(item, sort_keys=True, separators=(",", ":"))
    identity = hashlib.sha256(encoded.encode()).hexdigest()
    with connect(db_path) as conn:
        conn.execute("""INSERT OR IGNORE INTO option_event_coverage VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            identity, item["symbol"].upper(), item["category"],
            *(times[key].isoformat() for key in ("coverage_start", "coverage_end", "available_at", "reviewed_at", "valid_until")),
            item["reviewer"], item["source_url"], item["source_hash"], encoded, current.isoformat(),
        ))
        conn.commit()
    return identity


def option_event_context(db_path: Path, symbol: str, as_of: str | None = None, *, until: str | None = None,
                         policy_id: str | None = None, policy_hash: str = "", scope_hash: str = "") -> dict:
    if policy_id == "STRAT-SHORT-ATM-RANGE-EXPANSION-2H-V1":
        from .option_event_coverage_v3 import v3_event_context
        return v3_event_context(db_path, symbol, as_of, until=until,
                                policy_hash=policy_hash, scope_hash=scope_hash)
    current = timestamp(as_of) if as_of else datetime.now(UTC)
    end = timestamp(until) if until else current + timedelta(days=7)
    rows = []
    if Path(db_path).exists():
        with sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='option_event_coverage'").fetchone():
                rows = conn.execute("""SELECT * FROM option_event_coverage
                    WHERE symbol IN (?, '*') ORDER BY recorded_at DESC, coverage_id""", (symbol.upper(),)).fetchall()
    selected, missing, stale, blocking, sources = {}, [], [], [], {}
    for category in CATEGORIES:
        eligible = [dict(row) for row in rows if row["category"] == category
                    and row["symbol"] == ("*" if category == "macro" else symbol.upper())
                    and timestamp(row["recorded_at"]) <= current
                    and timestamp(row["available_at"]) <= current
                    and timestamp(row["reviewed_at"]) <= current]
        latest = eligible[0] if eligible else None
        if (latest is None or timestamp(latest["valid_until"]) <= current
                or timestamp(latest["coverage_start"]) > current or timestamp(latest["coverage_end"]) < current):
            missing.append(category)
            if latest is not None:
                stale.append(category)
            continue
        selected[category] = latest["coverage_id"]
        sources[category] = {key: latest[key] for key in (
            "source_url", "source_hash", "coverage_start", "coverage_end", "available_at", "reviewed_at", "valid_until")}
        payload = json.loads(latest['payload_json'])
        if timestamp(latest["coverage_end"]) < end or not payload.get('coverage_complete', True):
            missing.append(category)
        # Partial horizon coverage cannot clear entry, but a known event still matters.
        for event in payload['events']:
            if event["blocks_entry"] and timestamp(event["end_at"]) >= current and timestamp(event["start_at"]) <= end:
                blocking.append({"category": category, **event, "coverage_id": latest["coverage_id"]})
    return {
        "status": "STALE" if stale else "incomplete" if missing else ("event_blocked" if blocking else "reviewed"),
        "as_of": current.isoformat(), "coverage_until": end.isoformat(),
        "trade_eligible": not missing and not blocking,
        "missing_categories": missing, "blocking_events": blocking,
        "stale_categories": stale,
        "coverage_ids": selected, "option_only": True,
        "sources": sources,
        "coverage_quality": "PARTIAL" if selected and missing else "NOT_CHECKED" if missing else "COVERED_AS_OF",
        "known_risk_state": "KNOWN_BLOCKER" if blocking else "UNKNOWN" if missing else "CLEAR_UNDER_POLICY",
        "source_observations": source_observations(db_path, symbol),
    }
