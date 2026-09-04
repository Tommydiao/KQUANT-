from __future__ import annotations

from dataclasses import dataclass


SPOT_MARKET_DATA_REST = "https://data-api.binance.vision"
SPOT_MARKET_DATA_STREAM = "wss://data-stream.binance.vision/stream"
FUTURES_MARKET_DATA_REST = "https://fapi.binance.com"
FUTURES_MARKET_DATA_STREAM = "wss://fstream.binance.com/stream"


@dataclass(frozen=True)
class BinancePublicEndpoints:
    spot_rest: str = SPOT_MARKET_DATA_REST
    spot_stream: str = SPOT_MARKET_DATA_STREAM
    futures_rest: str = FUTURES_MARKET_DATA_REST
    futures_stream: str = FUTURES_MARKET_DATA_STREAM

    def rest(self, market_type: str) -> str:
        return self.futures_rest if str(market_type).lower() == "perpetual" else self.spot_rest

    def stream(self, market_type: str) -> str:
        return self.futures_stream if str(market_type).lower() == "perpetual" else self.spot_stream

    def report(self) -> dict[str, object]:
        return {
            "endpoint_family": "binance_public_market_data",
            "market_data_only": True,
            "spot_rest": self.spot_rest,
            "spot_stream": self.spot_stream,
            "futures_rest": self.futures_rest,
            "futures_stream": self.futures_stream,
        }


__all__ = [
    "BinancePublicEndpoints",
    "SPOT_MARKET_DATA_REST",
    "SPOT_MARKET_DATA_STREAM",
    "FUTURES_MARKET_DATA_REST",
    "FUTURES_MARKET_DATA_STREAM",
]
