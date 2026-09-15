import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from kquant_crypto.candidate_api import create_candidate_router
from kquant_crypto.candidate_simulation_store import CandidateStore
from kquant_crypto.gateway import _resolve_backend_path


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(create_candidate_router(tmp_path))
    with TestClient(app) as value:
        yield value


def seed(tmp_path):
    path = tmp_path / "work" / "candidate_simulation.sqlite3"
    store = CandidateStore(path)
    store.create_run("run_1", {"command": "forward", "config": {"initial_cash": 10000}, "policy_hash": "abc",
                               "source_hashes": {"candidate_forward.py": "safehash"}})
    store.save("run_1", {"status": "running", "cash": 10005, "positions": {},
                        "last_bars": {"BTCUSDT": 1000},
                        "kernels": {"BTCUSDT": {"hour_bars": [{"start": 0}]}},
                        "decisions": {"BTCUSDT": {"mode": "RANGE", "reason_codes": ["RANGE_NOT_TRIGGERED"]}}},
               trades=[{"trade_id": "t1", "net_pnl": 5, "secret": "hidden", "note": "C:\\private\\file"}],
               equity=[{"time": 1300, "equity": 10005}])
    return path


@pytest.mark.parametrize("endpoint", ["status", "trades?run_id=run_1", "report?run_id=run_1"])
def test_missing_database_never_created(client, tmp_path, endpoint):
    response = client.get("/api/crypto/candidate-simulation/" + endpoint)
    assert response.status_code == 200
    assert response.json()["status"] == "not_started"
    assert not (tmp_path / "work").exists()
    assert response.headers["cache-control"] == "no-store"


def test_status_and_trades_are_read_only(client, tmp_path):
    path = seed(tmp_path)
    before = path.read_bytes()
    response = client.get("/api/crypto/candidate-simulation/status")
    assert response.status_code == 200, response.text
    status = response.json()
    assert status["status"] == "running", status
    assert status['status_basis'] == 'PERSISTED_LEDGER_NOT_PROCESS_HEALTH'
    assert status['process_liveness'] == 'UNVERIFIED'
    assert status['process_liveness_verified'] is False
    assert status["run_id"] == "run_1"
    assert status["state"]["net_pnl"] == 5
    assert status["state"]["last_hours"]["BTCUSDT"] == 3600
    assert status["metadata"]["source_hashes"]["candidate_forward.py"] == "safehash"
    assert "config" not in status["metadata"]
    response = client.get("/api/crypto/candidate-simulation/trades?run_id=run_1")
    assert response.json()["total"] == 1
    assert "hidden" not in response.text and "private" not in response.text
    assert response.json()["order_submission"] is False
    assert path.read_bytes() == before


def test_report_fixed_location_and_redaction(client, tmp_path):
    seed(tmp_path)
    route = "/api/crypto/candidate-simulation/report?run_id=run_1"
    assert client.get(route).json()["report_status"] == "not_available"
    folder = tmp_path / "outputs" / "dual_regime_v1" / "run_1"
    folder.mkdir(parents=True)
    report = folder / "metrics.json"
    report.write_text(json.dumps({"sample_count": 2, "by_mode": {"RANGE": {"profit_factor": 1.2}},
                                  "api_key": "hidden", "data_path": "/private/file", "note": "/private/file"}))
    result = client.get(route)
    assert result.json()["metrics"]["by_mode"]["RANGE"]["profit_factor"] == 1.2
    assert "private" not in result.text and "hidden" not in result.text
    report.write_text("{broken")
    assert client.get(route).status_code == 503
    report.write_text(json.dumps({"run_id": "other"}))
    assert client.get(route).status_code == 503
    report.write_text(json.dumps({"policy_hash": "wrong"}))
    assert client.get(route).status_code == 503


