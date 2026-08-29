from __future__ import annotations

"""Shared point-in-time metadata for stock and crypto research records.

This is deliberately a small contract layer.  It does not decide whether a
record is tradable; EVAL still owns that decision.  Its job is to make the
lineage fields impossible to omit silently when a record crosses an agent
boundary.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping


RESEARCH_METADATA_VERSION = "research_metadata_v1.0.0"
KNOWN_SOURCE_STATUSES = frozenset({"live", "closed", "complete", "verified", "stale", "partial", "unknown"})


def _parse_time(value: Any) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True)
class ResearchMetadata:
    strategy_version: str
    feature_snapshot_id: str
    model_version: str
    data_cutoff_time: str
    source_status: str
    coverage: float
    hard_veto: bool
    research_only: bool = True
    metadata_version: str = RESEARCH_METADATA_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ResearchMetadata":
        try:
            coverage = float(value.get("coverage", 0.0))
        except (TypeError, ValueError):
            coverage = 0.0
        return cls(
            strategy_version=str(value.get("strategy_version") or ""),
            feature_snapshot_id=str(value.get("feature_snapshot_id") or ""),
            model_version=str(value.get("model_version") or ""),
            data_cutoff_time=str(value.get("data_cutoff_time") or ""),
            source_status=str(value.get("source_status") or "unknown").lower(),
            coverage=coverage,
            hard_veto=bool(value.get("hard_veto")),
            research_only=bool(value.get("research_only", True)),
            metadata_version=str(value.get("metadata_version") or RESEARCH_METADATA_VERSION),
        )

    def blockers(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.strategy_version:
            reasons.append("strategy_version_missing")
        if not self.feature_snapshot_id:
            reasons.append("feature_snapshot_id_missing")
        if not self.data_cutoff_time or _parse_time(self.data_cutoff_time) is None:
            reasons.append("data_cutoff_time_invalid")
        if self.source_status not in KNOWN_SOURCE_STATUSES:
            reasons.append("source_status_unknown")
        if not 0.0 < self.coverage <= 1.0:
            reasons.append("coverage_insufficient")
        if self.research_only is not True:
            reasons.append("research_only_required")
        return tuple(reasons)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "metadata_version": self.metadata_version,
            "strategy_version": self.strategy_version,
            "feature_snapshot_id": self.feature_snapshot_id,
            "model_version": self.model_version,
            "data_cutoff_time": self.data_cutoff_time,
            "source_status": self.source_status,
            "coverage": self.coverage,
            "hard_veto": self.hard_veto,
            "research_only": self.research_only,
            "blockers": list(self.blockers()),
        }


def metadata_from_roll_input(value: Mapping[str, Any]) -> ResearchMetadata:
    """Build the shared contract without changing the roll policy itself."""

    return ResearchMetadata.from_mapping(value)


__all__ = [
    "RESEARCH_METADATA_VERSION",
    "KNOWN_SOURCE_STATUSES",
    "ResearchMetadata",
    "metadata_from_roll_input",
]
