from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlencode

import httpx


class BinanceExecutionError(RuntimeError):
    pass


class BinanceUnknownExecutionState(BinanceExecutionError):
    """A write request failed without proving whether Binance accepted it."""


@dataclass(frozen=True)
class BinanceCredentials:
    api_key: str
    api_secret: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


def sign_query(params: Mapping[str, Any], secret: str) -> str:
    query = urlencode([(key, value) for key, value in params.items() if value is not None])
    signature = hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


class BinanceExecutionClient:
    """Minimal signed Binance client with explicit Spot and USD-M scopes."""

    def __init__(
        self,
        credentials: BinanceCredentials,
        *,
        spot_base_url: str,
        futures_base_url: str,
        timeout: float = 10.0,
        recv_window_ms: int = 5000,
        clock_ms: Callable[[], int] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        if not credentials.configured:
            raise ValueError("Binance credentials are not configured")
        self.credentials = credentials
        self.spot_base_url = spot_base_url.rstrip("/")
        self.futures_base_url = futures_base_url.rstrip("/")
        self.recv_window_ms = min(5000, max(1000, int(recv_window_ms)))
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.client = httpx.Client(timeout=max(1.0, float(timeout)), transport=transport)
        self._clock_offset_ms = 0

    def close(self) -> None:
        self.client.close()

    def _base_url(self, market_type: str) -> str:
        return self.futures_base_url if market_type == "perpetual" else self.spot_base_url

    def _request(
        self,
        method: str,
        path: str,
        *,
        market_type: str,
        params: Mapping[str, Any] | None = None,
        signed: bool = True,
        write: bool = False,
    ) -> Any:
        values = dict(params or {})
        headers = {"X-MBX-APIKEY": self.credentials.api_key}
        if signed:
            values["timestamp"] = self.clock_ms() + self._clock_offset_ms
            values["recvWindow"] = self.recv_window_ms
            query = sign_query(values, self.credentials.api_secret)
        else:
            query = urlencode(values)
        url = f"{self._base_url(market_type)}{path}"
        if query:
            url = f"{url}?{query}"
        try:
            response = self.client.request(method, url, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            error = BinanceUnknownExecutionState if write else BinanceExecutionError
            raise error(type(exc).__name__) from exc
        if write and response.status_code >= 500:
            raise BinanceUnknownExecutionState(f"binance_http_{response.status_code}")
        if response.status_code >= 400:
            try:
                payload = response.json()
                code = payload.get("code")
                message = payload.get("msg")
            except (ValueError, AttributeError):
                code, message = response.status_code, "request_rejected"
            raise BinanceExecutionError(f"binance_rejected:{code}:{message}")
        try:
            return response.json()
        except ValueError as exc:
            raise BinanceExecutionError("binance_invalid_json") from exc

    def sync_clock(self, market_type: str) -> int:
        path = "/fapi/v1/time" if market_type == "perpetual" else "/api/v3/time"
        payload = self._request("GET", path, market_type=market_type, signed=False)
        server_time = int(payload["serverTime"])
        self._clock_offset_ms = server_time - self.clock_ms()
        return self._clock_offset_ms

    def exchange_info(self, market_type: str, symbol: str | None = None) -> dict[str, Any]:
        path = "/fapi/v1/exchangeInfo" if market_type == "perpetual" else "/api/v3/exchangeInfo"
        payload = self._request("GET", path, market_type=market_type, params={"symbol": symbol}, signed=False)
        return dict(payload)

    def ticker_price(self, market_type: str, symbol: str) -> float:
        path = "/fapi/v2/ticker/price" if market_type == "perpetual" else "/api/v3/ticker/price"
        payload = self._request("GET", path, market_type=market_type, params={"symbol": symbol}, signed=False)
        return float(payload["price"])

    def account(self, market_type: str) -> dict[str, Any]:
        path = "/fapi/v2/account" if market_type == "perpetual" else "/api/v3/account"
        return dict(self._request("GET", path, market_type=market_type))

    def positions(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/fapi/v2/positionRisk", market_type="perpetual")
        return [dict(item) for item in payload]

    def open_orders(self, market_type: str, symbol: str | None = None) -> list[dict[str, Any]]:
        path = "/fapi/v1/openOrders" if market_type == "perpetual" else "/api/v3/openOrders"
        payload = self._request("GET", path, market_type=market_type, params={"symbol": symbol})
        return [dict(item) for item in payload]

    def query_order(self, market_type: str, symbol: str, client_order_id: str) -> dict[str, Any]:
        path = "/fapi/v1/order" if market_type == "perpetual" else "/api/v3/order"
        return dict(self._request("GET", path, market_type=market_type, params={"symbol": symbol, "origClientOrderId": client_order_id}))

    def place_order(self, market_type: str, params: Mapping[str, Any]) -> dict[str, Any]:
        path = "/fapi/v1/order" if market_type == "perpetual" else "/api/v3/order"
        return dict(self._request("POST", path, market_type=market_type, params=params, write=True))

    def place_spot_oco(self, params: Mapping[str, Any]) -> dict[str, Any]:
        return dict(self._request("POST", "/api/v3/orderList/oco", market_type="spot", params=params, write=True))

    def cancel_order(self, market_type: str, symbol: str, client_order_id: str) -> dict[str, Any]:
        path = "/fapi/v1/order" if market_type == "perpetual" else "/api/v3/order"
        return dict(self._request("DELETE", path, market_type=market_type, params={"symbol": symbol, "origClientOrderId": client_order_id}, write=True))

    def configure_futures_symbol(self, symbol: str, leverage: int) -> list[dict[str, Any]]:
        leverage = min(2, max(1, int(leverage)))
        results = [dict(self._request("POST", "/fapi/v1/positionSide/dual", market_type="perpetual", params={"dualSidePosition": "false"}, write=True))]
        try:
            results.append(dict(self._request("POST", "/fapi/v1/marginType", market_type="perpetual", params={"symbol": symbol, "marginType": "ISOLATED"}, write=True)))
        except BinanceExecutionError as exc:
            if "-4046" not in str(exc):
                raise
        results.append(dict(self._request("POST", "/fapi/v1/leverage", market_type="perpetual", params={"symbol": symbol, "leverage": leverage}, write=True)))
        return results

    def start_user_stream(self, market_type: str) -> str:
        path = "/fapi/v1/listenKey" if market_type == "perpetual" else "/api/v3/userDataStream"
        payload = self._request("POST", path, market_type=market_type, signed=False)
        return str(payload["listenKey"])

    def keepalive_user_stream(self, market_type: str, listen_key: str) -> None:
        path = "/fapi/v1/listenKey" if market_type == "perpetual" else "/api/v3/userDataStream"
        self._request("PUT", path, market_type=market_type, params={"listenKey": listen_key}, signed=False)