def test_latest_run_and_trade_limit(client, tmp_path):
    path = seed(tmp_path)
    store = CandidateStore(path)
    store.create_run("run_2", {"command": "forward"})
    store.save("run_2", {"status": "running"}, trades=[{"trade_id": str(i)} for i in range(205)])
    response = client.get("/api/crypto/candidate-simulation/status")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running", response.text
    assert response.json()["run_id"] == "run_2"
    result = client.get("/api/crypto/candidate-simulation/trades?run_id=run_2").json()
    assert result["total"] == 205 and len(result["items"]) == 200
    assert result["items"][0]["trade_id"] == "204"


def selection(tmp_path, store, *, run_id="base_A", cost=1, mode=None):
    store.create_run(run_id, {"command": "replay", "candidate": "A", "cost_multiplier": cost, "only_mode": mode})
    store.save(run_id, {"status": "completed"})
    folder = tmp_path / "outputs" / "dual_regime_v1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "candidate_selection.json").write_text(json.dumps({"selected": "A", "candidates": {"A": {"run_id": run_id}}}))


def test_forward_preferred_and_frozen_history_not_latest_replay(client, tmp_path):
    store = CandidateStore(seed(tmp_path))
    selection(tmp_path, store)
    for i in range(40):
        store.create_run(f"newer_replay_{i}", {"command": "replay", "cost_multiplier": 2, "only_mode": "RANGE"})
    payload = client.get("/api/crypto/candidate-simulation/status").json()
    assert payload["run_id"] == "run_1"
    assert payload["status_scope"] == "forward"
    assert payload["historical_report_run_id"] == "base_A"
    assert client.get("/api/crypto/candidate-simulation/trades?run_id=run_1").json()["total"] == 1


def test_history_available_without_forward(client, tmp_path):
    store = CandidateStore(tmp_path / "work" / "candidate_simulation.sqlite3")
    selection(tmp_path, store)
    payload = client.get("/api/crypto/candidate-simulation/status").json()
    assert payload["status"] == "not_started" and "run_id" not in payload
    assert payload["historical_report_run_id"] == "base_A"


@pytest.mark.parametrize("cost,mode", [(2, None), (1, "RANGE")])
def test_selection_rejects_stress_and_ablation(client, tmp_path, cost, mode):
    store = CandidateStore(seed(tmp_path))
    selection(tmp_path, store, cost=cost, mode=mode)
    assert client.get("/api/crypto/candidate-simulation/status").json()["historical_report_run_id"] is None


@pytest.mark.parametrize("connected,quote", [(True, 969), (False, 999), (True, None), (True, 1001)])
def test_paused_forward_unknown_valuation(client, tmp_path, monkeypatch, connected, quote):
    store = CandidateStore(seed(tmp_path))
    monkeypatch.setattr("kquant_crypto.candidate_api.time.time", lambda: 1000)
    state = store.load("run_1")
    state.update(status="paused", positions={"BTCUSDT": {"quantity": 1}}, day_paused=True,
                 forward={"connected": connected, "reason": "closed_data_stale", "last_quote": {"BTCUSDT": quote}})
    store.save("run_1", state)
    payload = client.get("/api/crypto/candidate-simulation/status").json()
    assert payload["status"] == "paused"
    state = payload["state"]
    assert state["day_paused"] is True
    assert state["forward"]["reason"] == "closed_data_stale"
    assert state["equity"] is None and state["net_pnl"] is None
    assert state["last_known_equity"] == 10005
    assert state["unable_to_value"] is True and state["stale_quote_symbols"] == ["BTCUSDT"]


def test_valuation_rechecks_server_time(client, tmp_path, monkeypatch):
    store = CandidateStore(seed(tmp_path))
    state = store.load("run_1")
    state.update(positions={"BTCUSDT": {"quantity": 1}},
                 forward={"connected": True, "last_quote": {"BTCUSDT": 1000}})
    store.save("run_1", state)
    monkeypatch.setattr("kquant_crypto.candidate_api.time.time", lambda: 1030)
    assert client.get("/api/crypto/candidate-simulation/status").json()["state"]["equity"] == 10005
    monkeypatch.setattr("kquant_crypto.candidate_api.time.time", lambda: 1031)
    assert client.get("/api/crypto/candidate-simulation/status").json()["state"]["equity"] is None


