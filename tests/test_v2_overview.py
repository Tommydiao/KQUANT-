from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from kquant.config import KquantConfig
from kquant.dashboard.app import create_app


def test_v2_overview_is_read_only_and_preserves_evidence_chain(tmp_path: Path) -> None:
    app = create_app(config=KquantConfig(db_path=tmp_path / "kquant.sqlite3", outputs_dir=tmp_path / "outputs"))
    client = TestClient(app)

    response = client.get("/api/quant/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "kquant_v2_overview_v1.1.0"
    assert payload["read_only_research"] is True
    assert payload["automatic_execution_allowed"] is False
    assert payload["order_submission_enabled"] is False
    assert [item["status"] for item in payload["evidence_chain"]] == [
        "not_available",
        "not_available",
        "not_available",
        "not_available",
    ]
    assert payload["shadow_observation"]["go_no_go"] == "NO_GO"
    assert payload["shadow_observation"]["start_allowed"] is False
    assert payload["shadow_observation"]["next_action"]
    assert payload["stock_quant"]["validation_readiness"]["status"] == "not_materialized"

    shadow = client.get("/api/shadow-observation/status")
    assert shadow.status_code == 200
    assert shadow.json()["status"] == "not_started"
    assert shadow.json()["target_trading_days"] == 20
    assert shadow.json()["real_money_allowed"] is False
