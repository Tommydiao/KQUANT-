from __future__ import annotations

"""Public Binance market-structure evidence.

Only values explicit in the public 24-hour ticker response are mapped. BTC
dominance and a market regime require separate datasets and remain N/A here.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Mapping

import httpx

from .binance_endpoints import SPOT_MARKET_DATA_REST
from .external_evidence import EvidenceCategory, ExternalEvidenceSnapshot


BINANCE_SPOT_REST = SPOT_MARKET_DATA_REST
MARKET_STRUCTURE_EVIDENCE_VERSION = "crypto_market_structure_public_v1.0.0"


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _normalize_symbols(symbols: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    values = []
    for value in symbols:
        symbol = str(value or "").strip().upper().replace("/", "").replace("-", "")
        if symbol and symbol.endswith(("USDT", "USDC", "USD")):
            values.append(symbol)
    required = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    return tuple(dict.fromkeys((*required, *values)))[:100]


@dataclass(frozen=True)
class MarketStructureEvidenceResult:
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
            "collector_version": MARKET_STRUCTURE_EVIDENCE_VERSION,
            "research_only": True,
        }


def _get_json(client: Any, path: str, *, params: Mapping[str, Any]) -> Any:
    response = client.get(f"{BINANCE_SPOT_REST}{path}", params=dict(params))
    response.raise_for_status()
    return response.json()


def fetch_binance_market_structure_evidence(
    *,
    asset_id: str,
    symbol: str = "BTC",
    universe_symbols: tuple[str, ...] | list[str] = (),
    client: Any | None = None,
    available_at: datetime | None = None,
    timeout_seconds: float = 4.0,
) -> MarketStructureEvidenceResult:
    """Fetch a point-in-time market breadth and relative-strength snapshot."""

    if not asset_id or not symbol:
        raise ValueError("asset_id and symbol are required")
    requested_symbols = _normalize_symbols(tuple(universe_symbols))
    created_client = client is None
    http = client or httpx.Client(timeout=max(0.5, float(timeout_seconds)), follow_redirects=False)
    endpoint_status: dict[str, str] = {}
    error_types: dict[str, str] = {}
    response: Any = None
    try:
        try:
            response = _get_json(
                http,
                "/api/v3/ticker/24hr",
                params={"symbols": json.dumps(list(requested_symbols), separators=(",", ":"))},
            )
            endpoint_status["ticker_24h"] = "available"
        except (httpx.HTTPError, TimeoutError, OSError, ValueError, TypeError, KeyError) as exc:
            endpoint_status["ticker_24h"] = "unavailable"
            error_types["ticker_24h"] = type(exc).__name__
    finally:
        if created_client:
            http.close()

    rows = response if isinstance(response, list) else []
    prices: dict[str, float] = {}
    changes: dict[str, float] = {}
    source_times: list[datetime] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        instrument = str(row.get("symbol") or "").upper()
        price = _number(row.get("lastPrice"))
        change = _number(row.get("priceChangePercent"))
        if instrument and price is not None and price > 0:
            prices[instrument] = price
        if instrument and change is not None:
            changes[instrument] = change
        if (timestamp := _timestamp(row.get("closeTime"))):
            source_times.append(timestamp)

    values: dict[str, float] = {}
    alt_symbols = tuple(item for item in requested_symbols if item not in {"BTCUSDT", "ETHUSDT", "SOLUSDT"})
    breadth_symbols = alt_symbols or requested_symbols
    breadth_changes = [changes[item] for item in breadth_symbols if item in changes]
    if breadth_changes:
        values["breadth"] = sum(change > 0 for change in breadth_changes) / len(breadth_changes)
    if prices.get("BTCUSDT") and prices.get("ETHUSDT"):
        values["eth_btc"] = prices["ETHUSDT"] / prices["BTCUSDT"]
    if prices.get("BTCUSDT") and prices.get("SOLUSDT"):
        values["sol_btc"] = prices["SOLUSDT"] / prices["BTCUSDT"]

    captured_at = datetime.now(UTC)
    requested = available_at or captured_at
    requested = requested if requested.tzinfo else requested.replace(tzinfo=UTC)
    available = max(requested, captured_at, *source_times)
    endpoint_ok = endpoint_status.get("ticker_24h") == "available"
    status = "complete" if endpoint_ok and all(
        field in values for field in ("breadth", "eth_btc", "sol_btc")
    ) else "partial" if endpoint_ok else "provider_unavailable"
    snapshot = ExternalEvidenceSnapshot.create(
        asset_id=asset_id,
        symbol=str(symbol).upper(),
        category=EvidenceCategory.MARKET_STRUCTURE.value,
        source="binance_public_market_structure",
        source_version=MARKET_STRUCTURE_EVIDENCE_VERSION,
        source_status=status,
        source_time=max(source_times).isoformat() if source_times else None,
        available_at=available.isoformat(),
        values=values,
    )
    return MarketStructureEvidenceResult(status, snapshot, endpoint_status, error_types)


__all__ = [
    "BINANCE_SPOT_REST",
    "MARKET_STRUCTURE_EVIDENCE_VERSION",
    "MarketStructureEvidenceResult",
    "fetch_binance_market_structure_evidence",
]
