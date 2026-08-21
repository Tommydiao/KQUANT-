from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .market_availability import (
    MARKET_AVAILABILITY_CONTRACT_VERSION,
    candle_available_at,
    parse_utc,
)
from .stock_store import connect


DATA_SNAPSHOT_CONTRACT_VERSION = "data_snapshot_v1.1.0"
SOURCE_POLICY_VERSION = "market_source_eligibility_v1"
MODEL_ELIGIBLE_SOURCE = "longbridge_candles"
REFERENCE_ONLY_SOURCES = {
    "live_yahoo_chart",
    "stale_yahoo_chart_cache",
    "yahoo_public",
    "yahoo_public_fallback",
    "fixture_read_only",
}


def _utc(value: str | datetime | None = None) -> str:
    if value is None:
        stamp = datetime.now(UTC)
    elif isinstance(value, datetime):
        stamp = value
    else:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Snapshot timestamps must include a timezone.")
    return stamp.astimezone(UTC).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def source_eligibility(*, source: str, provider_status: str, bar_state: str) -> dict[str, str | bool]:
    """Classify one candle without silently promoting reference data."""

    normalized_source = str(source or "unknown")
    if str(bar_state or "") != "closed_candle":
        return {"eligible": False, "status": "excluded", "reason": "forming_or_unknown_bar_state"}
    if normalized_source in REFERENCE_ONLY_SOURCES:
        return {"eligible": False, "status": "reference_only", "reason": "reference_source"}
    if normalized_source != MODEL_ELIGIBLE_SOURCE:
        return {"eligible": False, "status": "excluded", "reason": "unsupported_source"}
    if str(provider_status or "") != "available":
        return {"eligible": False, "status": "excluded", "reason": "provider_not_available"}
    return {"eligible": True, "status": "eligible", "reason": ""}


