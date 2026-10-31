"""Real gateway authentication and backend manual handlers, isolated SQLite only."""
from datetime import timedelta
from pathlib import Path
import sys
import time

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "crypto"))
from kquant_crypto.gateway import create_gateway_app
from kquant.security import generate_password_hash as hash_password

from kquant.config import KquantConfig
from kquant.dashboard.app import create_app
from kquant import options_one_minute as common
from kquant import options_one_minute_manual as manual
from kquant import options_opening_trend_store as store
from test_r58_positive_chain import prepare


def test_login_partial_exit_expired_session_and_persistent_recovery(tmp_path, monkeypatch):
    args, evaluation, _, _ = prepare(tmp_path, monkeypatch)
    ledger, research = tmp_path / "manual.sqlite3", tmp_path / "research.sqlite3"
    common.initialize(ledger)
    store.initialize(research)
    store.persist([evaluation], research)
    original_status = manual.manual_status
    monkeypatch.setenv("KQUANT_REQUIRE_API_AUTH", "true")
    monkeypatch.setenv("KQUANT_API_AUTH_TOKEN", "test-only-internal-token")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-config"))
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_ENABLED", "true")
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_EMAIL", "test-only@example.invalid")
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH", hash_password("TEST_ONLY_not_a_user_password"))
    monkeypatch.setenv("KQUANT_WORKSPACE_SESSION_SECRET", "TEST_ONLY_SECRET" * 4)
    monkeypatch.delenv("KQUANT_OPTION_FOUNDATION_ROOT", raising=False)
    backend = TestClient(create_app(config=KquantConfig(db_path=tmp_path / "business.sqlite3", outputs_dir=tmp_path / "outputs"),
        research_store=research, manual_store=ledger, research_clock=lambda: args["now"] + timedelta(minutes=1)))
    calls = []

    def handler(request):
        calls.append(request.url.path)
        response = backend.request(request.method, request.url.raw_path.decode(),
            headers=dict(request.headers), content=request.content)
        return httpx.Response(response.status_code, json=response.json(), request=request)

    app = create_gateway_app(stocks_url="http://isolated.test", crypto_url="http://unused.test",
        stocks_api_token="test-only-internal-token", transport=httpx.MockTransport(handler))
    client = TestClient(app)
    payload = dict(operation_key="test-only-open-001", evaluation_id=evaluation["evaluation_id"],
        contract_id="TEST261006C105000.US", quantity=2, multiplier=100, entry_price=1.01,
        underlying_entry_price=105, entry_fees=1, exit_fee_estimate=1, executed_at=args["now"].isoformat())
    assert client.post("/api/options/one-minute/manual/entries", json=payload,
        headers={"X-KQUANT-WORKSPACE-USER": "forged@example.invalid"}).status_code == 401
    assert calls == []
    assert client.post("/api/auth/login", json={"email": "test-only@example.invalid", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "test-only@example.invalid", "password": "TEST_ONLY_not_a_user_password"}).status_code == 200
    assert client.get("/api/options/one-minute/evaluations/" + evaluation["evaluation_id"]).json()["evaluation_id"] == evaluation["evaluation_id"]
    first = client.post("/api/options/one-minute/manual/entries", json=payload,
        headers={"X-KQUANT-WORKSPACE-USER": "forged@example.invalid"})
    assert first.status_code == 200, first.text
    report = first.json()
    assert report["reviewer"] == "test-only@example.invalid"
    checked = client.get("/api/options/one-minute/manual", params={"operation_key": payload["operation_key"]})
    assert checked.status_code == 200 and checked.json()["report"] == report
    assert not report["paper_fill"] and not report["real_order_created"]
    assert client.post("/api/options/one-minute/manual/entries", json=payload).json() == report
    assert client.post("/api/options/one-minute/manual/entries", json={**payload, "quantity": 3}).status_code == 400
    partial = dict(operation_key="test-only-exit-001", position_id=report["position_id"], quantity=1,
        exit_price=1.1, exit_fees=.5, executed_at=(args["now"] + timedelta(minutes=1)).isoformat())
    assert client.post("/api/options/one-minute/manual/exits", json=partial).status_code == 200
    assert original_status(ledger)["positions"][0]["open_quantity"] == 1
    auth = app.state.workspace_auth
    expired = auth.issue(email="test-only@example.invalid", issued_at=int(time.time()) - 60, expires_at=int(time.time()) - 1)
    client.cookies.clear()
    client.cookies.set("kquant_workspace_session", expired)
    count = len(calls)
    assert client.get("/api/options/one-minute/manual").status_code == 401
    assert len(calls) == count
    assert client.post("/api/auth/login", json={"email": "test-only@example.invalid", "password": "TEST_ONLY_not_a_user_password"}).status_code == 200
    restored = client.get("/api/options/one-minute/manual").json()["positions"][0]
    assert restored["open_quantity"] == 1 and restored["policy_snapshot"] == evaluation["policy_snapshot"]
    assert client.post("/api/auth/logout").status_code == 200
    assert client.post("/api/options/one-minute/manual/exits", json=partial).status_code == 401
    assert original_status(ledger)["positions"][0]["open_quantity"] == 1
