from __future__ import annotations

"""Public, read-only evidence collectors.

The collector intentionally uses endpoints that do not require exchange
account credentials.  Each Binance endpoint is independent: one failed
endpoint makes its fields unavailable, but never turns a partial response
into a complete evidence snapshot.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Mapping

import httpx

from .external_evidence import EvidenceCategory, ExternalEvidenceSnapshot


BINANCE_FUTURES_REST = "https://fapi.binance.com"
OKX_PUBLIC_REST = "https://www.okx.com"
PUBLIC_EVIDENCE_VERSION = "crypto_public_evidence_v1.2.0"


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    return current if current.tzinfo else current.replace(tzinfo=UTC)


def _iso_from_ms(value: Any) -> str | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(parsed / 1000.0, UTC).isoformat()


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _symbol(value: str) -> str:
    upper = str(value or "").upper().replace("/", "").replace("-", "")
    return upper if upper.endswith(("USDT", "USDC", "USD")) else f"{upper}USDT"


@dataclass(frozen=True)
class PublicEvidenceResult:
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
            "collector_version": PUBLIC_EVIDENCE_VERSION,
            "research_only": True,
        }


def _get_json(client: Any, path: str, *, params: Mapping[str, Any]) -> Any:
    response = client.get(f"{BINANCE_FUTURES_REST}{path}", params=dict(params))
    response.raise_for_status()
    return response.json()


def _get_okx_json(client: Any, path: str, *, params: Mapping[str, Any]) -> Any:
    response = client.get(f"{OKX_PUBLIC_REST}{path}", params=dict(params))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or str(payload.get("code") or "") != "0":
        raise ValueError("OKX public response did not return code 0")
    return payload.get("data")


def fetch_binance_derivatives_evidence(
    *,
    asset_id: str,
    symbol: str,
    client: Any | None = None,
    available_at: datetime | None = None,
    timeout_seconds: float = 4.0,
) -> PublicEvidenceResult:
    """Fetch a point-in-time derivatives snapshot from public Binance APIs."""

    if not asset_id or not symbol:
        raise ValueError("asset_id and symbol are required")
    created_client = client is None
    http = client or httpx.Client(timeout=max(0.5, float(timeout_seconds)), follow_redirects=False)
    requested_available = _now(available_at) if available_at is not None else None
    instrument = _symbol(symbol)
    endpoints = {
        "premium_index": ("/fapi/v1/premiumIndex", {"symbol": instrument}),
        "open_interest": ("/fapi/v1/openInterest", {"symbol": instrument}),
        "funding_rate": ("/fapi/v1/fundingRate", {"symbol": instrument, "limit": 1}),
        "depth": ("/fapi/v1/depth", {"symbol": instrument, "limit": 20}),
        "agg_trades": ("/fapi/v1/aggTrades", {"symbol": instrument, "limit": 1000}),
        "force_orders": ("/fapi/v1/allForceOrders", {"symbol": instrument, "limit": 100}),
    }
    responses: dict[str, Any] = {}
    endpoint_status: dict[str, str] = {}
    error_types: dict[str, str] = {}
    try:
        for name, (path, params) in endpoints.items():
            try:
                responses[name] = _get_json(http, path, params=params)
                endpoint_status[name] = "available"
            except (httpx.HTTPError, TimeoutError, OSError, ValueError, TypeError, KeyError) as exc:
                endpoint_status[name] = "unavailable"
                error_types[name] = type(exc).__name__
    finally:
        if created_client:
            http.close()

    values: dict[str, Any] = {}
    source_times: list[datetime] = []
    premium = responses.get("premium_index")
    if isinstance(premium, dict):
        funding = _number(premium.get("lastFundingRate"))
        mark = _number(premium.get("markPrice"))
        index = _number(premium.get("indexPrice"))
        if funding is not None:
            values["funding_rate"] = funding
        if mark is not None:
            values["mark_price"] = mark
        if index is not None:
            values["index_price"] = index
        if mark is not None and index is not None and index > 0:
            values["basis"] = (mark / index) - 1.0
        if (timestamp := _iso_from_ms(premium.get("time"))):
            source_times.append(datetime.fromisoformat(timestamp))

    open_interest = responses.get("open_interest")
    if isinstance(open_interest, dict) and (number := _number(open_interest.get("openInterest"))) is not None:
        values["open_interest"] = number
        if (timestamp := _iso_from_ms(open_interest.get("time"))):
            source_times.append(datetime.fromisoformat(timestamp))

    funding_rows = responses.get("funding_rate")
    if isinstance(funding_rows, list) and funding_rows:
        row = funding_rows[-1]
        if isinstance(row, dict):
            funding = _number(row.get("fundingRate"))
            if funding is not None:
                values["funding_rate"] = funding
            if (timestamp := _iso_from_ms(row.get("fundingTime"))):
                source_times.append(datetime.fromisoformat(timestamp))

    depth = responses.get("depth")
    if isinstance(depth, dict):
        bids = depth.get("bids") if isinstance(depth.get("bids"), list) else []
        asks = depth.get("asks") if isinstance(depth.get("asks"), list) else []
        bid = _number(bids[0][0]) if bids and isinstance(bids[0], list) and len(bids[0]) >= 2 else None
        ask = _number(asks[0][0]) if asks and isinstance(asks[0], list) and len(asks[0]) >= 2 else None
        if bid is not None and ask is not None and ask >= bid and (mid := (bid + ask) / 2.0) > 0:
            values["spread_bps"] = (ask - bid) / mid * 10000.0
        depth_usd = 0.0
        depth_rows = 0
        for row in [*bids[:20], *asks[:20]]:
            if isinstance(row, list) and len(row) >= 2:
                price = _number(row[0])
                quantity = _number(row[1])
                if price is not None and quantity is not None and price >= 0 and quantity >= 0:
                    depth_usd += price * quantity
                    depth_rows += 1
        if depth_rows:
            values["depth_usd"] = depth_usd
        if (timestamp := _iso_from_ms(depth.get("E") or depth.get("T"))):
            source_times.append(datetime.fromisoformat(timestamp))

    agg_trades = responses.get("agg_trades")
    active_buy = 0.0
    active_sell = 0.0
    trade_count = 0
    if isinstance(agg_trades, list):
        for row in agg_trades:
            if not isinstance(row, dict):
                continue
            price = _number(row.get("p"))
            quantity = _number(row.get("q"))
            if price is None or quantity is None or price < 0 or quantity < 0:
                continue
            notional = price * quantity
            # Binance `m=true` means the buyer was the maker, so the seller
            # was the aggressor for this aggregate trade.
            if bool(row.get("m")):
                active_sell += notional
            else:
                active_buy += notional
            trade_count += 1
            if (timestamp := _iso_from_ms(row.get("T") or row.get("time"))):
                source_times.append(datetime.fromisoformat(timestamp))
    if trade_count:
        values["active_buy_volume"] = active_buy
        values["active_sell_volume"] = active_sell
        values["cvd"] = active_buy - active_sell

    force_orders = responses.get("force_orders")
    liquidation_value = 0.0
    liquidation_count = 0
    if isinstance(force_orders, list):
        for row in force_orders:
            if not isinstance(row, dict):
                continue
            price = _number(row.get("price") or row.get("ap"))
            quantity = _number(row.get("origQty") or row.get("executedQty") or row.get("q"))
            if price is None or quantity is None or price < 0 or quantity < 0:
                continue
            liquidation_value += price * quantity
            liquidation_count += 1
            if (timestamp := _iso_from_ms(row.get("time") or row.get("T"))):
                source_times.append(datetime.fromisoformat(timestamp))
    if liquidation_count:
        values["liquidations_usd"] = liquidation_value

    # Provider clocks can be a few milliseconds ahead of the local clock. The
    # snapshot becomes available only after the request batch has completed,
    # so clamp available_at to the later of the requested/capture time and the
    # newest source timestamp. This preserves PIT ordering without inventing
    # a source value or silently discarding an otherwise valid response.
    capture_time = _now()
    available_time = max(requested_available or capture_time, capture_time, *source_times)
    available = available_time.isoformat()
    source_time = max(source_times).isoformat() if source_times else None
    successful = sum(status == "available" for status in endpoint_status.values())
    if successful == len(endpoints):
        status = "complete"
    elif successful:
        status = "partial"
    else:
        status = "provider_unavailable"
    snapshot = ExternalEvidenceSnapshot.create(
        asset_id=asset_id,
        symbol=symbol.upper(),
        category=EvidenceCategory.EXCHANGE_DERIVATIVES.value,
        source="binance_public_derivatives",
        source_version=PUBLIC_EVIDENCE_VERSION,
        source_status=status,
        source_time=source_time,
        available_at=available,
        values=values,
    )
    return PublicEvidenceResult(status=status, snapshot=snapshot, endpoint_status=endpoint_status, error_types=error_types)


def _okx_instrument(symbol: str) -> str:
    normalized = str(symbol or "").upper().replace("/", "-")
    if normalized.endswith("-USDT-SWAP"):
        return normalized
    if normalized.endswith("USDT"):
        normalized = normalized[:-4]
    return f"{normalized}-USDT-SWAP"


def fetch_okx_derivatives_evidence(
    *,
    asset_id: str,
    symbol: str,
    client: Any | None = None,
    available_at: datetime | None = None,
    timeout_seconds: float = 4.0,
) -> PublicEvidenceResult:
    """Fetch a point-in-time OKX public SWAP snapshot without credentials."""

    if not asset_id or not symbol:
        raise ValueError("asset_id and symbol are required")
    created_client = client is None
    http = client or httpx.Client(timeout=max(0.5, float(timeout_seconds)), follow_redirects=False)
    requested_available = _now(available_at) if available_at is not None else None
    instrument = _okx_instrument(symbol)
    endpoints = {
        "mark_price": ("/api/v5/public/mark-price", {"instType": "SWAP", "instId": instrument}),
        "index_ticker": ("/api/v5/market/index-tickers", {"instId": f"{str(symbol).upper()}-USDT"}),
        "open_interest": ("/api/v5/public/open-interest", {"instType": "SWAP", "instId": instrument}),
        "funding_rate": ("/api/v5/public/funding-rate", {"instId": instrument}),
        "depth": ("/api/v5/market/books", {"instId": instrument, "sz": "20"}),
        "trades": ("/api/v5/market/trades", {"instId": instrument, "limit": "500"}),
    }
    responses: dict[str, Any] = {}
    endpoint_status: dict[str, str] = {}
    error_types: dict[str, str] = {}
    try:
        for name, (path, params) in endpoints.items():
            try:
                responses[name] = _get_okx_json(http, path, params=params)
                endpoint_status[name] = "available"
            except (httpx.HTTPError, TimeoutError, OSError, ValueError, TypeError, KeyError) as exc:
                endpoint_status[name] = "unavailable"
                error_types[name] = type(exc).__name__
    finally:
        if created_client:
            http.close()

    values: dict[str, Any] = {}
    source_times: list[datetime] = []
    mark_rows = responses.get("mark_price")
    mark = mark_rows[0] if isinstance(mark_rows, list) and mark_rows and isinstance(mark_rows[0], dict) else {}
    mark_price = _number(mark.get("markPx") or mark.get("markPrice"))
    if mark_price is not None:
        values["mark_price"] = mark_price
    if (timestamp := _iso_from_ms(mark.get("ts"))):
        source_times.append(datetime.fromisoformat(timestamp))

    index_rows = responses.get("index_ticker")
    index = index_rows[0] if isinstance(index_rows, list) and index_rows and isinstance(index_rows[0], dict) else {}
    index_price = _number(index.get("idxPx") or index.get("indexPx"))
    if index_price is not None:
        values["index_price"] = index_price
    if mark_price is not None and index_price is not None and index_price > 0:
        values["basis"] = (mark_price / index_price) - 1.0
    if (timestamp := _iso_from_ms(index.get("ts"))):
        source_times.append(datetime.fromisoformat(timestamp))

    oi_rows = responses.get("open_interest")
    oi = oi_rows[0] if isinstance(oi_rows, list) and oi_rows and isinstance(oi_rows[0], dict) else {}
    if (open_interest := _number(oi.get("oi"))) is not None:
        values["open_interest"] = open_interest
    if (timestamp := _iso_from_ms(oi.get("ts"))):
        source_times.append(datetime.fromisoformat(timestamp))

    funding_rows = responses.get("funding_rate")
    funding = funding_rows[0] if isinstance(funding_rows, list) and funding_rows and isinstance(funding_rows[0], dict) else {}
    if (funding_rate := _number(funding.get("fundingRate"))) is not None:
        values["funding_rate"] = funding_rate
    if (timestamp := _iso_from_ms(funding.get("fundingTime"))):
        source_times.append(datetime.fromisoformat(timestamp))

    depth_rows = responses.get("depth")
    depth = depth_rows[0] if isinstance(depth_rows, list) and depth_rows and isinstance(depth_rows[0], dict) else {}
    bids = depth.get("bids") if isinstance(depth.get("bids"), list) else []
    asks = depth.get("asks") if isinstance(depth.get("asks"), list) else []
    bid = _number(bids[0][0]) if bids and isinstance(bids[0], list) and len(bids[0]) >= 2 else None
    ask = _number(asks[0][0]) if asks and isinstance(asks[0], list) and len(asks[0]) >= 2 else None
    if bid is not None and ask is not None and ask >= bid and (mid := (bid + ask) / 2.0) > 0:
        values["spread_bps"] = (ask - bid) / mid * 10000.0
    depth_usd = 0.0
    depth_count = 0
    for row in [*bids[:20], *asks[:20]]:
        if isinstance(row, list) and len(row) >= 2:
            price = _number(row[0])
            quantity = _number(row[1])
            if price is not None and quantity is not None and price >= 0 and quantity >= 0:
                depth_usd += price * quantity
                depth_count += 1
    if depth_count:
        values["depth_usd"] = depth_usd
    if (timestamp := _iso_from_ms(depth.get("ts"))):
        source_times.append(datetime.fromisoformat(timestamp))

    trades = responses.get("trades")
    active_buy = 0.0
    active_sell = 0.0
    trade_count = 0
    if isinstance(trades, list):
        for row in trades:
            if not isinstance(row, dict):
                continue
            price = _number(row.get("px"))
            quantity = _number(row.get("sz"))
            if price is None or quantity is None or price < 0 or quantity < 0:
                continue
            notional = price * quantity
            if str(row.get("side") or "").lower() == "buy":
                active_buy += notional
            else:
                active_sell += notional
            trade_count += 1
            if (timestamp := _iso_from_ms(row.get("ts"))):
                source_times.append(datetime.fromisoformat(timestamp))
    if trade_count:
        values["active_buy_volume"] = active_buy
        values["active_sell_volume"] = active_sell
        values["cvd"] = active_buy - active_sell

    capture_time = _now()
    available_time = max(requested_available or capture_time, capture_time, *source_times)
    source_time = max(source_times).isoformat() if source_times else None
    successful = sum(status == "available" for status in endpoint_status.values())
    status = "complete" if successful == len(endpoints) else "partial" if successful else "provider_unavailable"
    snapshot = ExternalEvidenceSnapshot.create(
        asset_id=asset_id,
        symbol=symbol.upper(),
        category=EvidenceCategory.EXCHANGE_DERIVATIVES.value,
        source="okx_public_derivatives",
        source_version=PUBLIC_EVIDENCE_VERSION,
        source_status=status,
        source_time=source_time,
        available_at=available_time.isoformat(),
        values=values,
    )
    return PublicEvidenceResult(status=status, snapshot=snapshot, endpoint_status=endpoint_status, error_types=error_types)


__all__ = [
    "BINANCE_FUTURES_REST",
    "OKX_PUBLIC_REST",
    "PUBLIC_EVIDENCE_VERSION",
    "PublicEvidenceResult",
    "fetch_binance_derivatives_evidence",
    "fetch_okx_derivatives_evidence",
]