def create_market_data_snapshot(
    db_path: Path,
    *,
    symbol: str,
    intervals: Iterable[str],
    as_of_time: str | datetime | None = None,
    purpose: str = "model_input",
    universe_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist an immutable, point-in-time view of canonical market candles.

    `available_at` is the conservative end-of-bar availability bound while
    `fetched_at` remains the local retrieval audit time. This lets historical
    replay use provider history only after the relevant bar could have closed,
    without pretending that a later backfill was a prospective observation.
    """

    normalized_symbol = str(symbol or "").upper().strip()
    normalized_intervals = tuple(sorted({str(value).strip().lower() for value in intervals if str(value).strip()}))
    if not normalized_symbol:
        raise ValueError("symbol is required")
    if not normalized_intervals:
        raise ValueError("at least one interval is required")
    cutoff = _utc(as_of_time)
    placeholders = ",".join("?" for _ in normalized_intervals)
    query = f"""
        SELECT symbol, interval, open_time, adjustment_mode, dataset_version,
               primary_source, provider_symbol, provider_status, freshness_seconds,
               bar_state, open, high, low, close, volume, fetched_at
        FROM market_candles
        WHERE symbol = ?
          AND interval IN ({placeholders})
          AND open_time <= ?
        ORDER BY interval, open_time, adjustment_mode, dataset_version
    """
    with connect(db_path) as conn:
        rows = [dict(row) for row in conn.execute(query, (normalized_symbol, *normalized_intervals, cutoff)).fetchall()]

    selected: list[dict[str, Any]] = []
    exclusions: dict[str, int] = {}
    present_intervals: set[str] = set()
    historical_backfill_item_count = 0
    for row in rows:
        try:
            market_available_at = candle_available_at(row, row["interval"])
        except ValueError:
            exclusions["invalid_market_availability"] = exclusions.get("invalid_market_availability", 0) + 1
            continue
        if market_available_at > parse_utc(cutoff, field="as_of_time"):
            exclusions["not_available_at_cutoff"] = exclusions.get("not_available_at_cutoff", 0) + 1
            continue
        eligibility = source_eligibility(
            source=str(row["primary_source"]),
            provider_status=str(row["provider_status"]),
            bar_state=str(row["bar_state"]),
        )
        if eligibility["reason"] == "forming_or_unknown_bar_state":
            exclusions["forming_or_unknown_bar_state"] = exclusions.get("forming_or_unknown_bar_state", 0) + 1
            continue
        present_intervals.add(str(row["interval"]))
        item_payload = {
            "symbol": row["symbol"],
            "interval": row["interval"],
            "open_time": row["open_time"],
            "adjustment_mode": row["adjustment_mode"],
            "dataset_version": row["dataset_version"],
            "source": row["primary_source"],
            "provider_symbol": row["provider_symbol"],
            "provider_status": row["provider_status"],
            "freshness_seconds": row["freshness_seconds"],
            "bar_state": row["bar_state"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
            "market_available_at": market_available_at.isoformat(),
        }
        item_key = ":".join(
            [
                "market_candle",
                str(row["symbol"]),
                str(row["interval"]),
                str(row["open_time"]),
                str(row["adjustment_mode"]),
                str(row["dataset_version"]),
            ]
        )
        selected.append(
            {
                "item_key": item_key,
                "item_type": "market_candle",
                "symbol": str(row["symbol"]),
                "interval": str(row["interval"]),
                "source": str(row["primary_source"]),
                "as_of_time": str(row["open_time"]),
                "available_at": market_available_at.isoformat(),
                "fetched_at": str(row["fetched_at"]),
                "eligibility_status": str(eligibility["status"]),
                "exclusion_reason": str(eligibility["reason"]),
                "content_hash": _hash(item_payload),
                "payload": item_payload,
            }
        )
        try:
            if parse_utc(row["fetched_at"], field="candle.fetched_at") > market_available_at:
                historical_backfill_item_count += 1
        except ValueError:
            exclusions["invalid_fetched_at"] = exclusions.get("invalid_fetched_at", 0) + 1
        if not bool(eligibility["eligible"]):
            reason = str(eligibility["reason"])
            exclusions[reason] = exclusions.get(reason, 0) + 1

    selected.sort(key=lambda item: item["item_key"])
    missing_intervals = sorted(set(normalized_intervals) - present_intervals)
    eligible_item_count = sum(item["eligibility_status"] == "eligible" for item in selected)
    if not selected or missing_intervals:
        eligibility_status = "incomplete"
    elif eligible_item_count != len(selected):
        eligibility_status = "reference_only" if all(item["eligibility_status"] == "reference_only" for item in selected) else "ineligible"
    else:
        eligibility_status = "eligible"
    scope = {
        "symbol": normalized_symbol,
        "intervals": list(normalized_intervals),
        "purpose": str(purpose or "model_input"),
        "universe_reference": universe_reference or {},
        "source_policy_version": SOURCE_POLICY_VERSION,
        "availability_basis": MARKET_AVAILABILITY_CONTRACT_VERSION,
    }
    hash_payload = {
        "contract_version": DATA_SNAPSHOT_CONTRACT_VERSION,
        "scope": scope,
        "as_of_time": cutoff,
        "items": [
            {
                "item_key": item["item_key"],
                "content_hash": item["content_hash"],
                "eligibility_status": item["eligibility_status"],
                "available_at": item["available_at"],
            }
            for item in selected
        ],
        "missing_intervals": missing_intervals,
        "forming_exclusions": exclusions.get("forming_or_unknown_bar_state", 0),
    }
    content_hash = _hash(hash_payload)
    snapshot_id = f"mds-{content_hash[:24]}"
    available_at = max((item["available_at"] for item in selected), default=cutoff)
    details = {
        "source_policy_version": SOURCE_POLICY_VERSION,
        "missing_intervals": missing_intervals,
        "exclusions": exclusions,
        "eligible_for_model": eligibility_status == "eligible",
        "availability_basis": MARKET_AVAILABILITY_CONTRACT_VERSION,
        "historical_backfill_item_count": historical_backfill_item_count,
        "provider_history_revision_risk": historical_backfill_item_count > 0,
    }
    created_at = _utc()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO data_snapshots(
              snapshot_id, contract_version, snapshot_kind, scope_json, as_of_time,
              available_at, eligibility_status, item_count, eligible_item_count,
              content_hash, details_json, created_at
            ) VALUES (?, ?, 'market_candles', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                DATA_SNAPSHOT_CONTRACT_VERSION,
                _canonical_json(scope),
                cutoff,
                available_at,
                eligibility_status,
                len(selected),
                eligible_item_count,
                content_hash,
                _canonical_json(details),
                created_at,
            ),
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO data_snapshot_items(
              snapshot_id, item_key, item_type, symbol, interval, source,
              as_of_time, available_at, fetched_at, eligibility_status,
              exclusion_reason, content_hash, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    snapshot_id,
                    item["item_key"],
                    item["item_type"],
                    item["symbol"],
                    item["interval"],
                    item["source"],
                    item["as_of_time"],
                    item["available_at"],
                    item["fetched_at"],
                    item["eligibility_status"],
                    item["exclusion_reason"],
                    item["content_hash"],
                    _canonical_json(item["payload"]),
                    created_at,
                )
                for item in selected
            ],
        )
        conn.commit()
    return read_data_snapshot(db_path, snapshot_id=snapshot_id)


def read_data_snapshot(db_path: Path, *, snapshot_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM data_snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
        if not row:
            raise ValueError("Unknown data snapshot.")
        items = [dict(item) for item in conn.execute("SELECT * FROM data_snapshot_items WHERE snapshot_id = ? ORDER BY item_key", (snapshot_id,)).fetchall()]
    snapshot = dict(row)
    snapshot["scope"] = json.loads(snapshot.pop("scope_json"))
    snapshot["details"] = json.loads(snapshot.pop("details_json"))
    for item in items:
        item["payload"] = json.loads(item.pop("payload_json"))
    snapshot["items"] = items
    return snapshot
