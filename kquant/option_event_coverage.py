"""Reviewed option-only calendar coverage; absence of rows is not absence of events."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .stock_store import connect

CATEGORIES = ("earnings", "dividends", "corporate", "macro")


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Calendar timestamps require an explicit timezone.")
    return result.astimezone(UTC)


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
    if not item["events"] and item.get("no_events_confirmed") is not True:
        raise ValueError("An empty calendar must explicitly confirm no events in its coverage window.")
    for event in item["events"]:
        start, end = timestamp(event["start_at"]), timestamp(event["end_at"])
        if end < start or not times["coverage_start"] <= start <= end <= times["coverage_end"]:
            raise ValueError("Event must fit inside its coverage window.")
        if not isinstance(event.get("blocks_entry"), bool) or not event.get("name"):
            raise ValueError("Event name and explicit blocks_entry are required.")
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


def option_event_context(db_path: Path, symbol: str, as_of: str | None = None, *, until: str | None = None) -> dict:
    current = timestamp(as_of) if as_of else datetime.now(UTC)
    end = timestamp(until) if until else current + timedelta(days=7)
    with connect(db_path) as conn:
        rows = conn.execute("""SELECT * FROM option_event_coverage
            WHERE symbol IN (?, '*') ORDER BY recorded_at DESC, coverage_id""", (symbol.upper(),)).fetchall()
    selected, missing, blocking = {}, [], []
    for category in CATEGORIES:
        eligible = [dict(row) for row in rows if row["category"] == category
                    and row["symbol"] == ("*" if category == "macro" else symbol.upper())
                    and timestamp(row["recorded_at"]) <= current
                    and timestamp(row["available_at"]) <= current
                    and timestamp(row["reviewed_at"]) <= current]
        latest = eligible[0] if eligible else None
        if (latest is None or timestamp(latest["valid_until"]) <= current
                or timestamp(latest["coverage_start"]) > current or timestamp(latest["coverage_end"]) < end):
            missing.append(category)
            continue
        selected[category] = latest["coverage_id"]
        for event in json.loads(latest["payload_json"])["events"]:
            if event["blocks_entry"] and timestamp(event["end_at"]) >= current and timestamp(event["start_at"]) <= end:
                blocking.append({"category": category, **event, "coverage_id": latest["coverage_id"]})
    return {
        "status": "incomplete" if missing else ("event_blocked" if blocking else "reviewed"),
        "as_of": current.isoformat(), "coverage_until": end.isoformat(),
        "trade_eligible": not missing and not blocking,
        "missing_categories": missing, "blocking_events": blocking,
        "coverage_ids": selected, "option_only": True,
    }
