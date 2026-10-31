from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .stock_store import connect


UNIVERSE_REGISTRY_CONTRACT_VERSION = "universe_registry_v1"
UNIVERSE_CATALOG_VERSION = "static_stock_catalog_v1"


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


def ensure_stock_universe_catalog(db_path: Path) -> dict[str, Any]:
    """Seed an empty operational catalogue once, without rewriting existing rows.

    The HTTP universe endpoint is intentionally read-only. New databases still
    need a canonical catalogue for coverage and model boundaries, so bootstrap
    that catalogue explicitly during application start or an operator job.
    Existing rows, including locally curated additions, are never replaced by
    the static source.
    """

    with connect(db_path) as conn:
        counts = conn.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active "
            "FROM stock_universe"
        ).fetchone()
        total = int(counts["total"] or 0) if counts else 0
        active = int(counts["active"] or 0) if counts else 0
        if total:
            return {
                "status": "existing",
                "catalog_version": UNIVERSE_CATALOG_VERSION,
                "total_symbols": total,
                "active_symbols": active,
                "inserted_symbols": 0,
            }

        # Keep the import local so this registry module remains usable by the
        # migration layer without creating an import cycle at module load time.
        from .stock_universe import stock_universe_payload

        payload = stock_universe_payload("all")
        now = _now()
        rows = list(payload.get("stocks") or [])
        conn.executemany(
            """
            INSERT INTO stock_universe(
              symbol, name, sector, layer, tags_json, rank, active, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            [
                (
                    str(stock["symbol"]).upper(),
                    str(stock.get("name") or stock["symbol"]),
                    str(stock.get("sector") or "Unclassified"),
                    str(stock.get("layer") or "Unclassified"),
                    json.dumps(stock.get("tags") or [], ensure_ascii=True, sort_keys=True),
                    int(stock.get("rank") or 0),
                    now,
                )
                for stock in rows
            ],
        )
        conn.commit()
    return {
        "status": "seeded",
        "catalog_version": UNIVERSE_CATALOG_VERSION,
        "total_symbols": len(rows),
        "active_symbols": len(rows),
        "inserted_symbols": len(rows),
    }


def restore_universe_from_registry(
    db_path: Path,
    registry_id: str,
    *,
    reason: str = "operator_requested_registry_repair",
) -> dict[str, Any]:
    """Explicitly restore the operational catalogue from a sealed registry.

    This is a repair command, never an implicit startup or HTTP behavior. The
    target registry is content-addressed and must already exist. The current
    catalogue is deactivated and then replaced inside one transaction; the
    before/after hashes are written to ``audit_events`` for later review.
    """

    target_id = str(registry_id or "").strip()
    if not target_id:
        raise ValueError("registry_id is required")
    with connect(db_path) as conn:
        target = conn.execute(
            "SELECT registry_id, content_hash, symbol_count FROM universe_registry_versions WHERE registry_id = ?",
            (target_id,),
        ).fetchone()
        if target is None:
            raise ValueError(f"Unknown universe registry: {target_id}")
        target_rows = conn.execute(
            """
            SELECT symbol, name, sector, layer, tags_json, rank_value, active
            FROM universe_registry_members
            WHERE registry_id = ? AND active = 1
            ORDER BY symbol
            """,
            (target_id,),
        ).fetchall()
        if not target_rows or len(target_rows) != int(target["symbol_count"]):
            raise ValueError("Target universe registry is incomplete and cannot be restored.")
        target_members = [
            {
                "symbol": str(row["symbol"]).upper(),
                "name": str(row["name"] or ""),
                "sector": str(row["sector"] or "Unclassified"),
                "layer": str(row["layer"] or "Unclassified"),
                "tags": json.loads(row["tags_json"] or "[]"),
                "rank": int(row["rank_value"] or 0),
                "active": True,
            }
            for row in target_rows
        ]
        target_hash = _hash(target_members)
        if target_hash != str(target["content_hash"]):
            raise ValueError("Target universe registry content hash does not match its members.")

        current_rows = conn.execute(
            "SELECT symbol, name, sector, layer, tags_json, rank, active FROM stock_universe WHERE active = 1 ORDER BY symbol"
        ).fetchall()
        before_members = [_canonical_member(dict(row)) for row in current_rows]
        before_hash = _hash(before_members)
        now = _now()

        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE stock_universe SET active = 0, updated_at = ?", (now,))
        conn.executemany(
            """
            INSERT INTO stock_universe(
              symbol, name, sector, layer, tags_json, rank, active, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(symbol) DO UPDATE SET
              name=excluded.name,
              sector=excluded.sector,
              layer=excluded.layer,
              tags_json=excluded.tags_json,
              rank=excluded.rank,
              active=1,
              updated_at=excluded.updated_at
            """,
            [
                (
                    member["symbol"],
                    member["name"],
                    member["sector"],
                    member["layer"],
                    json.dumps(member["tags"], ensure_ascii=True, sort_keys=True),
                    member["rank"],
                    now,
                )
                for member in target_members
            ],
        )
        audit_payload = {
            "repair_version": "universe_registry_repair_v1",
            "registry_id": target_id,
            "before_hash": before_hash,
            "after_hash": target_hash,
            "before_symbol_count": len(before_members),
            "after_symbol_count": len(target_members),
            "reason": str(reason)[:500],
        }
        conn.execute(
            "INSERT INTO audit_events(event_type, payload_json, created_at) VALUES (?, ?, ?)",
            ("universe_registry_repair", json.dumps(audit_payload, ensure_ascii=True, sort_keys=True), now),
        )
        conn.commit()
    return {
        "status": "already_aligned" if before_hash == target_hash else "repaired",
        "registry_id": target_id,
        "before_hash": before_hash,
        "after_hash": target_hash,
        "before_symbol_count": len(before_members),
        "after_symbol_count": len(target_members),
        "audit_event": "universe_registry_repair",
    }


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


def current_universe_registry_id_read_only(db_path: Path) -> str | None:
    """Return the registry matching the active catalogue without writing."""

    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT symbol, name, sector, layer, tags_json, rank, active
            FROM stock_universe WHERE active = 1 ORDER BY symbol
            """
        ).fetchall()
        if not rows:
            return None
        content_hash = _hash([_canonical_member(dict(row)) for row in rows])
        record = conn.execute(
            "SELECT registry_id FROM universe_registry_versions WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
    return str(record["registry_id"]) if record else None


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
