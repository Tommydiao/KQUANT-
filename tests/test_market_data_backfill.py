from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from kquant.market_data_backfill import (
    backfill_quota_status,
    create_backfill_job,
    create_quota_recovery_job,
    run_longbridge_backfill,
)
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

    monkeypatch.setattr(
        "kquant.market_data_backfill.load_market_data_env",
        lambda: {"status": "test", "loaded_key_count": 0, "longbridge_credentials_configured": True},
    )

    def candles(symbol, range_value, interval, source, db_path, *, allow_reference_fallback=True):
        assert symbol == "NVDA"
        assert source == "live"
        assert allow_reference_fallback is False
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
        lambda symbol, range_value, interval, source, db_path, *, allow_reference_fallback=True: {
            "provider_status": "available",
            "source_type": "longbridge_candles",
            "candles": [{}] * (1000 if interval == "1d" else 300),
            "provider_errors": [],
        },
    )
    monkeypatch.setattr(
        "kquant.market_data_backfill.load_market_data_env",
        lambda: {"status": "test", "loaded_key_count": 0, "longbridge_credentials_configured": True},
    )
    monkeypatch.setattr("kquant.market_data_backfill.api_stock_data_coverage", lambda _: {})
    report = run_longbridge_backfill(
        db_path=tmp_path / "kquant.sqlite3",
        outputs_dir=tmp_path / "outputs",
        pause_seconds=0,
    )
    assert report["eligible_symbol_count"] == 1


def test_direct_backfill_fails_closed_without_longbridge_configuration(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kquant.market_data_backfill.api_stock_universe",
        lambda **_: {"universe": "all", "stocks": [{"symbol": "NVDA"}]},
    )
    monkeypatch.setattr(
        "kquant.market_data_backfill.load_market_data_env",
        lambda: {"status": "env_file_missing", "loaded_key_count": 0, "longbridge_credentials_configured": False},
    )
    monkeypatch.setattr(
        "kquant.market_data_backfill.api_stock_candles",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("reference fallback must not be requested")),
    )
    monkeypatch.setattr("kquant.market_data_backfill.api_stock_data_coverage", lambda _: {})

    report = run_longbridge_backfill(
        db_path=tmp_path / "kquant.sqlite3",
        outputs_dir=tmp_path / "outputs",
        pause_seconds=0,
    )

    assert report["eligible_symbol_count"] == 0
    assert report["environment"]["longbridge_credentials_configured"] is False
    assert {item["source"] for item in report["results"][0]["timeframes"]} == {"longbridge_credentials_missing"}


def test_backfill_quota_blocks_new_symbols_but_allows_resume_of_tracked_symbols(tmp_path) -> None:
    db_path = tmp_path / "kquant.sqlite3"
    with connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at) VALUES (?, ?, 'Technology', 'Core', '[]', 1, 1, '2026-01-01T00:00:00+00:00')",
            [("AAA", "AAA"), ("BBB", "BBB")],
        )
        conn.commit()

    first = create_backfill_job(db_path=db_path, symbols=["AAA"], pause_seconds=0, monthly_symbol_cap=1)
    assert first["quota_preflight"]["status"] == "ready"
    repeated = backfill_quota_status(db_path=db_path, requested_symbols=["AAA"], monthly_symbol_cap=1)
    assert repeated["allowed"] is True
    assert repeated["new_unique_symbols"] == 0
    blocked = backfill_quota_status(db_path=db_path, requested_symbols=["BBB"], monthly_symbol_cap=1)
    assert blocked["allowed"] is False
    assert blocked["status"] == "blocked_new_symbols_exceed_cap"
    with pytest.raises(ValueError, match="monthly new-symbol cap"):
        create_backfill_job(db_path=db_path, symbols=["BBB"], pause_seconds=0, monthly_symbol_cap=1)


def test_quota_recovery_clones_legacy_301607_items_only_after_a_new_month(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "kquant.sqlite3"
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at) "
            "VALUES ('AAA', 'AAA', 'Technology', 'Core', '[]', 1, 1, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
    source = create_backfill_job(db_path=db_path, symbols=["AAA"], pause_seconds=0, max_attempts=2)
    with connect(db_path) as conn:
        conn.execute("UPDATE market_backfill_jobs SET status='completed', requested_at=? WHERE job_id=?", ("2026-08-22T00:00:00+00:00", source["job_id"]))
        conn.execute(
            "UPDATE market_backfill_job_items SET status='completed' WHERE job_id=? AND interval='1d'",
            (source["job_id"],),
        )
        conn.execute(
            """
            UPDATE market_backfill_job_items
            SET status='failed', result_json='{"errors":["OpenApiException: code=301607 history candlestick symbol count out of limit"]}'
            WHERE job_id=? AND interval='1h'
            """,
            (source["job_id"],),
        )
        conn.commit()
    monkeypatch.setattr(
        "kquant.market_data_backfill.api_stock_candles",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("recovery must not request market data")),
    )

    august = datetime(2026, 8, 22, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="quota preflight is not ready"):
        create_quota_recovery_job(db_path=db_path, source_job_id=source["job_id"], now=august)

    september = datetime(2026, 9, 1, 0, tzinfo=UTC)
    recovery = create_quota_recovery_job(db_path=db_path, source_job_id=source["job_id"], now=september)

    assert recovery["resumed_from_job_id"] == source["job_id"]
    assert recovery["item_count"] == 1
    assert recovery["network_started"] is False
    assert recovery["manual_run_required"] is True
    with connect(db_path) as conn:
        source_status = conn.execute("SELECT status FROM market_backfill_jobs WHERE job_id=?", (source["job_id"],)).fetchone()["status"]
        item = conn.execute("SELECT status, attempts, interval FROM market_backfill_job_items WHERE job_id=?", (recovery["job_id"],)).fetchone()
    assert source_status == "completed"
    assert dict(item) == {"status": "queued", "attempts": 0, "interval": "1h"}
    quota_after_recovery = backfill_quota_status(db_path=db_path, now=september)
    assert quota_after_recovery["quota_recovery"]["manual_action_required"] is False
    assert quota_after_recovery["quota_recovery"]["candidate_item_count"] == 0
    with pytest.raises(ValueError, match="active quota-recovery job"):
        create_quota_recovery_job(db_path=db_path, source_job_id=source["job_id"], now=september)
