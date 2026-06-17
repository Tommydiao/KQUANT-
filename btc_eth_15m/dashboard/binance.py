from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode

import requests


TESTNET_BASE_URL = "https://demo-fapi.binance.com"
LIVE_BASE_URL = "https://fapi.binance.com"


@dataclass(frozen=True)
class BinanceCredentials:
    api_key: str
    api_secret: str

    @classmethod
    def from_env(cls, prefix: str) -> "BinanceCredentials | None":
        _load_local_dotenv()
        api_key = os.getenv(f"{prefix}_API_KEY")
        api_secret = os.getenv(f"{prefix}_API_SECRET")
        if not api_key or not api_secret:
            return None
        return cls(api_key=api_key, api_secret=api_secret)


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    min_qty: Decimal
    max_qty: Decimal
    step_size: Decimal
    min_notional: Decimal
    tick_size: Decimal

    @classmethod
    def from_exchange_info(cls, symbol_payload: dict) -> "SymbolRules":
        filters = {item["filterType"]: item for item in symbol_payload.get("filters", [])}
        lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
        min_notional = filters.get("MIN_NOTIONAL") or {}
        price = filters.get("PRICE_FILTER") or {}
        return cls(
            symbol=str(symbol_payload["symbol"]),
            min_qty=Decimal(str(lot.get("minQty", "0"))),
            max_qty=Decimal(str(lot.get("maxQty", "0"))),
            step_size=Decimal(str(lot.get("stepSize", "0"))),
            min_notional=Decimal(str(min_notional.get("notional", "0"))),
            tick_size=Decimal(str(price.get("tickSize", "0"))),
        )

    def round_quantity(self, quantity: Decimal) -> Decimal:
        if self.step_size <= 0:
            return quantity
        steps = (quantity / self.step_size).to_integral_value(rounding=ROUND_DOWN)
        return steps * self.step_size

    def validate_market_order(self, quantity: Decimal, price: Decimal) -> list[str]:
        reasons = []
        notional = quantity * price
        if quantity <= 0:
            reasons.append("Quantity must be positive after exchange step-size rounding.")
        if self.min_qty > 0 and quantity < self.min_qty:
            reasons.append(f"Quantity {quantity} is below minQty {self.min_qty}.")
        if self.max_qty > 0 and quantity > self.max_qty:
            reasons.append(f"Quantity {quantity} exceeds maxQty {self.max_qty}.")
        if self.min_notional > 0 and notional < self.min_notional:
            reasons.append(f"Notional {notional} is below minNotional {self.min_notional}.")
        return reasons

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "min_qty": str(self.min_qty),
            "max_qty": str(self.max_qty),
            "step_size": str(self.step_size),
            "min_notional": str(self.min_notional),
            "tick_size": str(self.tick_size),
        }


class BinanceFuturesClient:
    def __init__(self, base_url: str, credentials: BinanceCredentials | None = None, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.credentials = credentials
        self.timeout = timeout

    def get(self, path: str, params: dict | None = None) -> dict | list:
        return self._request("GET", path, params or {})

    def post(self, path: str, params: dict | None = None) -> dict | list:
        return self._request("POST", path, params or {})

    def public_get(self, path: str, params: dict | None = None) -> dict | list:
        response = requests.get(
            f"{self.base_url}{path}",
            params=params or {},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def server_time_delta_ms(self) -> int:
        local_before = int(time.time() * 1000)
        payload = self.public_get("/fapi/v1/time")
        local_after = int(time.time() * 1000)
        if not isinstance(payload, dict) or "serverTime" not in payload:
            raise ValueError("Server time response did not include serverTime.")
        local_midpoint = (local_before + local_after) // 2
        return int(payload["serverTime"]) - local_midpoint

    def start_user_data_stream(self) -> dict:
        return self._api_key_request("POST", "/fapi/v1/listenKey")

    def keepalive_user_data_stream(self) -> dict:
        return self._api_key_request("PUT", "/fapi/v1/listenKey")

    def close_user_data_stream(self) -> dict:
        return self._api_key_request("DELETE", "/fapi/v1/listenKey")

    def _request(self, method: str, path: str, params: dict) -> dict | list:
        if self.credentials is None:
            raise ValueError("Signed Binance request requires API credentials.")
        payload = dict(params)
        payload.setdefault("recvWindow", 5000)
        payload["timestamp"] = int(time.time() * 1000)
        query = urlencode(payload, doseq=True)
        signature = hmac.new(
            self.credentials.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_query = f"{query}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.credentials.api_key}
        url = f"{self.base_url}{path}"
        if method == "GET":
            response = requests.get(f"{url}?{signed_query}", headers=headers, timeout=self.timeout)
        elif method == "POST":
            response = requests.post(url, data=signed_query, headers=headers, timeout=self.timeout)
        else:
            raise ValueError(f"Unsupported Binance method: {method}")
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def _api_key_request(self, method: str, path: str) -> dict:
        if self.credentials is None:
            raise ValueError("Binance user stream request requires API credentials.")
        headers = {"X-MBX-APIKEY": self.credentials.api_key}
        url = f"{self.base_url}{path}"
        if method == "POST":
            response = requests.post(url, headers=headers, timeout=self.timeout)
        elif method == "PUT":
            response = requests.put(url, headers=headers, timeout=self.timeout)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers, timeout=self.timeout)
        else:
            raise ValueError(f"Unsupported Binance API-key method: {method}")
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()


def _load_local_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)
