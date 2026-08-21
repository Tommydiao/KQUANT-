from __future__ import annotations

import os

from kquant.market_data_backfill import run_longbridge_backfill
from kquant.stock_signals import normalize_range_interval
from kquant.stock_store import connect


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


def test_resumable_backfill_loads_only_market_data_env_and_disables_reference_fallback(tmp_path, monkeypatch) -> None:
    from kquant.market_data_backfill import create_backfill_job, run_backfill_job

    env_file = tmp_path / ".env"
    env_file.write_text(
        "LONGBRIDGE_APP_KEY=test-key\n"
        "LONGBRIDGE_APP_SECRET=test-secret\n"
        "LONGBRIDGE_ACCESS_TOKEN=test-token\n"
        "OPENAI_API_KEY=must-not-be-loaded\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KQUANT_ENV_FILE", str(env_file))
    managed_names = ("LONGBRIDGE_APP_KEY", "LONGBRIDGE_APP_SECRET", "LONGBRIDGE_ACCESS_TOKEN", "OPENAI_API_KEY")
    original = {name: os.environ.get(name) for name in managed_names}
    try:
        for name in managed_names:
            os.environ.pop(name, None)
        db_path = tmp_path / "kquant.sqlite3"
        with connect(db_path) as conn:
            conn.execute(
                "INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at) "
                "VALUES ('NVDA', 'NVIDIA', 'Technology', 'Core', '[]', 1, 1, '2026-01-01T00:00:00+00:00')"
            )
            conn.commit()
        job = create_backfill_job(db_path=db_path, symbols=["NVDA"], pause_seconds=0, max_attempts=1)

        def candles(symbol, range_value, interval, source, db_path, *, allow_reference_fallback=True):
            assert symbol == "NVDA"
            assert source == "live"
            assert allow_reference_fallback is False
            assert os.environ["LONGBRIDGE_APP_KEY"] == "test-key"
            assert "OPENAI_API_KEY" not in os.environ
            count = 900 if interval == "1d" else 220
            return {
                "provider_status": "available",
                "source_type": "longbridge_candles",
                "candles": [{}] * count,
                "provider_errors": [],
            }

        monkeypatch.setattr("kquant.market_data_backfill.api_stock_candles", candles)
        first = run_backfill_job(db_path=db_path, job_id=job["job_id"], batch_size=2)
        assert first["environment"]["longbridge_credentials_configured"] is True
        assert first["item_counts"] == {"completed": 2}
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


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
