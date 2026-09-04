from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from .db.migrations import connect, migrate
from .evaluation_models import stable_hash


class EvidenceCategory(StrEnum):
    ETF_FLOW = "etf_flow"
    EXCHANGE_DERIVATIVES = "exchange_derivatives"
    ONCHAIN = "onchain"
    WHALE = "whale"
    MARKET_STRUCTURE = "market_structure"
    PROTOCOL_METRIC = "protocol_metric"


# This is the evidence universe, not a claim that every asset has a live
# provider.  A listed proxy or altcoin remains visible as N/A until a real
# source snapshot is available.
SUPPORTED_EVIDENCE_ASSETS = ("BTC", "ETH", "SOL", "ETHU", "MSTR", "MSTU", "AAVE", "ENA", "ZEC", "PUMP", "ARB", "HYPE")
EVIDENCE_ASSET_SCOPE: dict[str, tuple[str, ...]] = {
    "etf_flow": ("BTC", "ETH"),
    "exchange_derivatives": ("BTC", "ETH", "SOL", "AAVE", "ENA", "ZEC", "PUMP", "ARB", "HYPE"),
    "onchain": ("BTC", "ETH", "SOL", "AAVE", "ENA", "ZEC", "PUMP", "ARB", "HYPE"),
    "whale": ("BTC", "ETH", "SOL", "AAVE", "ENA", "ZEC", "PUMP", "ARB", "HYPE"),
    "market_structure": ("BTC", "ETH"),
    "protocol_metric": ("AAVE", "ENA"),
}
EVIDENCE_FIELDS: dict[str, tuple[str, ...]] = {
    EvidenceCategory.ETF_FLOW.value: ("flow_usd", "flow_7d_usd", "flow_30d_usd", "aum_usd", "premium_discount"),
    EvidenceCategory.EXCHANGE_DERIVATIVES.value: ("cvd", "active_buy_volume", "active_sell_volume", "open_interest", "funding_rate", "mark_price", "index_price", "basis", "liquidations_usd", "spread_bps", "depth_usd"),
    EvidenceCategory.ONCHAIN.value: ("exchange_netflow", "stablecoin_supply", "active_addresses", "holder_concentration", "dex_volume_usd", "dex_tvl_usd", "mvrv", "sopr", "nupl", "realized_cap_usd"),
    EvidenceCategory.WHALE.value: ("large_transfer_count", "large_transfer_volume_usd", "exchange_inflow_usd", "exchange_outflow_usd", "top_holder_concentration"),
    EvidenceCategory.MARKET_STRUCTURE.value: ("market_regime", "breadth", "btc_dominance", "eth_btc", "sol_btc"),
    EvidenceCategory.PROTOCOL_METRIC.value: ("tvl_usd", "fees_usd", "active_users", "token_unlock_usd"),
}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True)
class ExternalEvidenceSnapshot:
    evidence_id: str
    asset_id: str
    symbol: str
    category: str
    source: str
    source_version: str
    source_status: str
    source_time: str | None
    published_at: str | None
    collected_at: str
    available_at: str
    trust_status: str
    values: dict[str, Any]
    missing_fields: tuple[str, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        asset_id: str,
        symbol: str,
        category: str,
        source: str,
        source_version: str = "",
        source_status: str,
        available_at: str,
        values: Mapping[str, Any],
        source_time: str | None = None,
        published_at: str | None = None,
        collected_at: str | None = None,
    ) -> "ExternalEvidenceSnapshot":
        category_value = str(category).lower()
        if category_value not in EVIDENCE_FIELDS:
            raise ValueError(f"unsupported evidence category: {category}")
        if not asset_id or not symbol or not source:
            raise ValueError("asset_id, symbol and source are required")
        if _parse_time(available_at) is None:
            raise ValueError("available_at must be an ISO timestamp")
        if published_at and _parse_time(published_at) is None:
            raise ValueError("published_at must be an ISO timestamp")
        if source_time and _parse_time(source_time) is None:
            raise ValueError("source_time must be an ISO timestamp")
        collected_value = collected_at or available_at
        if _parse_time(collected_value) is None:
            raise ValueError("collected_at must be an ISO timestamp")
        available = _parse_time(available_at)
        source_time_value = _parse_time(source_time) if source_time else None
        published_value = _parse_time(published_at) if published_at else None
        if available is not None and source_time_value is not None and source_time_value > available:
            raise ValueError("source_time must not be after available_at")
        if available is not None and published_value is not None and published_value > available:
            raise ValueError("published_at must not be after available_at")
        normalized_source_version = str(source_version or source)
        normalized = {str(key): value for key, value in values.items() if str(key) in EVIDENCE_FIELDS[category_value] and value is not None}
        missing = tuple(sorted(set(EVIDENCE_FIELDS[category_value]) - set(normalized)))
        trust = "verified" if str(source_status).lower() in {"live", "closed", "complete", "verified"} and not missing else "data_caution"
        payload = {
            "asset_id": asset_id,
            "symbol": symbol,
            "category": category_value,
            "source": source,
            "source_version": normalized_source_version,
            "source_status": str(source_status).lower(),
            "source_time": source_time,
            "published_at": published_at,
            "collected_at": collected_value,
            "available_at": available_at,
            "values": normalized,
            "missing_fields": list(missing),
            "trust_status": trust,
        }
        content_hash = stable_hash(payload)
        return cls(
            evidence_id=f"evidence_{content_hash[:20]}",
            asset_id=asset_id,
            symbol=symbol,
            category=category_value,
            source=source,
            source_version=normalized_source_version,
            source_status=str(source_status).lower(),
            source_time=source_time,
            published_at=published_at,
            collected_at=collected_value,
            available_at=available_at,
            trust_status=trust,
            values=normalized,
            missing_fields=missing,
            content_hash=content_hash,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "category": self.category,
            "source": self.source,
            "source_version": self.source_version,
            "source_status": self.source_status,
            "source_time": self.source_time,
            "published_at": self.published_at,
            "collected_at": self.collected_at,
            "available_at": self.available_at,
            "trust_status": self.trust_status,
            "values": dict(self.values),
            "missing_fields": list(self.missing_fields),
            "content_hash": self.content_hash,
        }


