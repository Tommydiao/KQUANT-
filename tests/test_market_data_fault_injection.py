from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from kquant import stock_signals
from kquant.data_quality import assess_candle_payload


def _available_yahoo_payload(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "interval": "1m",
        "source_type": "live_yahoo_chart",
        "provider": "yahoo_public",
        "provider_status": "available",
        "adjustment_mode": "provider_default_unknown",
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


def test_provider_timeout_becomes_blocked_data(monkeypatch) -> None:
    def timeout(*args, **kwargs):
        raise requests.Timeout("simulated provider timeout")

    monkeypatch.setattr(stock_signals.requests, "get", timeout)
    payload = stock_signals.yahoo_candles("NVDA", "1d", "1m")
    quality = assess_candle_payload(payload)

    assert payload["provider_status"] == "unavailable"
    assert quality["status"] == "blocked"
    assert "provider_unavailable" in quality["hard_veto_reasons"]


def test_longbridge_failure_yahoo_fallback_is_visible_but_blocked(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(stock_signals, "preferred_market_data_provider", lambda: "longbridge")
    monkeypatch.setattr(
        stock_signals,
        "longbridge_candles",
        lambda symbol, range_value, interval: {
            "symbol": symbol,
            "interval": interval,
            "source_type": "longbridge_candles",
            "provider_status": "unavailable",
            "provider_errors": ["simulated Longbridge timeout"],
            "candles": [],
        },
    )
    monkeypatch.setattr(stock_signals, "yahoo_candles", lambda symbol, range_value, interval: _available_yahoo_payload(symbol))

    payload = stock_signals.api_stock_candles("NVDA", "1d", "1m", "live", tmp_path / "kquant.sqlite3")

    assert payload["source_type"] == stock_signals.YAHOO_FALLBACK_SOURCE
    assert payload["data_quality"]["buy_data_eligible"] is False
    assert "yahoo_reference_only" in payload["data_quality"]["hard_veto_reasons"]


def test_future_candle_is_rejected_by_data_quality() -> None:
    payload = _available_yahoo_payload("NVDA")
    future = datetime.now(UTC) + timedelta(hours=1)
    payload["candles"][0]["open_time"] = future.isoformat()

    quality = assess_candle_payload(payload)

    assert quality["status"] == "blocked"
    assert "invalid_candle_timestamps" in quality["hard_veto_reasons"]


def test_cache_write_failure_preserves_response_and_blocks_fixture(monkeypatch, tmp_path: Path) -> None:
    def fail_write(*args, **kwargs):
        raise sqlite3.OperationalError("simulated database is read-only")

    monkeypatch.setattr(stock_signals, "persist_candles", fail_write)
    payload = stock_signals.api_stock_candles("NVDA", "1y", "1d", "fixture", tmp_path / "kquant.sqlite3")

    assert payload["data_quality"]["status"] == "blocked"
    assert "fixture_data" in payload["data_quality"]["hard_veto_reasons"]
    assert payload.get("cache_write_status") != "ok"
