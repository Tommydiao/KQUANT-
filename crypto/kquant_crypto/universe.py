from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .db.migrations import connect, migrate
from .evaluation_models import stable_hash
from .universe_catalog import cex_symbol_tiers, load_universe_catalog


@dataclass(frozen=True)
class CanonicalAsset:
    asset_id: str
    symbol: str
    asset_kind: str
    chain_id: str | None = None
    contract_address: str | None = None
    status: str = "active"
    metadata: dict[str, Any] | None = None

    @classmethod
    def cex(cls, symbol: str, *, asset_kind: str = "native", metadata: dict[str, Any] | None = None) -> "CanonicalAsset":
        normalized = symbol.upper()
        return cls(asset_id=f"asset:{normalized.lower()}", symbol=normalized, asset_kind=asset_kind, metadata=metadata or {})

    @classmethod
    def dex(cls, chain_id: str, contract_address: str, symbol: str, *, asset_kind: str = "token", metadata: dict[str, Any] | None = None) -> "CanonicalAsset":
        chain = chain_id.lower().strip()
        address = contract_address.lower().strip()
        return cls(asset_id=f"{chain}:{address}", symbol=symbol.upper(), asset_kind=asset_kind, chain_id=chain, contract_address=address, metadata=metadata or {})


class UniverseRegistry:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def save_asset(self, asset: CanonicalAsset) -> None:
        migrate(self.db_path)
        now = datetime.now(UTC).isoformat()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO crypto_universe_registry(asset_id,symbol,asset_kind,chain_id,contract_address,status,first_seen_at,last_seen_at,metadata_json)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(asset_id) DO UPDATE SET
                  symbol=excluded.symbol,status=excluded.status,last_seen_at=excluded.last_seen_at,metadata_json=excluded.metadata_json
                """,
                (asset.asset_id, asset.symbol, asset.asset_kind, asset.chain_id, asset.contract_address, asset.status, now, now, json.dumps(asset.metadata or {}, ensure_ascii=True, sort_keys=True)),
            )

    def create_snapshot(self, assets: list[tuple[CanonicalAsset, str]], *, registry_version: str = "crypto_universe_v1.0.0", as_of_time: str | None = None) -> dict[str, Any]:
        migrate(self.db_path)
        as_of = as_of_time or datetime.now(UTC).isoformat()
        members = [{"asset_id": asset.asset_id, "symbol": asset.symbol, "tier": tier, "asset_kind": asset.asset_kind} for asset, tier in assets]
        digest = stable_hash({"registry_version": registry_version, "as_of_time": as_of, "members": members})
        snapshot_id = f"universe_{uuid4().hex}"
        with connect(self.db_path) as conn:
            now = datetime.now(UTC).isoformat()
            for asset, _ in assets:
                conn.execute(
                    """
                    INSERT INTO crypto_universe_registry(asset_id,symbol,asset_kind,chain_id,contract_address,status,first_seen_at,last_seen_at,metadata_json)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(asset_id) DO UPDATE SET
                      symbol=excluded.symbol,status=excluded.status,last_seen_at=excluded.last_seen_at,metadata_json=excluded.metadata_json
                    """,
                    (asset.asset_id, asset.symbol, asset.asset_kind, asset.chain_id, asset.contract_address, asset.status, now, now, json.dumps(asset.metadata or {}, ensure_ascii=True, sort_keys=True)),
                )
            # Each snapshot is a full replacement of the active research
            # universe. Close prior open-ended memberships at the boundary so
            # point-in-time queries cannot see both versions.
            conn.execute(
                "UPDATE crypto_universe_memberships SET effective_to=? WHERE effective_to IS NULL AND effective_from<?",
                (as_of, as_of),
            )
            conn.execute(
                "INSERT INTO crypto_universe_snapshots(snapshot_id,registry_version,as_of_time,available_at,member_count,content_hash,members_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (snapshot_id, registry_version, as_of, as_of, len(members), digest, json.dumps(members, ensure_ascii=True, sort_keys=True), as_of),
            )
            for asset, tier in assets:
                conn.execute(
                    "INSERT INTO crypto_universe_memberships(snapshot_id,asset_id,tier,effective_from,effective_to,membership_status) VALUES(?,?,?,?,?,?)",
                    (snapshot_id, asset.asset_id, tier, as_of, None, "active"),
                )
        return {"snapshot_id": snapshot_id, "registry_version": registry_version, "as_of_time": as_of, "member_count": len(members), "content_hash": digest, "members": members}

    def ensure_cex_snapshot(self, symbols: tuple[str, ...] | list[str], *, root_dir: Path, as_of_time: str | None = None) -> dict[str, Any]:
        """Create or reuse the configured CEX snapshot without restart churn."""

        tiers = cex_symbol_tiers(root_dir)
        normalized = tuple(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
        assets = [
            (CanonicalAsset.cex(symbol, metadata={"source": "config/crypto_universe.yml"}), tiers.get(symbol, "CEX_HIGH_BETA"))
            for symbol in normalized
        ]
        expected = [
            {"asset_id": asset.asset_id, "symbol": asset.symbol, "tier": tier, "asset_kind": asset.asset_kind}
            for asset, tier in assets
        ]
        migrate(self.db_path)
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM crypto_universe_snapshots ORDER BY as_of_time DESC LIMIT 1").fetchone()
        if row is not None:
            try:
                members = json.loads(row["members_json"])
            except (TypeError, json.JSONDecodeError):
                members = None
            if members == expected:
                value = dict(row)
                value["members"] = members
                value.pop("members_json", None)
                value["status"] = "unchanged"
                return value
        snapshot = self.create_snapshot(
            assets,
            registry_version=str(load_universe_catalog(root_dir).get("version") or "crypto_universe_v1.1.0"),
            as_of_time=as_of_time,
        )
        snapshot["status"] = "created"
        return snapshot

    def member_at(self, asset_id: str, at_time: str) -> bool:
        migrate(self.db_path)
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM crypto_universe_memberships WHERE asset_id=? AND effective_from<=? AND (effective_to IS NULL OR effective_to>?) LIMIT 1",
                (asset_id, at_time, at_time),
            ).fetchone()
        return row is not None
