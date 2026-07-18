from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any


ACTIVE_VALIDATION_PROFILE = "swing_long_v1"
VERSIONING_CONTRACT = "kquant_strategy_version_contract_v1"
INITIAL_ACTIVE_VERSION = "swing_long_v1.0.0"


@dataclass(frozen=True)
class StrategyVersion:
    profile: str
    version: str
    config_hash: str
    lifecycle: str
    config_snapshot: dict[str, Any]

    def as_payload(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "version": self.version,
            "config_hash": self.config_hash,
            "lifecycle": self.lifecycle,
            "contract": VERSIONING_CONTRACT,
            "config_snapshot": self.config_snapshot,
        }


def canonical_snapshot(profile_config: dict[str, Any]) -> dict[str, Any]:
    """Return the exact deterministic configuration that a run is allowed to use."""

    snapshot = {
        key: value
        for key, value in profile_config.items()
        if key not in {"label"}
    }
    snapshot["versioning_contract"] = VERSIONING_CONTRACT
    return json.loads(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def strategy_version(profile_config: dict[str, Any]) -> StrategyVersion:
    profile = str(profile_config.get("name") or ACTIVE_VALIDATION_PROFILE)
    snapshot = canonical_snapshot(profile_config)
    config_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    config_hash = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
    return StrategyVersion(
        profile=profile,
        version=INITIAL_ACTIVE_VERSION if profile == ACTIVE_VALIDATION_PROFILE else f"{profile}.frozen",
        config_hash=config_hash,
        lifecycle="active_validation" if profile == ACTIVE_VALIDATION_PROFILE else "frozen_out_of_scope",
        config_snapshot=snapshot,
    )


def ensure_strategy_version(conn: sqlite3.Connection, profile_config: dict[str, Any]) -> StrategyVersion:
    """Persist a configuration snapshot and reject silent mutation of a version."""

    metadata = strategy_version(profile_config)
    config_json = json.dumps(metadata.config_snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    rows = conn.execute(
        "SELECT config_hash FROM strategy_versions WHERE profile = ? AND strategy_version = ?",
        (metadata.profile, metadata.version),
    ).fetchall()
    existing_hashes = {str(row["config_hash"]) for row in rows}
    if existing_hashes and metadata.config_hash not in existing_hashes:
        raise ValueError(
            f"Immutable strategy version conflict for {metadata.profile} {metadata.version}; "
            "bump the strategy version before changing its configuration."
        )
    conn.execute(
        """
        INSERT OR IGNORE INTO strategy_versions(
          profile, strategy_version, config_hash, lifecycle, config_json, created_at
        ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            metadata.profile,
            metadata.version,
            metadata.config_hash,
            metadata.lifecycle,
            config_json,
        ),
    )
    return metadata
