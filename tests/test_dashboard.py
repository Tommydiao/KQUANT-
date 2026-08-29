from __future__ import annotations

from pathlib import Path
import re

from fastapi.testclient import TestClient

from kquant.config import KquantConfig
from kquant.data_snapshots import create_market_data_snapshot
from kquant.dashboard.app import API_CONTRACT_VERSION, FORBIDDEN_ROUTE_TOKENS, create_app, route_safety_report
from kquant.db import LATEST_SCHEMA_VERSION
from kquant.stock_store import connect


def _app(tmp_path: Path):
    return create_app(
        config=KquantConfig(
            db_path=tmp_path / "kquant.sqlite3",
            outputs_dir=tmp_path / "outputs",
        )
    )


def test_stock_dashboard_has_no_executable_trade_routes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KQUANT_BUILD_SHA", "local")
    monkeypatch.setattr(
        "kquant.dashboard.app.api_stock_market_data_status",
        lambda db_path=None: {"provider": "yahoo", "status": "standby"},
    )
    monkeypatch.setattr(
        "kquant.dashboard.app.api_stock_ai_review_status",
        lambda: {"status": "missing_key", "models": {}},
    )
    app = _app(tmp_path)
    report = route_safety_report(app)
    assert report["status"] == "pass"
    assert report["forbidden_routes"] == []
    for route in app.routes:
        path = getattr(route, "path", "").lower()
        assert not any(token in path for token in FORBIDDEN_ROUTE_TOKENS)
    health = TestClient(app).get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "online"
    assert health.json()["safety"]["order_submission_enabled"] is False
    assert health.json()["runtime"]["api_contract_version"] == "kquant-api-2026-08-22-v2-oos-shadow-v4"
    assert health.json()["runtime"]["auth_routes_version"] == "local_email_password_v1"
    assert health.json()["runtime"]["database_schema_version"] == LATEST_SCHEMA_VERSION
    assert health.json()["database_migration"]["status"] == "up_to_date"
    assert health.json()["database_migration"]["checksum_verified"] is True
    assert health.json()["safety"]["options_research_enabled"] is True
    assert health.json()["safety"]["options_order_submission_enabled"] is False
    assert health.json()["runtime"]["build_sha"] == "local"
    assert health.json()["runtime"]["environment"] == "development"
    version = TestClient(app).get("/api/version")
    assert version.status_code == 200
    assert version.json()["api"] == API_CONTRACT_VERSION
    assert version.json()["strategy"] == "swing_long_v1.1.0"
    assert version.json()["build_sha"] == "local"
    assert version.json()["order_submission"] is False


