from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .stock_store import connect


CANONICAL_VERSIONS = {
    "swing_long_v1": "swing_long_v1.0.1",
}


class StrategyVersionConflict(RuntimeError):
    """Raised when a previously registered version is given different rules."""


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    strategy_version: str
    profile_name: str
    rule_engine_version: str
    specification_path: str
    parameters: dict[str, Any]

    @property
    def config_payload(self) -> dict[str, Any]:
        return {
            "definition_schema": "strategy_definition_v1",
            "strategy_id": self.strategy_id,
            "profile_name": self.profile_name,
            "rule_engine_version": self.rule_engine_version,
            "parameters": self.parameters,
        }

    @property
    def config_json(self) -> str:
        return json.dumps(self.config_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def config_hash(self) -> str:
        return hashlib.sha256(self.config_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StrategyVersionRecord:
    strategy_id: str
    strategy_version: str
    profile_name: str
    config_hash: str
    config_json: str
    specification_path: str
    created_at: str


def definition_for_profile(
    profile_name: str,
    profile: dict[str, Any],
    *,
    strategy_version: str | None = None,
) -> StrategyDefinition:
    """Build the immutable definition envelope for a strategy profile.

    Legacy profiles remain separately identifiable so their historical evidence
    is not accidentally relabelled as the canonical swing strategy.
    """

    normalized = str(profile_name or profile.get("name") or "swing_long_v1")
    canonical = normalized == "swing_long_v1"
    return StrategyDefinition(
        strategy_id="swing_long" if canonical else normalized,
        strategy_version=strategy_version or CANONICAL_VERSIONS.get(normalized, f"{normalized}.legacy.0"),
        profile_name=normalized,
        rule_engine_version="stock_signals.build_signal.v1",
        specification_path="docs/strategy_specification.md" if canonical else "legacy_profile_unfrozen",
        parameters=dict(profile),
    )


def register_strategy_version(db_path: Path, definition: StrategyDefinition) -> StrategyVersionRecord:
    """Insert a version once, or return its exact existing immutable record."""

    with connect(db_path) as conn:
        existing = conn.execute(
            """
            SELECT strategy_id, strategy_version, profile_name, config_hash,
                   config_json, specification_path, created_at
            FROM strategy_versions
            WHERE strategy_version = ?
            """,
            (definition.strategy_version,),
        ).fetchone()
        if existing:
            record = _record(existing)
            if record.strategy_id != definition.strategy_id or record.config_hash != definition.config_hash:
                raise StrategyVersionConflict(
                    f"Strategy version {definition.strategy_version} is already registered with a different configuration. "
                    "Create a new version instead of overwriting historical evidence."
                )
            return record
        conn.execute(
            """
            INSERT INTO strategy_versions(
              strategy_id, strategy_version, profile_name, config_hash,
              config_json, specification_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'))
            """,
            (
                definition.strategy_id,
                definition.strategy_version,
                definition.profile_name,
                definition.config_hash,
                definition.config_json,
                definition.specification_path,
            ),
        )
        row = conn.execute(
            """
            SELECT strategy_id, strategy_version, profile_name, config_hash,
                   config_json, specification_path, created_at
            FROM strategy_versions
            WHERE strategy_version = ?
            """,
            (definition.strategy_version,),
        ).fetchone()
        conn.commit()
    if not row:  # pragma: no cover - SQLite insert/read is deterministic
        raise RuntimeError("Strategy version registration failed.")
    return _record(row)


def _record(row: Any) -> StrategyVersionRecord:
    return StrategyVersionRecord(
        strategy_id=str(row["strategy_id"]),
        strategy_version=str(row["strategy_version"]),
        profile_name=str(row["profile_name"]),
        config_hash=str(row["config_hash"]),
        config_json=str(row["config_json"]),
        specification_path=str(row["specification_path"]),
        created_at=str(row["created_at"]),
    )
