from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .db.migrations import connect, migrate
from .evaluation_models import stable_hash


TRUST_STATUSES = frozenset({"live", "stale", "partial", "cross_source_conflict", "provider_unavailable", "security_unknown", "unavailable"})
PUBLIC_SOURCE_STATUSES = frozenset({"live_primary", "stale_primary", "reference_only", "unavailable"})


def normalize_source_status(status: str) -> str:
    """Expose crypto lineage through the same public contract as stock data."""
    normalized = str(status or "unknown").lower()
    if normalized in {"live", "closed", "complete", "verified"}:
        return "live_primary"
    if normalized == "stale":
        return "stale_primary"
    if normalized in {"partial", "cross_source_conflict", "security_unknown"}:
        return "reference_only"
    return "unavailable"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class DataSnapshot:
    snapshot_id: str
    snapshot_type: str
    source: str
    trust_status: str
    content_hash: str
    payload: dict[str, Any]
    asset_id: str | None = None
    instrument_id: str | None = None
    venue: str | None = None
    source_time: str | None = None
    available_at: str | None = None
    fetched_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.trust_status not in TRUST_STATUSES:
            raise ValueError(f"Unknown data trust status: {self.trust_status}")

    @classmethod
    def create(cls, *, snapshot_type: str, source: str, payload: dict[str, Any], trust_status: str, asset_id: str | None = None, instrument_id: str | None = None, venue: str | None = None, source_time: str | None = None, available_at: str | None = None) -> "DataSnapshot":
        digest = stable_hash({"snapshot_type": snapshot_type, "source": source, "payload": payload, "source_time": source_time})
        return cls(
            snapshot_id=f"data_{uuid4().hex}",
            snapshot_type=snapshot_type,
            source=source,
            trust_status=trust_status,
            content_hash=digest,
            payload=payload,
            asset_id=asset_id,
            instrument_id=instrument_id,
            venue=venue,
            source_time=source_time,
            available_at=available_at,
        )

    def eval_eligible(self) -> bool:
        return self.trust_status == "live" and not bool(self.payload.get("forming_candle")) and not bool(self.payload.get("cross_source_conflict"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_type": self.snapshot_type,
            "asset_id": self.asset_id,
            "instrument_id": self.instrument_id,
            "venue": self.venue,
            "source": self.source,
            "source_time": self.source_time,
            "available_at": self.available_at,
            "fetched_at": self.fetched_at,
            "trust_status": self.trust_status,
            "source_status": normalize_source_status(self.trust_status),
            "content_hash": self.content_hash,
            "payload": self.payload,
        }


def assess_trust(*, provider_status: str, age_seconds: float | None, required_fields: list[str], payload: dict[str, Any], max_age_seconds: float = 30.0) -> str:
    if provider_status in {"provider_unavailable", "clock_skew", "source_stale", "resync_required"}:
        return "provider_unavailable"
    if payload.get("cross_source_conflict"):
        return "cross_source_conflict"
    if any(payload.get(field) is None for field in required_fields):
        return "partial"
    if payload.get("forming_candle"):
        return "partial"
    if age_seconds is None or age_seconds > max_age_seconds:
        return "stale"
    return "live"


class DataTrustStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def save(self, snapshot: DataSnapshot) -> None:
        migrate(self.db_path)
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO crypto_data_snapshots(
                  snapshot_id,snapshot_type,asset_id,instrument_id,venue,source,
                  source_time,available_at,fetched_at,trust_status,content_hash,
                  payload_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(snapshot_id) DO NOTHING
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.snapshot_type,
                    snapshot.asset_id,
                    snapshot.instrument_id,
                    snapshot.venue,
                    snapshot.source,
                    snapshot.source_time,
                    snapshot.available_at,
                    snapshot.fetched_at,
                    snapshot.trust_status,
                    snapshot.content_hash,
                    json.dumps(snapshot.payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                    snapshot.fetched_at,
                ),
            )

    def get(self, snapshot_id: str) -> dict[str, Any] | None:
        migrate(self.db_path)
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM crypto_data_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["payload"] = json.loads(value.pop("payload_json"))
        return value
