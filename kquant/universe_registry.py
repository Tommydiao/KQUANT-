from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .stock_store import connect


UNIVERSE_REGISTRY_CONTRACT_VERSION = "universe_registry_v1"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_member(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(row["symbol"]).upper(),
        "name": str(row.get("name") or ""),
        "sector": str(row.get("sector") or "Unclassified"),
        "layer": str(row.get("layer") or "Unclassified"),
        "tags": json.loads(row.get("tags_json") or "[]"),
        "rank": int(row.get("rank") or 0),
        "active": bool(row.get("active")),
    }


def _hash(members: list[dict[str, Any]]) -> str:
    encoded = json.dumps(members, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def ensure_current_universe_registry(db_path: Path, registry_name: str = "active_us_equities") -> dict[str, Any]:
    """Version the current database universe without deleting legacy rows.

    The database is the current operational catalogue: it has 296 active rows
    while the old Python seed list has fewer. The seed is retained as a source
    of updates, but coverage and models now consume this registered snapshot.
    """

    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT symbol, name, sector, layer, tags_json, rank, active
            FROM stock_universe WHERE active = 1 ORDER BY symbol
            """
        ).fetchall()
        members = [_canonical_member(dict(row)) for row in rows]
        content_hash = _hash(members)
        existing = conn.execute(
            "SELECT * FROM universe_registry_versions WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if existing is None:
            registry_id = f"usr_{content_hash[:20]}"
            now = _now()
            conn.execute(
                """
                INSERT INTO universe_registry_versions(
                  registry_id, registry_name, source, content_hash, symbol_count, details_json, created_at
                ) VALUES (?, ?, 'database_stock_universe', ?, ?, ?, ?)
                """,
                (
                    registry_id,
                    registry_name,
                    content_hash,
                    len(members),
                    json.dumps({"contract_version": UNIVERSE_REGISTRY_CONTRACT_VERSION}, sort_keys=True),
                    now,
                ),
            )
            conn.executemany(
                """
                INSERT INTO universe_registry_members(
                  registry_id, symbol, name, sector, layer, tags_json, rank_value,
                  active, eligibility_status, provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'eligible', 'database_stock_universe')
                """,
                [
                    (
                        registry_id,
                        item["symbol"],
                        item["name"],
                        item["sector"],
                        item["layer"],
                        json.dumps(item["tags"], ensure_ascii=True, sort_keys=True),
                        item["rank"],
                    )
                    for item in members
                ],
            )
            conn.commit()
        else:
            registry_id = str(existing["registry_id"])
        record = conn.execute(
            "SELECT * FROM universe_registry_versions WHERE registry_id = ?", (registry_id,)
        ).fetchone()
    return {
        "registry_id": registry_id,
        "registry_name": registry_name,
        "contract_version": UNIVERSE_REGISTRY_CONTRACT_VERSION,
        "source": "database_stock_universe",
        "content_hash": content_hash,
        "symbol_count": len(members),
        "created_at": record["created_at"] if record else None,
    }


def current_universe_members(db_path: Path) -> list[dict[str, Any]]:
    registry = ensure_current_universe_registry(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT symbol, name, sector, layer, tags_json, rank_value, eligibility_status, provenance
            FROM universe_registry_members WHERE registry_id = ? AND active = 1 ORDER BY symbol
            """,
            (registry["registry_id"],),
        ).fetchall()
    return [
        {
            **dict(row),
            "tags": json.loads(row["tags_json"]),
            "rank": int(row["rank_value"]),
            "eligible_for_model": row["eligibility_status"] == "eligible",
        }
        for row in rows
    ]
