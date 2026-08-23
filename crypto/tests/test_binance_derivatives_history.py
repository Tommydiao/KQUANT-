from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from kquant_crypto.binance_derivatives_history import (
    BinanceDerivativeBackfill,
    BinancePublicDerivativeClient,
    funding_event,
    open_interest_event,
)
from kquant_crypto.parquet_store import ParquetMarketStore


FETCHED_AT = datetime(2026, 8, 23, 0, 0, tzinfo=UTC)


def test_derivative_events_are_public_historical_and_auditable():
    funding = funding_event("BTCUSDT", {"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingTime": 1_000, "markPrice": "100"}, fetched_at=FETCHED_AT)
    oi = open_interest_event("BTCUSDT", {"symbol": "BTCUSDT", "sumOpenInterest": "42", "sumOpenInterestValue": "4200", "timestamp": 2_000}, period="1h", fetched_at=FETCHED_AT)
    assert funding is not None and oi is not None
    assert funding.instrument_id == "binance:perpetual:BTCUSDT"
    assert funding.event_type == "funding_rate"
    assert funding.payload["available_at"] == funding.source_time
    assert funding.payload["retrieved_at"] == FETCHED_AT.isoformat()
    assert funding.payload["provenance"] == "historical_rest_replay"
    assert oi.event_type == "open_interest"
    assert oi.payload["open_interest"] == 42.0
    assert funding_event("BTCUSDT", {"fundingRate": "0.1", "fundingTime": int(FETCHED_AT.timestamp() * 1000) + 1}, fetched_at=FETCHED_AT) is None


def test_public_derivative_client_uses_endpoint_parameters_and_retries():
    urls: list[str] = []
    attempts = 0

    def request(url: str, _timeout: float):
        nonlocal attempts
        attempts += 1
        urls.append(url)
        if attempts == 1:
            raise HTTPError(url, 429, "rate", {"Retry-After": "0"}, None)
        if "fundingRate" in url:
            return [{"fundingTime": 1, "fundingRate": "0.1"}]
        return [{"timestamp": 2, "sumOpenInterest": "3"}]

    client = BinancePublicDerivativeClient(request_json=request, sleep=lambda _seconds: None)
    assert client.fetch_funding_rates("BTCUSDT", start_time_ms=0, end_time_ms=10, limit=10)[0]["fundingTime"] == 1
    assert client.fetch_open_interest("BTCUSDT", period="1h", start_time_ms=0, end_time_ms=10, limit=10)[0]["timestamp"] == 2
    assert attempts == 3
    assert parse_qs(urlparse(urls[-1]).query)["period"] == ["1h"]


def test_derivative_backfill_persists_and_resumes(tmp_path):
    calls: list[tuple[str, int]] = []

    def request(url: str, _timeout: float):
        query = parse_qs(urlparse(url).query)
        endpoint = "funding" if "fundingRate" in url else "open_interest"
        start = int(query["startTime"][0])
        calls.append((endpoint, start))
        if endpoint == "funding":
            if start == 0:
                return [{"fundingTime": 0, "fundingRate": "0.1"}, {"fundingTime": 1_000, "fundingRate": "0.2"}]
            if start == 1_001:
                return [{"fundingTime": 2_000, "fundingRate": "0.3"}]
        else:
            if start == 0:
                return [{"timestamp": 0, "sumOpenInterest": "10"}, {"timestamp": 3_600_000, "sumOpenInterest": "11"}]
        return []

    client = BinancePublicDerivativeClient(request_json=request, sleep=lambda _seconds: None)
    store = ParquetMarketStore(tmp_path / "data")
    state = tmp_path / "state.json"
    backfill = BinanceDerivativeBackfill(store, client, state_path=state, now=lambda: FETCHED_AT)
    first = backfill.run(["BTCUSDT"], start_at=0, end_at=2_000, period="1h", limit=2, max_pages=1)
    assert first[0].funding_status == "paused"
    second = backfill.run(["BTCUSDT"], start_at=0, end_at=2_000, period="1h", limit=2)
    assert second[0].funding_status == "complete"
    assert second[0].funding_rows == 1
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["jobs"]["funding:BTCUSDT:1h"]["status"] == "complete"
    assert len(store.query(venue="binance", market_type="perpetual", limit=20)) == 4
    assert ("funding", 1_001) in calls


def test_open_interest_tail_page_backfills_missing_prefix(tmp_path):
    calls: list[tuple[int, int]] = []
    step = 3_600_000

    def request(url: str, _timeout: float):
        query = parse_qs(urlparse(url).query)
        if "openInterestHist" not in url:
            return []
        start = int(query["startTime"][0])
        end = int(query["endTime"][0])
        calls.append((start, end))
        if end == 5 * step:
            return [
                {"timestamp": 2 * step, "sumOpenInterest": "12"},
                {"timestamp": 3 * step, "sumOpenInterest": "13"},
                {"timestamp": 4 * step, "sumOpenInterest": "14"},
                {"timestamp": 5 * step, "sumOpenInterest": "15"},
            ]
        return [
            {"timestamp": 0, "sumOpenInterest": "10"},
            {"timestamp": step, "sumOpenInterest": "11"},
        ]

    client = BinancePublicDerivativeClient(request_json=request, sleep=lambda _seconds: None)
    store = ParquetMarketStore(tmp_path / "data")
    backfill = BinanceDerivativeBackfill(store, client, now=lambda: FETCHED_AT)
    report = backfill.run(["BTCUSDT"], start_at=0, end_at=5 * step, period="1h", limit=4)

    assert report[0].open_interest_status == "complete"
    assert report[0].open_interest_rows == 6
    assert calls == [(0, 5 * step), (0, step)]
    rows = store.query(venue="binance", market_type="perpetual", limit=20)
    assert sorted(row["event_type"] for row in rows) == ["open_interest"] * 6
