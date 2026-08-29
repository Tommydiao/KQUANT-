from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from kquant.config import KquantConfig
from kquant.dashboard.app import create_app
from kquant.security import SESSION_COOKIE_NAME, generate_password_hash


def _app(tmp_path: Path):
    return create_app(config=KquantConfig(db_path=tmp_path / "kquant.sqlite3", outputs_dir=tmp_path / "outputs"))


def test_local_cors_is_restricted_and_security_headers_are_present(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("KQUANT_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("KQUANT_FRAME_ANCESTORS", raising=False)
    client = TestClient(_app(tmp_path))
    response = client.get("/api/health", headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") is None
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert response.json()["security"]["secrets_exposed"] is False


def test_explicit_local_gateway_origin_can_frame_dashboard(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(
        "KQUANT_FRAME_ANCESTORS",
        "http://127.0.0.1:8020 http://localhost:8020 javascript:alert(1)",
    )
    response = TestClient(_app(tmp_path)).get("/")

    assert response.status_code == 200
    assert "x-frame-options" not in response.headers
    assert response.headers["content-security-policy"] == (
        "frame-ancestors 'self' http://127.0.0.1:8020 http://localhost:8020"
    )


def test_optional_api_auth_fails_closed_without_leaking_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KQUANT_REQUIRE_API_AUTH", "true")
    monkeypatch.setenv("KQUANT_API_AUTH_TOKEN", "local-test-token")
    client = TestClient(_app(tmp_path))
    assert client.get("/api/health").status_code == 401
    response = client.get("/api/health", headers={"X-KQUANT-API-TOKEN": "local-test-token"})
    assert response.status_code == 200
    assert "local-test-token" not in response.text


def test_invalid_rate_limit_environment_keeps_dashboard_startable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KQUANT_API_RATE_LIMIT_PER_MINUTE", "not-a-number")
    client = TestClient(_app(tmp_path))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["security"]["rate_limit_per_minute"] == 240


def test_local_email_password_login_protects_research_apis(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KQUANT_LOGIN_ENABLED", "true")
    monkeypatch.setenv("KQUANT_LOGIN_EMAIL", "researcher@example.com")
    monkeypatch.setenv("KQUANT_LOGIN_PASSWORD_HASH", generate_password_hash("correct-horse-battery"))
    monkeypatch.setenv("KQUANT_SESSION_SECRET", "x" * 48)
    client = TestClient(_app(tmp_path))

    assert client.get("/api/health").status_code == 401
    assert client.get("/api/auth/session").json()["authenticated"] is False
    assert client.post("/api/auth/login", json={"email": "wrong@example.com", "password": "correct-horse-battery"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "researcher@example.com", "password": "wrong-password"}).status_code == 401

    logged_in = client.post("/api/auth/login", json={"email": "researcher@example.com", "password": "correct-horse-battery"})
    assert logged_in.status_code == 200
    assert SESSION_COOKIE_NAME in logged_in.headers["set-cookie"]
    assert client.get("/api/health").status_code == 200

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/health").status_code == 401


def test_local_login_rate_limit_and_expired_session_fail_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KQUANT_LOGIN_ENABLED", "true")
    monkeypatch.setenv("KQUANT_LOGIN_EMAIL", "researcher@example.com")
    monkeypatch.setenv("KQUANT_LOGIN_PASSWORD_HASH", generate_password_hash("correct-horse-battery"))
    monkeypatch.setenv("KQUANT_SESSION_SECRET", "y" * 48)
    monkeypatch.setenv("KQUANT_LOGIN_ATTEMPT_LIMIT", "3")
    app = _app(tmp_path)
    client = TestClient(app)

    for _ in range(3):
        assert client.post("/api/auth/login", json={"email": "researcher@example.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "researcher@example.com", "password": "wrong-password"}).status_code == 429

    expired = app.state.session_auth.issue_session(issued_at=int(time.time()) - 8 * 3600, expires_at=int(time.time()) - 1)
    client.cookies.set(SESSION_COOKIE_NAME, expired)
    assert client.get("/api/health").status_code == 401
