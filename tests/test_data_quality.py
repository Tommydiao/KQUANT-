from __future__ import annotations

from datetime import UTC, datetime

from kquant.data_quality import assess_candle_payload, assess_realtime_market_data, normalize_source_status


def _payload(*, source: str = "longbridge_candles", status: str = "available") -> dict:
    return {
        "symbol": "NVDA",
        "interval": "1d",
        "source_type": source,
        "provider_status": status,
        "adjustment_mode": "unadjusted",
        "dataset_version": "market_data_contract_v1",
        "candles": [
            {
                "open_time": "2026-07-22T13:30:00+00:00",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1_000_000,
                "bar_state": "closed_candle",
            }
        ],
    }


def test_data_quality_allows_clean_primary_closed_candles() -> None:
    quality = assess_candle_payload(_payload(), now=datetime(2026, 7, 23, tzinfo=UTC))

    assert quality["status"] == "clean"
    assert quality["buy_data_eligible"] is True


def test_data_quality_blocks_yahoo_and_invalid_ohlcv() -> None:
    yahoo = assess_candle_payload(_payload(source="yahoo_public_fallback", status="fallback"))
    fixture = assess_candle_payload(_payload(source="fixture_read_only", status="fixture_read_only"))
    broken_payload = _payload()
    broken_payload["candles"][0]["low"] = 103.0
    broken = assess_candle_payload(broken_payload)

    assert yahoo["status"] == "blocked"
    assert "yahoo_reference_only" in yahoo["hard_veto_reasons"]
    assert "fixture_data" in fixture["hard_veto_reasons"]
    assert broken["status"] == "blocked"
    assert "invalid_ohlcv" in broken["hard_veto_reasons"]


def test_realtime_quality_requires_regular_session_fresh_quote_and_depth() -> None:
    candle_quality = assess_candle_payload(_payload(), now=datetime(2026, 7, 23, tzinfo=UTC))
    quote = {"provider_status": "available", "freshness_seconds": 4, "depth_status": "available"}
    clean = assess_realtime_market_data(
        candle_quality=candle_quality, quote=quote, session="regular", trust="live_quote"
    )
    blocked = assess_realtime_market_data(
        candle_quality=candle_quality, quote={**quote, "depth_status": "unavailable"}, session="regular", trust="live_quote"
    )

    assert clean["buy_data_eligible"] is True
    assert blocked["buy_data_eligible"] is False
    assert "depth_unavailable" in blocked["hard_veto_reasons"]


def test_public_source_status_contract_distinguishes_primary_reference_and_unavailable() -> None:
    assert normalize_source_status(source="longbridge_candles", provider_status="available") == "live_primary"
    assert normalize_source_status(source="stale_longbridge_cache", provider_status="stale_cache") == "stale_primary"
    assert normalize_source_status(source="live_yahoo_chart", provider_status="available") == "reference_only"
    assert normalize_source_status(source="longbridge_candles", provider_status="unavailable") == "unavailable"