def save_evidence_snapshot(db_path: Path, snapshot: ExternalEvidenceSnapshot) -> dict[str, Any]:
    migrate(db_path)
    payload = snapshot.to_mapping()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO crypto_external_evidence(
              evidence_id,asset_id,symbol,category,source,source_status,source_time,
              published_at,available_at,trust_status,content_hash,payload_json,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                snapshot.evidence_id, snapshot.asset_id, snapshot.symbol, snapshot.category,
                snapshot.source, snapshot.source_status, snapshot.source_time,
                snapshot.published_at, snapshot.available_at, snapshot.trust_status,
                snapshot.content_hash, json.dumps(payload, ensure_ascii=True, sort_keys=True),
                datetime.now(UTC).isoformat(),
            ),
        )
    return payload


def list_latest_evidence(db_path: Path, asset_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT payload_json FROM crypto_external_evidence WHERE asset_id=? ORDER BY available_at DESC, created_at DESC LIMIT ?",
            (asset_id, max(1, min(int(limit), 200))),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def evidence_bundle(db_path: Path, asset_id: str) -> dict[str, Any]:
    items = list_latest_evidence(db_path, asset_id, limit=200)
    latest: dict[str, dict[str, Any]] = {}
    for item in items:
        latest.setdefault(str(item["category"]), item)
    return {
        "asset_id": asset_id,
        "items": latest,
        "missing_categories": [category for category in EvidenceCategory if category.value not in latest],
        "unknown_values_are_blocked": True,
        "not_available": "N/A",
        "research_only": True,
    }


def evidence_coverage(db_path: Path, asset_ids: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Return latest persisted coverage without treating presence as trust."""

    migrate(db_path)
    requested_assets = tuple(asset_ids or tuple(f"asset:{symbol.lower()}" for symbol in SUPPORTED_EVIDENCE_ASSETS))
    requested_by_symbol = {
        str(asset).removeprefix("asset:").upper(): str(asset)
        for asset in requested_assets
    }
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT asset_id, category, trust_status, source_status, available_at
            FROM crypto_external_evidence
            ORDER BY available_at DESC, created_at DESC
            """
        ).fetchall()
    for row in rows:
        key = (str(row["asset_id"]), str(row["category"]))
        latest.setdefault(key, dict(row))

    categories: dict[str, dict[str, Any]] = {}
    for category in EVIDENCE_FIELDS:
        expected_assets = tuple(
            requested_by_symbol[symbol]
            for symbol in EVIDENCE_ASSET_SCOPE.get(category, SUPPORTED_EVIDENCE_ASSETS)
            if symbol in requested_by_symbol
        )
        observed = sorted(asset for asset in expected_assets if (asset, category) in latest)
        verified = sorted(
            asset for asset in expected_assets
            if (item := latest.get((asset, category))) is not None
            and str(item.get("trust_status")) == "verified"
        )
        missing = sorted(set(expected_assets) - set(observed))
        categories[category] = {
            "expected_assets": list(expected_assets),
            "observed_assets": observed,
            "verified_assets": verified,
            "missing_assets": missing,
            "observed_ratio": round(len(observed) / len(expected_assets), 6) if expected_assets else 0.0,
            "verified_ratio": round(len(verified) / len(expected_assets), 6) if expected_assets else 0.0,
            "status": "complete" if len(verified) == len(expected_assets) and expected_assets else "partial" if observed else "not_collected",
        }
    return {
        "status": "available" if any(item["observed_assets"] for item in categories.values()) else "not_collected",
        "asset_count": len(requested_assets),
        "category_asset_scope": {key: list(value) for key, value in EVIDENCE_ASSET_SCOPE.items()},
        "categories": categories,
        "missing_value_policy": "N/A",
        "unknown_values_are_blocked": True,
        "research_only": True,
    }


__all__ = [
    "EvidenceCategory",
    "SUPPORTED_EVIDENCE_ASSETS",
    "EVIDENCE_FIELDS",
    "EVIDENCE_ASSET_SCOPE",
    "ExternalEvidenceSnapshot",
    "save_evidence_snapshot",
    "list_latest_evidence",
    "evidence_bundle",
    "evidence_coverage",
]