def test_removed_legacy_paths_are_not_registered(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    for path in (
        "/api/orders",
        "/api/positions",
        "/api/broker/options/status",
        "/api/options/paper-orders",
        "/api/mstr/cycle-radar",
        "/api/exchange/sync",
    ):
        assert client.get(path).status_code == 404


def test_realtime_instruction_and_option_research_routes_are_registered(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("kquant.dashboard.app.option_market_status", lambda: {"provider": "longbridge", "status": "missing_config"})
    client = TestClient(_app(tmp_path))
    assert client.get("/api/instructions/current").status_code == 200
    assert client.get("/api/alerts").status_code == 200
    assert client.get("/api/runtime/supervisor-status").json()["order_submission_enabled"] is False
    assert client.get("/api/options/status").json()["provider"] == "longbridge"


def test_data_snapshot_route_returns_an_immutable_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "kquant.sqlite3"
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO market_candles(
              symbol, interval, open_time, adjustment_mode, dataset_version,
              primary_source, provider_symbol, provider_status, freshness_seconds,
              bar_state, open, high, low, close, volume, fetched_at, first_seen_at, updated_at
            ) VALUES ('NVDA', '1d', '2026-01-02T14:30:00+00:00', 'unadjusted', 'test',
              'longbridge_candles', 'US.NVDA', 'available', 0, 'closed_candle', 100, 101, 99, 100, 1000,
              '2026-01-02T21:00:00+00:00', '2026-01-02T21:00:00+00:00', '2026-01-02T21:00:00+00:00')
            """
        )
        conn.commit()
    snapshot = create_market_data_snapshot(
        db_path, symbol="NVDA", intervals=["1d"], as_of_time="2026-01-03T00:00:00+00:00"
    )

    response = TestClient(_app(tmp_path)).get(f"/api/data/snapshots/{snapshot['snapshot_id']}")

    assert response.status_code == 200
    assert response.json()["content_hash"] == snapshot["content_hash"]


def test_data_coverage_route_includes_read_only_backfill_quota_status(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    payload = client.get("/api/data/coverage?detail=summary").json()

    assert payload["detail"] == "summary"
    assert payload["symbol_details_included"] is False
    assert payload["symbols"] == []
    assert payload["backfill_quota"]["read_only_market_data"] is True
    assert payload["backfill_quota"]["provider_remaining_quota_known"] is False
    assert payload["backfill_quota"]["quota_recovery"]["manual_action_required"] is False
    assert payload["historical_validation"]["status"] == "not_materialized"
    assert payload["historical_validation"]["eligible_symbols"] is None

    full = client.get("/api/data/coverage")
    assert full.status_code == 200
    assert full.json()["detail"] == "full"
    assert full.json()["symbol_details_included"] is True
    assert client.get("/api/data/coverage?detail=unexpected").status_code == 400


def test_frontend_cache_contract_keeps_html_fresh_and_hash_assets_immutable(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    index = client.get("/")

    assert index.status_code == 200
    assert index.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert client.get("/service-worker.js").headers["cache-control"] == "no-cache, no-store, must-revalidate"
    script = re.search(r'<script[^>]+src="(?P<path>/assets/[^"]+\.js)"', index.text)
    assert script is not None
    asset = client.get(script.group("path"))
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_theme_taxonomy_routes_are_read_only_and_explicit_when_not_materialized(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    response = client.get("/api/themes")
    assert response.status_code == 200
    assert response.json()["status"] == "not_materialized"
    ranking = client.get("/api/themes/ranking")
    assert ranking.status_code == 200
    assert ranking.json()["status"] == "not_materialized"
    assert client.get("/api/themes/theme.unknown").status_code == 404


def test_theme_taxonomy_audit_route_is_read_only(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    response = client.get("/api/themes/audit")
    assert response.status_code == 200
    assert response.json()["status"] == "not_materialized"
    assert response.json()["read_only_research"] is True


def test_quant_model_routes_are_read_only_and_empty_before_artifacts(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    assert client.get("/api/models/validation-runs").json() == {"artifacts": [], "read_only_research": True}
    assert client.get("/api/models/qma_unknown/metrics").status_code == 404
    readiness = client.get("/api/quant/stocks/validation-readiness")
    assert readiness.status_code == 200
    assert readiness.json()["status"] == "not_materialized"
    assert readiness.json()["read_only_research"] is True


def test_theme_prediction_route_is_read_only_and_empty_before_run(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    payload = client.get("/api/models/theme-prediction/latest")
    assert payload.status_code == 200
    assert payload.json() == {"status": "not_materialized", "runs": [], "read_only_research": True}
    assert client.get("/api/models/theme-prediction/tpr_unknown").status_code == 404


def test_leadership_routes_are_read_only_and_empty_before_run(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    assert client.get("/api/leadership/latest").json() == {"status": "not_materialized", "leaders": [], "summary": {}, "read_only_research": True}
    assert client.get("/api/themes/theme.unknown/leaders").status_code == 404


def test_fixture_source_is_blocked_at_http_boundary(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    response = client.get("/api/stocks/candles?symbol=NVDA&range=1y&interval=1d&source=fixture")
    assert response.status_code == 400


def test_self_check_includes_route_and_secret_safety(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kquant.dashboard.app.api_stock_market_data_self_check",
        lambda symbol, db_path: {"status": "caution", "symbol": symbol, "checks": []},
    )
    payload = TestClient(_app(tmp_path)).get("/api/stocks/market-data/self-check?symbol=NVDA").json()
    assert payload["route_safety"]["status"] == "pass"
    assert payload["credential_values_exposed"] is False
    assert payload["ai_key"] in {"configured", "missing"}


def test_manual_workflow_routes_remain_research_only(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    sizing = client.post(
        "/api/stocks/manual-position-plan",
        json={
            "account_value": 10_000,
            "risk_per_trade_pct": 1,
            "entry_price": 100,
            "stop_price": 95,
            "max_total_risk_pct": 2,
        },
    )
    assert sizing.status_code == 200
    assert sizing.json()["no_order_submission"] is True
    ledger = client.post(
        "/api/stocks/decision-ledger",
        json={"signal_id": "signal-1", "symbol": "NVDA", "user_decision": "observe"},
    )
    assert ledger.status_code == 200
    assert ledger.json()["read_only_research"] is True
    assert client.get("/api/stocks/weekly-review").status_code == 200
    assert client.get("/api/stocks/operations/health").status_code == 200
    assert client.get("/api/stocks/database/migration-readiness").json()["runtime_supported"] is True
    notification = client.post("/api/stocks/notifications", json={"event_type": "data_anomaly", "payload": {"symbol": "NVDA"}})
    assert notification.status_code == 200
    assert notification.json()["secret_values_stored"] is False


def test_today_and_production_routes_fail_safe_without_forward_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kquant.dashboard.app.api_stock_signals_latest",
        lambda **_: {
            "run_id": "run-1", "provider_status": "available", "provider_error_count": 0,
            "daily_candidates": {"buy_setups": [{"symbol": "NVDA", "rank": 1}], "watch": []},
            "market_regime": {"regime": "RISK_ON", "label": "Risk On", "score": 80},
            "strategy_version": "swing_long_v1.1.0",
        },
    )
    monkeypatch.setattr("kquant.dashboard.app.api_stock_market_data_status", lambda *_: {"status": "available"})
    monkeypatch.setattr("kquant.dashboard.app.api_stock_ai_review_status", lambda: {"status": "available"})
    monkeypatch.setattr("kquant.dashboard.app.api_strategy_validation_latest", lambda *_: {"evidence": {"historical_policy_replay": {"summary": {}}}})
    client = TestClient(_app(tmp_path))
    today = client.get("/api/stocks/today-workbench").json()
    assert today["decision"] == "NO_TRADE"
    live = client.post(
        "/api/stocks/manual-live-readiness",
        json={"instrument_type": "common_stock", "risk_per_trade_pct": 0.25, "manual_trades_today": 0, "data_clean": True, "hard_veto_active": False},
    ).json()
    assert live["status"] == "blocked"
    assert live["broker_execution_present"] is False


def test_kquant_runtime_does_not_import_legacy_package() -> None:
    root = Path(__file__).resolve().parents[1]
    source = "\n".join(path.read_text(encoding="utf-8") for path in (root / "kquant").rglob("*.py"))
    assert "btc_eth_15m" not in source
    assert "TradeContext" not in source


def test_runtime_contract_is_aligned_across_server_client_and_startup_script() -> None:
    root = Path(__file__).resolve().parents[1]
    frontend = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    startup = (root / "start_kquant_stock_terminal.ps1").read_text(encoding="utf-8")

    assert f'FRONTEND_API_CONTRACT_VERSION = "{API_CONTRACT_VERSION}"' in frontend
    assert f'$ExpectedApiContract = "{API_CONTRACT_VERSION}"' in startup
