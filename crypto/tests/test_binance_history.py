from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.error import HTTPError

from kquant_crypto.binance_history import (
    BinanceKlineBackfill,
    BinancePublicKlineClient,
    kline_event,
)
from kquant_crypto.parquet_store import ParquetMarketStore


FETCHED_AT = datetime(2026, 8, 23, 0, 0, tzinfo=UTC)


def _row(open_time: int, close: str = "101") -> list[object]:
    return [open_time, "100", "102", "99", close, "10", open_time + 59_999, "1000", 10, "5", "500", "0"]


def test_kline_event_preserves_closed_bar_provenance():
    event = kline_event("BTCUSDT", _row(1_000), interval="1m", fetched_at=FETCHED_AT)
    assert event is not None
    assert event.asset_id == "cex:binance:spot:BTCUSDT"
    assert event.instrument_id == "binance:spot:BTCUSDT"
    assert event.provider_status == "historical"
    assert event.payload["source"] == "binance_public_rest_klines"
    assert event.payload["closed"] is True
    future_open = int(FETCHED_AT.timestamp() * 1000) + 60_000
    assert kline_event("BTCUSDT", _row(future_open), interval="1m", fetched_at=FETCHED_AT) is None


def test_backfill_paginates_and_resumes_without_restarting_cursor(tmp_path):
    calls: list[tuple[int, int]] = []

    def request(url: str, _timeout: float):
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(url).query)
        start = int(query["startTime"][0])
        calls.append((start, int(query["endTime"][0])))
        if start == 0:
            return [_row(0), _row(60_000)]
        if start == 120_000:
            return [_row(120_000)]
        return []

    client = BinancePublicKlineClient(request_json=request, sleep=lambda _seconds: None)
    store = ParquetMarketStore(tmp_path / "data")
    state = tmp_path / "state.json"
    backfill = BinanceKlineBackfill(store, client, state_path=state, now=lambda: FETCHED_AT)

    first = backfill.run(["BTCUSDT"], start_at=0, end_at=179_999, limit=2, max_pages=1)
    assert first[0].status == "paused"
    assert first[0].rows_written == 2
    second = backfill.run(["BTCUSDT"], start_at=0, end_at=179_999)
    assert second[0].status == "complete"
    assert second[0].rows_written == 1
    assert [item[0] for item in calls] == [0, 120_000]
    assert len(store.query(venue="binance", market_type="spot", symbol="BTCUSDT", limit=10)) == 3
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["jobs"]["BTCUSDT:1m"]["status"] == "complete"


def test_public_client_retries_rate_limit():
    attempts = 0

    def request(_url: str, _timeout: float):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError("https://binance.test", 429, "rate", {"Retry-After": "0"}, None)
        return [_row(0)]

    client = BinancePublicKlineClient(request_json=request, sleep=lambda _seconds: None)
    assert client.fetch_klines("BTCUSDT", "1m", start_time_ms=0, end_time_ms=60_000) == [_row(0)]
    assert attempts == 2
