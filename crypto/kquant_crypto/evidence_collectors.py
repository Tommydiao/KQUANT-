from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from .external_evidence import EVIDENCE_FIELDS, ExternalEvidenceSnapshot


@dataclass(frozen=True)
class EvidenceSourceSpec:
    source: str
    categories: tuple[str, ...]
    configuration_env: str | None
    public_only: bool = True

    def to_mapping(self) -> dict[str, Any]:
        configured = True if self.configuration_env is None else bool(os.getenv(self.configuration_env, "").strip())
        return {
            "source": self.source,
            "categories": list(self.categories),
            "configuration_env": self.configuration_env,
            "configured": configured,
            "public_only": self.public_only,
            "status": "configured" if configured else "not_configured",
            "secrets_exposed": False,
        }


EVIDENCE_SOURCE_SPECS: tuple[EvidenceSourceSpec, ...] = (
    EvidenceSourceSpec("binance_public_derivatives", ("exchange_derivatives",), None),
    EvidenceSourceSpec("binance_public_market_structure", ("market_structure",), None),
    EvidenceSourceSpec("okx_public_derivatives", ("exchange_derivatives",), None),
    EvidenceSourceSpec("official_etf_feed", ("etf_flow",), "KQUANT_CRYPTO_ETF_EVIDENCE_URL"),
    EvidenceSourceSpec("etf_flow_feed", ("etf_flow",), "KQUANT_CRYPTO_ETF_EVIDENCE_URL"),
    EvidenceSourceSpec("coinglass_optional", ("exchange_derivatives", "etf_flow", "onchain", "whale"), "COINGLASS_API_KEY"),
    EvidenceSourceSpec("defillama_public", ("onchain", "protocol_metric"), "KQUANT_CRYPTO_ENABLE_DEFILLAMA"),
    EvidenceSourceSpec("birdeye_optional", ("onchain", "whale", "market_structure"), "BIRDEYE_API_KEY"),
    EvidenceSourceSpec("goplus_security", ("onchain",), "GOPLUS_API_KEY"),
    EvidenceSourceSpec("onchain_metrics_feed", ("onchain", "whale"), "KQUANT_CRYPTO_ONCHAIN_EVIDENCE_URL"),
)


def evidence_source_capabilities() -> dict[str, Any]:
    return {
        "items": [item.to_mapping() for item in EVIDENCE_SOURCE_SPECS],
        "categories": {key: list(value) for key, value in EVIDENCE_FIELDS.items()},
        "missing_value_policy": "N/A",
        "unknown_values_are_blocked": True,
        "research_only": True,
    }


def normalize_provider_evidence(
    payload: Mapping[str, Any],
    *,
    source: str,
    source_version: str = "",
    category: str,
    asset_id: str,
    symbol: str,
    source_status: str,
    available_at: str,
    source_time: str | None = None,
    published_at: str | None = None,
    collected_at: str | None = None,
) -> ExternalEvidenceSnapshot:
    if source not in {item.source for item in EVIDENCE_SOURCE_SPECS}:
        raise ValueError(f"unregistered evidence source: {source}")
    values = {
        str(key): value
        for key, value in payload.items()
        if str(key) in EVIDENCE_FIELDS.get(str(category).lower(), ())
    }
    return ExternalEvidenceSnapshot.create(
        asset_id=asset_id,
        symbol=symbol,
        category=category,
        source=source,
        source_version=source_version or source,
        source_status=source_status,
        source_time=source_time,
        published_at=published_at,
        collected_at=collected_at,
        available_at=available_at,
        values=values,
    )


def fetch_configured_evidence(
    *,
    url: str,
    source: str,
    category: str,
    asset_id: str,
    symbol: str,
    timeout_seconds: float = 4.0,
) -> dict[str, Any]:
    """Fetch a user-controlled JSON evidence feed without inventing values.

    The feed contract is deliberately narrow: either a flat field mapping or
    ``{"values": {...}, "source_time": ..., "published_at": ...}`` is
    accepted.  A timeout, non-JSON response, or unknown shape becomes a
    data-caution snapshot with all fields missing.  This function is not
    called by the realtime signal loop, so a slow research feed cannot delay
    market data or change a signal by itself.
    """

    from datetime import UTC, datetime

    if not str(url or "").strip():
        now = datetime.now(UTC).isoformat()
        snapshot = normalize_provider_evidence(
            {}, source=source, category=category, asset_id=asset_id, symbol=symbol,
            source_status="provider_unavailable", available_at=now,
        )
        return {"status": "not_configured", "snapshot": snapshot.to_mapping(), "research_only": True}
    try:
        response = httpx.get(str(url), timeout=max(0.5, float(timeout_seconds)), follow_redirects=False)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("evidence response must be a JSON object")
        values = body.get("values") if isinstance(body.get("values"), dict) else body
        source_time = body.get("source_time") if isinstance(body.get("source_time"), str) else None
        published_at = body.get("published_at") if isinstance(body.get("published_at"), str) else None
        source_version = body.get("source_version") if isinstance(body.get("source_version"), str) else source
        collected_at = body.get("collected_at") if isinstance(body.get("collected_at"), str) else None
        # Capture after the response arrives. If the provider clock is slightly
        # ahead, keep the source timestamp and move availability forward rather
        # than silently rejecting an otherwise usable snapshot.
        available_dt = datetime.now(UTC)
        for candidate in (source_time, published_at):
            if candidate:
                try:
                    parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
                    parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
                    available_dt = max(available_dt, parsed)
                except ValueError:
                    pass
        snapshot = normalize_provider_evidence(
            values, source=source, category=category, asset_id=asset_id, symbol=symbol,
            source_status="complete", available_at=available_dt.isoformat(), source_time=source_time,
            published_at=published_at, source_version=source_version, collected_at=collected_at,
        )
        return {"status": "available", "snapshot": snapshot.to_mapping(), "research_only": True}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        now = datetime.now(UTC).isoformat()
        snapshot = normalize_provider_evidence(
            {}, source=source, category=category, asset_id=asset_id, symbol=symbol,
            source_status="provider_unavailable", available_at=now,
        )
        return {
            "status": "provider_unavailable",
            "snapshot": snapshot.to_mapping(),
            "error_type": type(exc).__name__,
            "research_only": True,
        }


__all__ = [
    "EvidenceSourceSpec",
    "EVIDENCE_SOURCE_SPECS",
    "evidence_source_capabilities",
    "normalize_provider_evidence",
    "fetch_configured_evidence",
]
