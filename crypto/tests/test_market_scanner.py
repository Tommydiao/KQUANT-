from __future__ import annotations

import httpx

from kquant_crypto.market_scanner import BinanceMarketScanner


def _instrument(symbol: str, base: str, *, status: str = "TRADING") -> dict:
    return {
        "symbol": symbol,
        "baseAsset": base,
        "quoteAsset": "USDT",
        "status": status,
        "isSpotTradingAllowed": True,
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
        ],
    }


def test_scanner_filters_and_ranks_liquid_spot_symbols(settings):
    scanner = BinanceMarketScanner(settings.db_path, minimum_quote_volume=1_000_000, deep_limit=1)
    exchange_info = {"symbols": [
        _instrument("BTCUSDT", "BTC"),
        _instrument("SOLUSDT", "SOL"),
        _instrument("USDCUSDT", "USDC"),
        _instrument("USD1USDT", "USD1"),
        _instrument("BTCUPUSDT", "BTCUP"),
        _instrument("OLDUSDT", "OLD", status="BREAK"),
    ]}
    tickers = [
        {"symbol": "BTCUSDT", "quoteVolume": "900000000", "priceChangePercent": "2"},
        {"symbol": "SOLUSDT", "quoteVolume": "300000000", "priceChangePercent": "8"},
        {"symbol": "USDCUSDT", "quoteVolume": "100000000", "priceChangePercent": "0"},
        {"symbol": "USD1USDT", "quoteVolume": "100000000", "priceChangePercent": "0"},
        {"symbol": "BTCUPUSDT", "quoteVolume": "100000000", "priceChangePercent": "20"},
    ]
    books = [
        {"symbol": "BTCUSDT", "bidPrice": "100", "askPrice": "100.01"},
        {"symbol": "SOLUSDT", "bidPrice": "100", "askPrice": "100.02"},
        {"symbol": "USDCUSDT", "bidPrice": "1", "askPrice": "1.0001"},
        {"symbol": "USD1USDT", "bidPrice": "1", "askPrice": "1.0001"},
        {"symbol": "BTCUPUSDT", "bidPrice": "10", "askPrice": "10.01"},
    ]

    candidates = scanner.build_candidates(exchange_info, tickers, books, source_time="2026-09-02T00:00:00+00:00")

    assert {item.symbol for item in candidates} == {"BTCUSDT", "SOLUSDT"}
    assert candidates[0].tier == "deep"
    assert next(item for item in candidates if item.symbol == "BTCUSDT").execution_allowlisted is True


def test_scanner_persists_one_scan_for_identical_market_state(settings):
    payloads = {
        "/api/v3/exchangeInfo": {"symbols": [_instrument("BTCUSDT", "BTC")]},
        "/api/v3/ticker/24hr": [{"symbol": "BTCUSDT", "quoteVolume": "900000000", "priceChangePercent": "2", "closeTime": 1788307200000}],
        "/api/v3/ticker/bookTicker": [{"symbol": "BTCUSDT", "bidPrice": "100", "askPrice": "100.01"}],
    }
    scanner = BinanceMarketScanner(settings.db_path, request_json=payloads.__getitem__)

    first = scanner.run_once()
    second = scanner.run_once()

    assert first["status"] == second["status"] == "available"
    assert first["scan_id"] == second["scan_id"]


def test_scanner_persists_restricted_location_as_fail_closed(settings):
    response = httpx.Response(451, request=httpx.Request("GET", "https://api.binance.com/api/v3/exchangeInfo"))

    def blocked(_path):
        raise httpx.HTTPStatusError("restricted", request=response.request, response=response)

    result = BinanceMarketScanner(settings.db_path, request_json=blocked).run_once()
    assert result["status"] == "unavailable"
    assert result["error"] == "restricted_location"
    assert result["watch_symbols"] == []
    from kquant_crypto.market_scanner import scanner_status
    stored = scanner_status(settings.db_path)["latest"]
    assert stored["status"] == "unavailable"
    assert stored["details"]["endpoint_family"] == "binance_public_market_data"


def test_scanner_uses_market_data_only_endpoint_by_default(settings):
    scanner = BinanceMarketScanner(settings.db_path)
    assert scanner.base_url == "https://data-api.binance.vision"
    assert scanner.endpoint_family == "binance_public_market_data"


def test_scanner_reports_endpoint_without_private_capability(settings):
    payloads = {
        "/api/v3/exchangeInfo": {"symbols": [_instrument("BTCUSDT", "BTC")]},
        "/api/v3/ticker/24hr": [{"symbol": "BTCUSDT", "quoteVolume": "900000000", "priceChangePercent": "2", "closeTime": 1788307200000}],
        "/api/v3/ticker/bookTicker": [{"symbol": "BTCUSDT", "bidPrice": "100", "askPrice": "100.01"}],
    }
    result = BinanceMarketScanner(settings.db_path, request_json=payloads.__getitem__).run_once()
    assert result["endpoint_family"] == "binance_public_market_data"
    assert result["market_data_only"] is True
