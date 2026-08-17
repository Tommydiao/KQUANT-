from __future__ import annotations

from kquant.market_data_backfill import run_longbridge_backfill
from kquant.stock_signals import normalize_range_interval


def test_two_year_hourly_backfill_range_is_not_silently_downgraded() -> None:
    assert normalize_range_interval("2y", "1h") == ("2y", "1h")
    assert normalize_range_interval("5y", "1d") == ("5y", "1d")


def test_backfill_never_counts_reference_fallback_as_eligible(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kquant.market_data_backfill.api_stock_universe",
        lambda **_: {"universe": "all", "stocks": [{"symbol": "NVDA"}]},
    )

    def candles(symbol, range_value, interval, source, db_path):
        assert symbol == "NVDA"
        assert source == "live"
        count = 1000 if interval == "1d" else 500
        return {
            "provider_status": "fallback",
            "source_type": "yahoo_public_fallback",
            "candles": [{}] * count,
            "provider_errors": ["Longbridge unavailable"],
        }

    monkeypatch.setattr("kquant.market_data_backfill.api_stock_candles", candles)
    monkeypatch.setattr(
        "kquant.market_data_backfill.api_stock_data_coverage",
        lambda _: {"canonical_validation_eligible_symbols": 0},
    )
    report = run_longbridge_backfill(
        db_path=tmp_path / "kquant.sqlite3",
        outputs_dir=tmp_path / "outputs",
        pause_seconds=0,
    )
    assert report["requested_symbol_count"] == 1
    assert report["eligible_symbol_count"] == 0
    assert report["reference_fallback_counts_as_eligible"] is False


def test_backfill_counts_only_sufficient_longbridge_ranges(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kquant.market_data_backfill.api_stock_universe",
        lambda **_: {"universe": "all", "stocks": [{"symbol": "NVDA"}]},
    )
    monkeypatch.setattr(
        "kquant.market_data_backfill.api_stock_candles",
        lambda symbol, range_value, interval, source, db_path: {
            "provider_status": "available",
            "source_type": "longbridge_candles",
            "candles": [{}] * (1000 if interval == "1d" else 300),
            "provider_errors": [],
        },
    )
    monkeypatch.setattr("kquant.market_data_backfill.api_stock_data_coverage", lambda _: {})
    report = run_longbridge_backfill(
        db_path=tmp_path / "kquant.sqlite3",
        outputs_dir=tmp_path / "outputs",
        pause_seconds=0,
    )
    assert report["eligible_symbol_count"] == 1
