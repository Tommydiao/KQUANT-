from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from kquant.config import KquantConfig
from kquant.dashboard.app import FORBIDDEN_ROUTE_TOKENS, create_app, route_safety_report


def _app(tmp_path: Path):
    return create_app(
        config=KquantConfig(
            db_path=tmp_path / "kquant.sqlite3",
            outputs_dir=tmp_path / "outputs",
        )
    )


def test_stock_dashboard_has_no_executable_trade_routes(tmp_path: Path, monkeypatch) -> None:
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


def test_kquant_runtime_does_not_import_legacy_package() -> None:
    root = Path(__file__).resolve().parents[1]
    source = "\n".join(path.read_text(encoding="utf-8") for path in (root / "kquant").rglob("*.py"))
    assert "btc_eth_15m" not in source
    assert "TradeContext" not in source