def test_empty_forward_cash_without_equity_sample(client, tmp_path):
    store = CandidateStore(tmp_path / "work" / "candidate_simulation.sqlite3")
    store.create_run("empty", {"command": "forward", "config": {"initial_cash": 10000}})
    store.save("empty", {"cash": 10000, "positions": {}, "forward": {"connected": False}})
    state = client.get("/api/crypto/candidate-simulation/status").json()["state"]
    assert state["equity"] == 10000 and state["net_pnl"] == 0 and not state["unable_to_value"]


@pytest.mark.parametrize("forward", [None, {"connected": True, "last_quote": None}])
def test_partial_forward_checkpoint_does_not_return_503(client, tmp_path, forward):
    store = CandidateStore(tmp_path / "work" / "candidate_simulation.sqlite3")
    store.create_run("partial", {"command": "forward", "policy": None, "config": None})
    store.save("partial", {"status": "paused", "forward": forward, "cash": 9000,
                           "positions": {"BTCUSDT": {"quantity": 1}}, "kernels": None})
    response = client.get("/api/crypto/candidate-simulation/status")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["run_id"] == "partial" and result["status"] == "paused"
    assert result["state"]["equity"] is None and result["state"]["unable_to_value"]
    assert result["state"]["last_hours"] == {}


def test_report_retains_numeric_fail_and_independent_unproven(client, tmp_path):
    store = CandidateStore(seed(tmp_path))
    selection(tmp_path, store)
    folder = tmp_path / "outputs" / "dual_regime_v1" / "base_A"
    folder.mkdir()
    (folder / "metrics.json").write_text(json.dumps({"gates": {"status": "TARGET_NOT_MET"},
        "independent_evidence_status": "PERFORMANCE_UNPROVEN", "source_hashes": {"module.py": "abc"},
        "config": {"password": "private"}, "source_path": "/private/source"}))
    response = client.get("/api/crypto/candidate-simulation/report?run_id=base_A")
    metrics = response.json()["metrics"]
    assert metrics["gates"]["status"] == "TARGET_NOT_MET"
    assert metrics["independent_evidence_status"] == "PERFORMANCE_UNPROVEN"
    assert metrics["source_hashes"]["module.py"] == "abc"
    assert "private" not in response.text


@pytest.mark.parametrize("run_id", ["../other", "C:\\private", "/etc/passwd", "' OR 1=1--", "a/b", "a" * 129])
def test_invalid_run_ids(client, run_id):
    response = client.get("/api/crypto/candidate-simulation/report", params={"run_id": run_id})
    assert response.status_code == 422


def test_unknown_run_and_corrupt_database(client, tmp_path):
    path = seed(tmp_path)
    assert client.get("/api/crypto/candidate-simulation/trades?run_id=absent").status_code == 404
    path.write_bytes(b"not sqlite")
    response = client.get("/api/crypto/candidate-simulation/status")
    assert response.status_code == 503
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize("endpoint", ["status", "trades", "report"])
def test_get_only(client, endpoint):
    route = f"candidate-simulation/{endpoint}"
    assert _resolve_backend_path("crypto", route, "GET") == "/api/crypto/" + route
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        assert _resolve_backend_path("crypto", route, method) is None
        assert client.request(method, "/api/crypto/" + route).status_code == 405
    assert _resolve_backend_path("crypto", route + "/extra", "GET") is None
    assert _resolve_backend_path("crypto", "candidate-simulation/stop", "GET") is None


def test_existing_dashboard_auth_is_inherited(settings):
    from kquant_crypto.dashboard.app import create_app

    with TestClient(create_app(settings)) as client:
        route = "/api/crypto/candidate-simulation/status"
        assert client.get(route).status_code == 401
        for endpoint in ("trades", "report"):
            assert client.get(f"/api/crypto/candidate-simulation/{endpoint}?run_id=run_1").status_code == 401
        response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery staple"})
        assert response.status_code == 200
        assert client.get(route).json()["status"] == "not_started"
    assert not (settings.root_dir / "work" / "candidate_simulation.sqlite3").exists()
