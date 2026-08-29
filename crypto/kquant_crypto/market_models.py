from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _iso(value: datetime) -> str:
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).isoformat()


def timestamp_ms(value: Any, *, fallback: datetime | None = None) -> str:
    if value is None:
        return _iso(fallback or datetime.now(UTC))
    number = float(value)
    return datetime.fromtimestamp(number / 1000, UTC).isoformat()


def content_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class NormalizedMarketEvent:
    asset_id: str
    venue: str
    instrument_id: str
    market_type: str
    event_type: str
    source_time: str
    received_at: str
    sequence: int | None
    provider_status: str
    content_hash: str
    payload: dict[str, Any]
    previous_sequence: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "venue": self.venue,
            "instrument_id": self.instrument_id,
            "market_type": self.market_type,
            "event_type": self.event_type,
            "source_time": self.source_time,
            "received_at": self.received_at,
            "sequence": self.sequence,
            "previous_sequence": self.previous_sequence,
            "provider_status": self.provider_status,
            "content_hash": self.content_hash,
            "payload": self.payload,
        }


@dataclass
class SequenceTracker:
    last_seen: dict[str, int] = field(default_factory=dict)
    gaps: int = 0
    duplicates: int = 0
    out_of_order: int = 0

    def observe(self, stream_key: str, sequence: int | None, *, previous_sequence: int | None = None, strict: bool = True) -> str:
        if sequence is None:
            return "unsequenced"
        previous = self.last_seen.get(stream_key)
        if previous is None:
            self.last_seen[stream_key] = sequence
            return "first"
        if sequence == previous:
            self.duplicates += 1
            return "duplicate"
        if sequence < previous:
            self.out_of_order += 1
            return "out_of_order"
        self.last_seen[stream_key] = sequence
        if strict and previous_sequence is not None and previous_sequence != previous:
            self.gaps += 1
            return "gap"
        return "ok"

    def reset(self, stream_key: str | None = None) -> None:
        if stream_key is None:
            self.last_seen.clear()
        else:
            self.last_seen.pop(stream_key, None)


@dataclass
class ProviderHealth:
    provider: str
    enabled: bool
    status: str = "disabled"
    connected: bool = False
    reconnect_count: int = 0
    sequence_gaps: int = 0
    duplicate_events: int = 0
    out_of_order_events: int = 0
    accepted_events: int = 0
    handler_errors: int = 0
    last_source_time: str | None = None
    last_received_at: str | None = None
    last_error: str | None = None
    clock_offset_seconds: float | None = None
    clock_source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        quality_errors = self.sequence_gaps + self.duplicate_events + self.out_of_order_events + self.handler_errors
        observed_events = self.accepted_events + quality_errors
        ingestion_lag_seconds: float | None = None
        if self.last_source_time:
            try:
                source = datetime.fromisoformat(self.last_source_time.replace("Z", "+00:00"))
                source = source if source.tzinfo else source.replace(tzinfo=UTC)
                ingestion_lag_seconds = round(max(0.0, (datetime.now(UTC) - source).total_seconds()), 3)
            except ValueError:
                ingestion_lag_seconds = None
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "status": self.status,
            "connected": self.connected,
            "reconnect_count": self.reconnect_count,
            "sequence_gaps": self.sequence_gaps,
            "duplicate_events": self.duplicate_events,
            "out_of_order_events": self.out_of_order_events,
            "accepted_events": self.accepted_events,
            "handler_errors": self.handler_errors,
            "quality_error_count": quality_errors,
            "quality_error_rate": round(quality_errors / observed_events, 6) if observed_events else None,
            "last_source_time": self.last_source_time,
            "last_received_at": self.last_received_at,
            "ingestion_lag_seconds": ingestion_lag_seconds,
            "last_error": self.last_error,
            "clock_offset_seconds": self.clock_offset_seconds,
            "clock_source": self.clock_source,
        }
