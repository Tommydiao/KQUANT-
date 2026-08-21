from __future__ import annotations

from pathlib import Path

from kquant.data_coverage import api_stock_data_coverage, persist_data_coverage_run
from kquant.market_data_backfill import create_backfill_job, run_backfill_job
from kquant.provider_event_retention import provider_event_retention_status
from kquant.stock_signals import persist_candles
from kquant.stock_store import connect
from kquant.universe_registry import ensure_current_universe_registry


def _seed_universe(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at) VALUES ('TEST', 'Test', 'Tech', 'Core', '[]', 1, 1, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()


def test_data_coverage_tracks_1m_gaps_and_persists_registry(tmp_path: Path) -> None:
    db_path = tmp_path / "trust.sqlite3"
    _seed_universe(db_path)
    payload = {
        "symbol": "TEST", "interval": "1m", "source_type": "longbridge_candles", "provider_status": "available",
        "adjustment_mode": "forward", "fetched_at": "2025-01-02T15:00:00+00:00",
        "candles": [
            {"open_time": "2025-01-02T14:00:00+00:00", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"open_time": "2025-01-02T14:04:00+00:00", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        ],
    }
    persist_candles(db_path, payload)
    coverage = api_stock_data_coverage(db_path)
    observed = coverage["symbols"][0]["intervals"]["1m"]
    assert coverage["universe_registry"]["symbol_count"] == 1
    assert observed["gap_count"] == 1
    saved = persist_data_coverage_run(db_path)
    assert saved["coverage_run_id"].startswith("dcr_")
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM data_coverage_items").fetchone()[0] == 3


def test_backfill_queue_retries_reference_fallback_without_counting_it_as_complete(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "queue.sqlite3"
    _seed_universe(db_path)
    job = create_backfill_job(db_path=db_path, symbols=["TEST"], pause_seconds=0, max_attempts=2)
    monkeypatch.setattr(
        "kquant.market_data_backfill.load_market_data_env",
        lambda: {"status": "test", "loaded_key_count": 0, "longbridge_credentials_configured": True},
    )
    monkeypatch.setattr(
        "kquant.market_data_backfill.api_stock_candles",
        lambda *args, **kwargs: {"source_type": "live_yahoo_chart", "provider_status": "available", "candles": [{}] * 999, "provider_errors": []},
    )
    first = run_backfill_job(db_path=db_path, job_id=job["job_id"], batch_size=2)
    assert first["item_counts"]["retry"] == 2
    second = run_backfill_job(db_path=db_path, job_id=job["job_id"], batch_size=2)
    assert second["job"]["status"] == "completed"
    assert second["item_counts"]["failed"] == 2


def test_backfill_queue_records_partial_longbridge_history_without_retrying(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "partial.sqlite3"
    _seed_universe(db_path)
    job = create_backfill_job(db_path=db_path, symbols=["TEST"], pause_seconds=0, max_attempts=2)
    monkeypatch.setattr(
        "kquant.market_data_backfill.load_market_data_env",
        lambda: {"status": "test", "loaded_key_count": 0, "longbridge_credentials_configured": True},
    )
    monkeypatch.setattr(
        "kquant.market_data_backfill.api_stock_candles",
        lambda *args, **kwargs: {
            "source_type": "longbridge_candles",
            "provider_status": "available",
            "candles": [{}] * 10,
            "provider_errors": [],
        },
    )

    report = run_backfill_job(db_path=db_path, job_id=job["job_id"], batch_size=2)

    assert report["job"]["status"] == "completed"
    assert report["item_counts"] == {"completed_limited": 2}


def test_provider_event_retention_is_report_only_by_default(tmp_path: Path) -> None:
    db_path = tmp_path / "retention.sqlite3"
    with connect(db_path) as conn:
        conn.execute("INSERT INTO provider_events(provider, instrument, symbol, status, message, created_at) VALUES ('longbridge', 'stock', 'TEST', 'ok', 'old', '2020-01-01T00:00:00+00:00')")
        conn.commit()
    report = provider_event_retention_status(db_path, retention_days=1)
    assert report["eligible_for_archive"] == 1
    assert report["automatic_deletion"] is False


def test_registry_is_content_addressed_and_repeatable(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    _seed_universe(db_path)
    assert ensure_current_universe_registry(db_path)["registry_id"] == ensure_current_universe_registry(db_path)["registry_id"]
