from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .stock_store import connect


UTC = timezone.utc
SNAPSHOT_SOURCE = "runtime_static_universe_v1"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_members(stocks: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for stock in stocks:
        symbol = str(stock.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        members.append(
            {
                "symbol": symbol,
                "name": str(stock.get("name") or symbol),
                "sector": str(stock.get("sector") or "Unknown"),
                "layer": str(stock.get("layer") or stock.get("primary_layer") or "Unknown"),
                "tags": sorted(str(tag) for tag in (stock.get("tags") or [])),
                "rank": int(stock.get("rank") or 0),
                "liquidity_tier": str(stock.get("liquidity_tier") or "core"),
            }
        )
    return sorted(members, key=lambda item: item["symbol"])


def _definition_hash(members: list[dict[str, Any]]) -> str:
    encoded = json.dumps(members, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def persist_universe_snapshot(
    db_path: Path,
    *,
    universe: str,
    as_of_date: str,
    stocks: Iterable[dict[str, Any]],
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Persist the exact runtime membership without claiming pre-snapshot history."""
    normalized_universe = (universe or "default").strip().lower()
    members = _canonical_members(stocks)
    definition_hash = _definition_hash(members)
    observed_at = recorded_at or _utc_now()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO stock_universe_snapshots(
              universe, as_of_date, definition_hash, membership_count, source, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (normalized_universe, as_of_date, definition_hash, len(members), SNAPSHOT_SOURCE, observed_at),
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO stock_universe_memberships(
              universe, as_of_date, definition_hash, symbol, name, sector, layer,
              tags_json, rank, liquidity_tier, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    normalized_universe,
                    as_of_date,
                    definition_hash,
                    item["symbol"],
                    item["name"],
                    item["sector"],
                    item["layer"],
                    json.dumps(item["tags"], separators=(",", ":")),
                    item["rank"],
                    item["liquidity_tier"],
                    observed_at,
                )
                for item in members
            ],
        )
        conn.commit()
    return {
        "universe": normalized_universe,
        "as_of_date": as_of_date,
        "definition_hash": definition_hash,
        "membership_count": len(members),
        "source": SNAPSHOT_SOURCE,
        "recorded_at": observed_at,
    }


def universe_snapshot_status(
    db_path: Path,
    *,
    universe: str,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    normalized_universe = (universe or "default").strip().lower()
    with connect(db_path) as conn:
        coverage = conn.execute(
            """
            SELECT MIN(as_of_date) AS first_snapshot_date, MAX(as_of_date) AS last_snapshot_date,
                   COUNT(DISTINCT as_of_date) AS snapshot_dates
            FROM stock_universe_snapshots WHERE universe = ?
            """,
            (normalized_universe,),
        ).fetchone()
        exact = None
        if as_of_date:
            exact = conn.execute(
                """
                SELECT definition_hash, membership_count, source, recorded_at
                FROM stock_universe_snapshots
                WHERE universe = ? AND as_of_date = ?
                ORDER BY recorded_at DESC LIMIT 1
                """,
                (normalized_universe, as_of_date),
            ).fetchone()
    first = coverage["first_snapshot_date"] if coverage else None
    last = coverage["last_snapshot_date"] if coverage else None
    return {
        "universe": normalized_universe,
        "requested_as_of_date": as_of_date,
        "exact_snapshot_available": bool(exact),
        "snapshot": dict(exact) if exact else None,
        "coverage": {
            "first_snapshot_date": first,
            "last_snapshot_date": last,
            "snapshot_dates": int(coverage["snapshot_dates"] or 0) if coverage else 0,
        },
        "historical_membership_complete": False,
        "survivorship_limited": True,
        "limitation": (
            "Runtime snapshots begin when KQUANT observes them. Earlier membership is not "
            "reconstructed, so historical replay using this universe is survivorship-limited."
        ),
    }


def resolve_universe_membership(
    db_path: Path,
    *,
    universe: str,
    as_of_date: str,
) -> dict[str, Any]:
    """Resolve only observed membership available on or before a requested date.

    Runtime snapshots do not reconstruct delisted constituents or index history,
    so every result remains explicitly survivorship-limited until that dataset is
    independently ingested.
    """

    normalized_universe = (universe or "default").strip().lower()
    requested = str(as_of_date)
    with connect(db_path) as conn:
        snapshot = conn.execute(
            """
            SELECT universe, as_of_date, definition_hash, membership_count, source, recorded_at
            FROM stock_universe_snapshots
            WHERE universe = ? AND as_of_date <= ?
            ORDER BY as_of_date DESC, recorded_at DESC
            LIMIT 1
            """,
            (normalized_universe, requested),
        ).fetchone()
        members = []
        if snapshot:
            members = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT symbol, name, sector, layer, tags_json, rank, liquidity_tier, recorded_at
                    FROM stock_universe_memberships
                    WHERE universe = ? AND as_of_date = ? AND definition_hash = ?
                    ORDER BY symbol
                    """,
                    (snapshot["universe"], snapshot["as_of_date"], snapshot["definition_hash"]),
                ).fetchall()
            ]
    for member in members:
        member["tags"] = json.loads(member.pop("tags_json"))
    resolved = dict(snapshot) if snapshot else None
    return {
        "universe": normalized_universe,
        "requested_as_of_date": requested,
        "resolved_snapshot": resolved,
        "resolution": "exact" if snapshot and snapshot["as_of_date"] == requested else "latest_prior_observation" if snapshot else "unavailable",
        "members": members,
        "membership_count": len(members),
        "historical_membership_complete": False,
        "survivorship_limited": True,
        "eligible_for_model": False,
        "limitation": "Observed runtime memberships are not a complete historical constituent history.",
    }
