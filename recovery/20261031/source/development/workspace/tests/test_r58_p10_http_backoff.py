"""Existing API cap and authentication stay unchanged; retries are explicit."""
from types import SimpleNamespace

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from kquant import security


def guarded_app(monkeypatch, clock):
    monkeypatch.setenv("KQUANT_LOGIN_ENABLED", "false")
    monkeypatch.setenv("KQUANT_REQUIRE_API_AUTH", "true")
    monkeypatch.setenv("KQUANT_API_AUTH_TOKEN", "TEST_ONLY_transport_token")
    monkeypatch.setenv("KQUANT_API_RATE_LIMIT_PER_MINUTE", "10")
    monkeypatch.setattr(security, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    settings = security.SecuritySettings.from_environment()
    app = Starlette(routes=[Route("/api/test-only-snapshot", lambda request: JSONResponse({"snapshot": "TEST_ONLY"}))])
    app.add_middleware(security.ApiSecurityMiddleware, settings=settings,
                       session_auth=security.LocalSessionAuth(settings))
    return app


def test_rate_limit_has_remaining_window_without_raising_cap(monkeypatch):
    clock = [100.0]
    with TestClient(guarded_app(monkeypatch, clock)) as client:
        client.headers["X-KQUANT-API-TOKEN"] = "TEST_ONLY_transport_token"
        for _ in range(10):
            assert client.get("/api/test-only-snapshot").status_code == 200
        response = client.get("/api/test-only-snapshot")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"
        assert response.headers["cache-control"] == "no-store"
        clock[0] = 159.2
        response = client.get("/api/test-only-snapshot")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "1"
        clock[0] = 160.0
        assert client.get("/api/test-only-snapshot").status_code == 200


def test_auth_denials_do_not_consume_or_bypass_authenticated_quota(monkeypatch):
    with TestClient(guarded_app(monkeypatch, [100.0])) as client:
        for _ in range(11):
            response = client.get("/api/test-only-snapshot")
            assert response.status_code == 401
            assert "retry-after" not in response.headers
        client.headers["X-KQUANT-API-TOKEN"] = "TEST_ONLY_transport_token"
        for _ in range(10):
            assert client.get("/api/test-only-snapshot").status_code == 200
        assert client.get("/api/test-only-snapshot").status_code == 429
