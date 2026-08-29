from __future__ import annotations

"""Optional, read-only CoinGlass evidence adapter.

The adapter only reads public market-data endpoints. It never requests
account, wallet, order or execution resources, and it keeps provider fields
missing when the response does not contain an explicit value.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Callable, Mapping

import httpx

from ..external_evidence import EvidenceCategory, ExternalEvidenceSnapshot


COINGLASS_REST = "https://open-api-v4.coinglass.com"
COINGLASS_EVIDENCE_VERSION = "crypto_coinglass_evidence_v1.2.0"


class CoinGlassProviderError(RuntimeError):
    """Raised internally when the optional provider cannot supply a snapshot."""


@dataclass(frozen=True)
class CoinGlassEvidenceResult:
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
            "collector_version": COINGLASS_EVIDENCE_VERSION,
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
    if isinstance(value, (int, float)):
        numeric = float(value)
        if not isfinite(numeric):
            return None
        if numeric > 100_000_000_000:
            numeric /= 1000.0
        try:
            return datetime.fromtimestamp(numeric, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _pick(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("list", "rows", "items", "data"):
            candidate = data.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _latest_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    dated = [(row, _timestamp(_pick(row, "timestamp", "time", "ts", "updated_at", "date"))) for row in rows]
    dated = [(row, value) for row, value in dated if value is not None]
    return max(dated, key=lambda item: item[1])[0] if dated else rows[0]


def _latest_series_point(rows: list[dict[str, Any]]) -> tuple[float | None, datetime | None]:
    """Read a documented value/time series without inventing missing points."""

    points: list[tuple[datetime | None, float]] = []
    for row in rows:
        values = row.get("data_list")
        times = row.get("time_list")
        if not isinstance(values, (list, tuple)):
            continue
        if isinstance(times, (list, tuple)):
            for raw_value, raw_time in zip(values, times):
                value = _number(raw_value)
                if value is None:
                    continue
                points.append((_timestamp(raw_time), value))
        else:
            for raw_value in values:
                value = _number(raw_value)
                if value is not None:
                    points.append((None, value))
    if not points:
        return None, None
    dated = [point for point in points if point[0] is not None]
    if dated:
        return max(dated, key=lambda point: point[0])[1], max(dated, key=lambda point: point[0])[0]
    return points[-1][1], None


def _asset_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _etf_requests(symbol: str) -> list[tuple[str, dict[str, Any]]] | None:
    paths = {
        "BTC": [
            "/api/etf/bitcoin/flow-history",
            "/api/etf/bitcoin/net-assets/history",
            "/api/etf/bitcoin/premium-discount/history",
        ],
        "ETH": [
            "/api/etf/ethereum/flow-history",
            "/api/etf/ethereum/net-assets/history",
        ],
    }.get(symbol)
    return [(path, {}) for path in paths] if paths else None


def _onchain_requests(symbol: str) -> list[tuple[str, dict[str, Any]]]:
    """Return only CoinGlass endpoints with a documented symbol contract.

    The Bitcoin index endpoints are intentionally BTC-only.  We do not map a
    Bitcoin metric onto ETH or an altcoin simply because the provider has no
    equivalent endpoint for that asset.
    """

    requests: list[tuple[str, dict[str, Any]]] = [
        ("/api/exchange/balance/list", {"symbol": symbol}),
    ]
    if symbol == "BTC":
        requests.extend(
            [
                ("/api/index/stableCoin-marketCap-history", {}),
                ("/api/index/bitcoin-net-unrealized-profit-loss", {}),
                ("/api/index/bitcoin-sth-sopr", {}),
                ("/api/index/bitcoin-active-addresses", {}),
            ]
        )
    elif symbol == "ETH":
        # CoinGlass documents this as a market-wide index, so it is only
        # attached to the two core asset snapshots and never to altcoins.
        requests.append(("/api/index/stableCoin-marketCap-history", {}))
    return requests


def _whale_params(symbol: str, now: datetime) -> dict[str, Any]:
    end_ms = int(now.timestamp() * 1000)
    start_ms = end_ms - 24 * 60 * 60 * 1000
    return {"symbol": symbol, "start_time": start_ms, "end_time": end_ms}


def _history_total(rows: list[dict[str, Any]], field_names: tuple[str, ...], days: int) -> float | None:
    dated: list[tuple[datetime, float]] = []
    for row in rows:
        timestamp = _timestamp(_pick(row, "timestamp", "time", "ts", "updated_at", "date"))
        value = _number(_pick(row, *field_names))
        if timestamp is not None and value is not None:
            dated.append((timestamp, value))
    if not dated:
        return None
    latest = max(timestamp for timestamp, _ in dated)
    cutoff = latest - timedelta(days=days)
    return sum(value for timestamp, value in dated if cutoff <= timestamp <= latest)


@dataclass
class CoinGlassPublicAdapter:
    """Fetch explicit CoinGlass evidence with an optional API key."""

    api_key: str = ""
    base_url: str = COINGLASS_REST
    timeout_seconds: float = 8.0
    requester: Callable[..., Any] | None = None

    def fetch(
        self,
        *,
        asset_id: str,
        symbol: str,
        category: str,
        available_at: datetime | None = None,
    ) -> CoinGlassEvidenceResult:
        if not asset_id or not symbol:
            raise ValueError("asset_id and symbol are required")
        category_value = str(category).lower()
        symbol_value = _asset_symbol(symbol)
        request_list: list[tuple[str, dict[str, Any]]]
        if category_value == EvidenceCategory.EXCHANGE_DERIVATIVES.value:
            request_list = [("/api/futures/pairs-markets", {"symbol": symbol_value})]
        elif category_value == EvidenceCategory.ETF_FLOW.value:
            request_list = _etf_requests(symbol_value)
            if request_list is None:
                return self._unavailable(
                    asset_id=asset_id,
                    symbol=symbol_value,
                    category=category_value,
                    status="unsupported_asset",
                    error_type="unsupported_asset",
                    available_at=available_at,
                )
        elif category_value == EvidenceCategory.ONCHAIN.value:
            request_list = _onchain_requests(symbol_value)
        elif category_value == EvidenceCategory.WHALE.value:
            request_list = [("/api/chain/v2/whale-transfer", _whale_params(symbol_value, available_at or datetime.now(UTC)))]
        else:
            return self._unavailable(
                asset_id=asset_id,
                symbol=symbol_value,
                category=category_value,
                status="unsupported_category",
                error_type="unsupported_category",
                available_at=available_at,
            )

        try:
            endpoint_status: dict[str, str] = {}
            error_types: dict[str, str] = {}
            values: dict[str, float] = {}
            source_times: list[datetime] = []
            published_times: list[datetime] = []
            available_capture = datetime.now(UTC)
            for path, params in request_list:
                try:
                    payload = self._get_json(path, params=params)
                    rows = _rows(payload)
                    values.update(self._normalize_endpoint_values(category_value, path, rows))
                    row = _latest_row(rows)
                    source_time_value = _timestamp(_pick(row, "timestamp", "time", "ts", "updated_at", "date", "block_timestamp", "transaction_time"))
                    if path == "/api/index/stableCoin-marketCap-history":
                        _, series_time = _latest_series_point(rows)
                        source_time_value = series_time or source_time_value
                    published_value = _timestamp(_pick(row, "published_at", "publish_time", "published_time"))
                    if source_time_value:
                        source_times.append(source_time_value)
                    if published_value:
                        published_times.append(published_value)
                    endpoint_status[path] = "available"
                except (CoinGlassProviderError, httpx.HTTPError, TimeoutError, OSError, ValueError, TypeError, KeyError) as exc:
                    endpoint_status[path] = "unavailable"
                    error_types[path] = type(exc).__name__
            available_end = max(source_times + published_times + [available_capture])
            capture_time = datetime.now(UTC)
            requested = available_at or capture_time
            requested = requested if requested.tzinfo else requested.replace(tzinfo=UTC)
            available = max(requested, capture_time, available_end)
            available_count = sum(status == "available" for status in endpoint_status.values())
            if available_count == 0:
                status = "provider_unavailable"
            elif available_count == len(request_list):
                status = "complete"
            else:
                status = "partial"
            snapshot = ExternalEvidenceSnapshot.create(
                asset_id=asset_id,
                symbol=symbol_value,
                category=category_value,
                source="coinglass_optional",
                source_version=COINGLASS_EVIDENCE_VERSION,
                source_status=status,
                source_time=max(source_times).isoformat() if source_times else None,
                published_at=max(published_times).isoformat() if published_times else None,
                available_at=available.isoformat(),
                values=values,
            )
            return CoinGlassEvidenceResult(
                status=status,
                snapshot=snapshot,
                endpoint_status=endpoint_status,
                error_types=error_types,
            )
        except (CoinGlassProviderError, httpx.HTTPError, TimeoutError, OSError, ValueError, TypeError, KeyError) as exc:
            return self._unavailable(
                asset_id=asset_id,
                symbol=symbol_value,
                category=category_value,
                status="provider_unavailable",
                error_type=type(exc).__name__,
                path=request_list[0][0],
                available_at=available_at,
            )

    def _normalize_endpoint_values(
        self,
        category: str,
        path: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, float]:
        row = _latest_row(rows)
        values: dict[str, float] = {}
        if category == EvidenceCategory.EXCHANGE_DERIVATIVES.value:
            aliases = {
                "open_interest": ("open_interest_usd", "openInterest", "oi_usd"),
                "funding_rate": ("funding_rate", "fundingRate"),
                "basis": ("basis", "basis_rate"),
                # Long/short notional is not the same as aggressor flow, so
                # only explicit taker fields are accepted for these values.
                "active_buy_volume": ("taker_buy_volume_usd_5m", "taker_buy_volume_usd"),
                "active_sell_volume": ("taker_sell_volume_usd_5m", "taker_sell_volume_usd"),
                "cvd": ("cvd", "cvd_usd"),
                "spread_bps": ("spread_bps",),
                "depth_usd": ("depth_usd",),
            }
            for field, names in aliases.items():
                value = _number(_pick(row, *names))
                if value is not None:
                    values[field] = value
            direct_liquidations = _number(_pick(row, "liquidations_usd", "liquidation_usd"))
            if direct_liquidations is not None:
                values["liquidations_usd"] = direct_liquidations
            else:
                long_value = _number(_pick(row, "long_liquidation_usd_24h", "long_liquidation_usd"))
                short_value = _number(_pick(row, "short_liquidation_usd_24h", "short_liquidation_usd"))
                if long_value is not None and short_value is not None:
                    values["liquidations_usd"] = long_value + short_value
        elif category == EvidenceCategory.ETF_FLOW.value:
            if path.endswith("/flow-history"):
                value = _number(_pick(row, "flow_usd", "net_flow_usd", "flow", "net_flow"))
                if value is not None:
                    values["flow_usd"] = value
                flow_7d = _history_total(rows, ("flow_usd", "net_flow_usd", "flow", "net_flow"), 7)
                flow_30d = _history_total(rows, ("flow_usd", "net_flow_usd", "flow", "net_flow"), 30)
                if flow_7d is not None:
                    values["flow_7d_usd"] = flow_7d
                if flow_30d is not None:
                    values["flow_30d_usd"] = flow_30d
            elif path.endswith("/net-assets/history"):
                value = _number(_pick(row, "net_assets_usd", "aum_usd", "aum", "net_assets"))
                if value is not None:
                    values["aum_usd"] = value
            elif path.endswith("/premium-discount/history"):
                value = _number(_pick(row, "premium_discount", "premium_discount_percent", "premium", "discount"))
                items = row.get("list")
                if value is None and isinstance(items, list) and len(items) == 1:
                    item = items[0]
                    if isinstance(item, dict):
                        value = _number(_pick(item, "premium_discount_details", "premium_discount", "premium_discount_percent"))
                # The endpoint returns one value per ETF. Without an explicit
                # ticker, do not average several funds into a synthetic signal.
                if value is not None:
                    values["premium_discount"] = value
        elif category == EvidenceCategory.ONCHAIN.value:
            if path == "/api/exchange/balance/list":
                # This is the signed change in exchange-held balance, not a
                # claim about wallet-level inflow/outflow.  It is retained as
                # exchange_netflow only because the evidence schema exposes
                # that field; the source and formula remain auditable here.
                balance_values = [
                    value
                    for item in rows
                    if (value := _number(_pick(item, "balance_change_1d"))) is not None
                ]
                if balance_values:
                    balance_delta = sum(balance_values)
                    values["exchange_netflow"] = balance_delta
            elif path == "/api/index/bitcoin-net-unrealized-profit-loss":
                value = _number(_pick(row, "net_unpnl", "nupl"))
                if value is not None:
                    values["nupl"] = value
            elif path == "/api/index/stableCoin-marketCap-history":
                value, _ = _latest_series_point(rows)
                if value is not None:
                    values["stablecoin_supply"] = value
            elif path == "/api/index/bitcoin-sth-sopr":
                value = _number(_pick(row, "sth_sopr", "sopr"))
                if value is not None:
                    values["sopr"] = value
            elif path == "/api/index/bitcoin-active-addresses":
                value = _number(_pick(row, "active_address_count", "active_addresses"))
                if value is not None:
                    values["active_addresses"] = value
        elif category == EvidenceCategory.WHALE.value:
            amounts = [_number(_pick(item, "amount_usd", "value_usd")) for item in rows]
            amounts = [value for value in amounts if value is not None]
            if rows:
                values["large_transfer_count"] = float(len(rows))
            if amounts:
                values["large_transfer_volume_usd"] = float(sum(amounts))
            inflow = 0.0
            outflow = 0.0
            for item in rows:
                amount = _number(_pick(item, "amount_usd", "value_usd"))
                if amount is None:
                    continue
                transfer_type = _pick(item, "transfer_type")
                if str(transfer_type) == "1":
                    inflow += amount
                elif str(transfer_type) == "2":
                    outflow += amount
                else:
                    source = str(_pick(item, "from", "from_address") or "").lower()
                    target = str(_pick(item, "to", "to_address") or "").lower()
                    if "exchange" in target:
                        inflow += amount
                    if "exchange" in source:
                        outflow += amount
            if inflow:
                values["exchange_inflow_usd"] = inflow
            if outflow:
                values["exchange_outflow_usd"] = outflow
        return values

    def _get_json(self, path: str, *, params: Mapping[str, Any]) -> dict[str, Any]:
        if not self.api_key.strip():
            raise CoinGlassProviderError("api_key_missing")
        headers = {"Accept": "application/json", "CG-API-KEY": self.api_key.strip()}
        if self.requester is not None:
            payload = self.requester(path, params=params, headers=headers)
        else:
            with httpx.Client(timeout=max(0.5, float(self.timeout_seconds)), follow_redirects=False) as client:
                response = client.get(f"{self.base_url.rstrip('/')}{path}", params=dict(params), headers=headers)
                response.raise_for_status()
                payload = response.json()
        if not isinstance(payload, dict):
            raise CoinGlassProviderError("invalid_json_shape")
        code = payload.get("code")
        if code not in (None, 0, "0", 200, "200"):
            raise CoinGlassProviderError("provider_error")
        return payload

    def _unavailable(
        self,
        *,
        asset_id: str,
        symbol: str,
        category: str,
        status: str,
        error_type: str,
        available_at: datetime | None,
        path: str = "provider",
    ) -> CoinGlassEvidenceResult:
        now = datetime.now(UTC)
        requested = available_at or now
        requested = requested if requested.tzinfo else requested.replace(tzinfo=UTC)
        snapshot = ExternalEvidenceSnapshot.create(
            asset_id=asset_id,
            symbol=symbol,
            category=category,
            source="coinglass_optional",
            source_version=COINGLASS_EVIDENCE_VERSION,
            source_status="provider_unavailable",
            available_at=max(now, requested).isoformat(),
            values={},
        )
        return CoinGlassEvidenceResult(
            status=status,
            snapshot=snapshot,
            endpoint_status={path: "unavailable"},
            error_types={path: error_type},
        )


__all__ = [
    "COINGLASS_REST",
    "COINGLASS_EVIDENCE_VERSION",
    "CoinGlassEvidenceResult",
    "CoinGlassProviderError",
    "CoinGlassPublicAdapter",
]
