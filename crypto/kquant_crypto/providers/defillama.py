from __future__ import annotations

"""Public, read-only DefiLlama evidence adapter.

Only metrics with an explicit provider contract are mapped. Market-wide
stablecoin supply is attached to BTC/ETH as market context, while protocol
TVL is attached only to the matching protocol token. No holder, whale, price,
or per-asset DEX metric is inferred from an aggregate response.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Callable

import httpx

from ..external_evidence import EvidenceCategory, ExternalEvidenceSnapshot


DEFILLAMA_API = "https://api.llama.fi"
DEFILLAMA_STABLECOINS_API = "https://stablecoins.llama.fi"
DEFILLAMA_EVIDENCE_VERSION = "crypto_defillama_public_v1.0.0"


class DefiLlamaProviderError(RuntimeError):
    """Raised when a public response cannot be used as evidence."""


@dataclass(frozen=True)
class DefiLlamaEvidenceResult:
    status: str
    snapshot: ExternalEvidenceSnapshot
    endpoint_status: dict[str, str]
    error_types: dict[str, str]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "snapshot": self.snapshot.to_mapping(),
            "endpoint_status": dict(self.endpoint_status),
            "error_types": dict(self.error_types),
            "collector_version": DEFILLAMA_EVIDENCE_VERSION,
            "research_only": True,
        }


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
        if not isfinite(numeric):
            return None
        if numeric > 100_000_000_000:
            numeric /= 1000.0
        return datetime.fromtimestamp(numeric, UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _latest_stablecoin_point(payload: Any) -> tuple[float | None, datetime | None]:
    if not isinstance(payload, list):
        return None, None
    points: list[tuple[datetime, float]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        value_container = row.get("totalCirculatingUSD")
        if isinstance(value_container, dict):
            value = _number(value_container.get("peggedUSD"))
        else:
            value = _number(value_container)
        timestamp = _timestamp(row.get("date"))
        if value is not None and timestamp is not None:
            points.append((timestamp, value))
    if not points:
        return None, None
    latest = max(points, key=lambda item: item[0])
    return latest[1], latest[0]


@dataclass
class DefiLlamaPublicAdapter:
    """Fetch selected DefiLlama public metrics without credentials."""

    timeout_seconds: float = 8.0
    requester: Callable[[str], Any] | None = None

    def fetch(
        self,
        *,
        asset_id: str,
        symbol: str,
        category: str,
        enabled: bool = True,
        available_at: datetime | None = None,
    ) -> DefiLlamaEvidenceResult:
        if not asset_id or not symbol:
            raise ValueError("asset_id and symbol are required")
        category_value = str(category).lower()
        symbol_value = str(symbol).strip().upper()
        if not enabled:
            return self._unavailable(
                asset_id=asset_id,
                symbol=symbol_value,
                category=category_value,
                status="provider_disabled",
                error_type="provider_disabled",
                available_at=available_at,
            )

        if category_value == EvidenceCategory.ONCHAIN.value and symbol_value in {"BTC", "ETH"}:
            requests = [(f"{DEFILLAMA_STABLECOINS_API}/stablecoincharts/all", "stablecoin_supply")]
        elif category_value == EvidenceCategory.PROTOCOL_METRIC.value:
            slug = {"AAVE": "aave", "ENA": "ethena"}.get(symbol_value)
            if slug is None:
                return self._unavailable(
                    asset_id=asset_id,
                    symbol=symbol_value,
                    category=category_value,
                    status="unsupported_asset",
                    error_type="unsupported_asset",
                    available_at=available_at,
                )
            requests = [(f"{DEFILLAMA_API}/tvl/{slug}", "tvl_usd")]
        else:
            return self._unavailable(
                asset_id=asset_id,
                symbol=symbol_value,
                category=category_value,
                status="unsupported_asset",
                error_type="unsupported_asset",
                available_at=available_at,
            )

        endpoint_status: dict[str, str] = {}
        error_types: dict[str, str] = {}
        values: dict[str, float] = {}
        source_times: list[datetime] = []
        captured_at = datetime.now(UTC)
        for url, field in requests:
            try:
                payload = self._get_json(url)
                if field == "stablecoin_supply":
                    value, source_time = _latest_stablecoin_point(payload)
                    if value is None:
                        raise DefiLlamaProviderError("stablecoin_series_missing")
                else:
                    value = _number(payload)
                    source_time = None
                    if value is None:
                        raise DefiLlamaProviderError("protocol_tvl_missing")
                values[field] = value
                if source_time:
                    source_times.append(source_time)
                endpoint_status[url] = "available"
            except (DefiLlamaProviderError, httpx.HTTPError, TimeoutError, OSError, TypeError, ValueError) as exc:
                endpoint_status[url] = "unavailable"
                error_types[url] = type(exc).__name__

        available_end = max(source_times + [captured_at])
        requested = available_at or captured_at
        requested = requested if requested.tzinfo else requested.replace(tzinfo=UTC)
        available = max(requested, captured_at, available_end)
        available_count = sum(status == "available" for status in endpoint_status.values())
        status = "complete" if available_count == len(requests) else "partial" if available_count else "provider_unavailable"
        snapshot = ExternalEvidenceSnapshot.create(
            asset_id=asset_id,
            symbol=symbol_value,
            category=category_value,
            source="defillama_public",
            source_version=DEFILLAMA_EVIDENCE_VERSION,
            source_status=status,
            source_time=max(source_times).isoformat() if source_times else None,
            available_at=available.isoformat(),
            values=values,
        )
        return DefiLlamaEvidenceResult(status, snapshot, endpoint_status, error_types)

    def _get_json(self, url: str) -> Any:
        if self.requester is not None:
            return self.requester(url)
        with httpx.Client(timeout=max(0.5, float(self.timeout_seconds)), follow_redirects=False) as client:
            response = client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            return response.json()

    def _unavailable(
        self,
        *,
        asset_id: str,
        symbol: str,
        category: str,
        status: str,
        error_type: str,
        available_at: datetime | None,
    ) -> DefiLlamaEvidenceResult:
        captured_at = datetime.now(UTC)
        requested = available_at or captured_at
        requested = requested if requested.tzinfo else requested.replace(tzinfo=UTC)
        snapshot = ExternalEvidenceSnapshot.create(
            asset_id=asset_id,
            symbol=symbol,
            category=category,
            source="defillama_public",
            source_version=DEFILLAMA_EVIDENCE_VERSION,
            source_status=status,
            available_at=max(requested, captured_at).isoformat(),
            values={},
        )
        return DefiLlamaEvidenceResult(
            status=status,
            snapshot=snapshot,
            endpoint_status={},
            error_types={"provider": error_type},
        )


__all__ = [
    "DEFILLAMA_API",
    "DEFILLAMA_STABLECOINS_API",
    "DEFILLAMA_EVIDENCE_VERSION",
    "DefiLlamaProviderError",
    "DefiLlamaEvidenceResult",
    "DefiLlamaPublicAdapter",
]
