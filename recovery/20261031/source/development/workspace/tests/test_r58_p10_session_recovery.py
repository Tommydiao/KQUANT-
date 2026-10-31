"""Real gateway routes with TEST_ONLY credentials and controlled file I/O."""
from threading import Event
from time import monotonic
import json
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from kquant.security import generate_password_hash
from kquant_crypto.gateway import create_gateway_app


@pytest.mark.parametrize("read_result", ["unchanged", "replaced", "io_error"])
def test_session_unavailable_is_503_and_real_result_preserves_revocation(tmp_path, monkeypatch, read_result):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_ENABLED", "true")
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_EMAIL", "test-only@example.invalid")
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH", generate_password_hash("TEST_ONLY long test password"))
    monkeypatch.setenv("KQUANT_WORKSPACE_SESSION_SECRET", "TEST_ONLY_SESSION_SECRET_" * 4)
    sentinel = tmp_path / "KQUANT/workspace_login.dpapi"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"TEST_ONLY sentinel, not user DPAPI")
    app = create_gateway_app(stocks_url="http://TEST_ONLY", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": "ok"})))
    gate, entered = Event(), Event()
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={"email": "test-only@example.invalid",
            "password": "TEST_ONLY long test password"}).status_code == 200
        assert client.get("/api/auth/session").json()["authenticated"] is True
        checker = app.state.login_fingerprint_check
        original_reader = checker.reader
        original_cookie = dict(client.cookies)
        issuer = Mock(wraps=app.state.workspace_auth.issue)
        monkeypatch.setattr(app.state.workspace_auth, "issue", issuer)

        def delayed_read():
            entered.set()
            assert gate.wait(3)
            if read_result == "io_error":
                raise OSError("TEST_ONLY file I/O unavailable")
            if read_result == "replaced":
                sentinel.write_bytes(b"TEST_ONLY replacement")
            return original_reader()

        checker.reader = delayed_read
        try:
            started = monotonic()
            response = client.get("/api/auth/session")
            assert monotonic() - started < 1
            assert entered.is_set() and response.status_code == 503
            assert response.headers["Retry-After"] == "1"
            assert response.json()["detail"] == "LOGIN_CONFIGURATION_CHECK_UNAVAILABLE"
            assert response.json()["configuration_check"]["reason"] == "FILE_CHECK_PENDING"
            assert dict(client.cookies) == original_cookie
            assert "set-cookie" not in response.headers
            issuer.assert_not_called()
            pending_response = {"status": response.status_code, "body": response.json(),
                                "retry_after": response.headers["Retry-After"]}
            pending = checker.future
            assert client.get("/api/stocks/health").status_code == 503
            assert checker.future is pending
            assert client.get("/api/health/live").status_code == 200
            issuer.assert_not_called()
            gate.set()
            pending.result(timeout=3)
            response = client.get("/api/auth/session")
            assert response.json()["configuration_check"]["reader_running"] is False
            if read_result == "unchanged":
                assert response.status_code == 200 and response.json()["authenticated"] is True
                assert client.get("/api/stocks/health").status_code == 200
            elif read_result == "replaced":
                assert response.status_code == 200 and response.json()["restart_required"] is True
                assert not response.json()["authenticated"]
                assert client.get("/api/stocks/health").status_code == 503
                assert "set-cookie" not in response.headers
                issuer.assert_not_called()
            else:
                assert response.status_code == 503
                assert response.json()["configuration_check"]["reason"] == "FILE_READ_FAILED"
                assert "set-cookie" not in response.headers
                issuer.assert_not_called()
                file_error_response = {"status": response.status_code, "body": response.json()}
                checker.reader = original_reader
                response = client.get("/api/auth/session")
                assert response.status_code == 200 and response.json()["authenticated"] is True
            assert "file I/O unavailable" not in response.text
            (tmp_path / "TEST_ONLY-session-recovery-trace.json").write_text(json.dumps({
                "test_only": True, "real_user_credentials": False, "read_result": read_result,
                "pending_response": pending_response,
                "file_error_response": file_error_response if read_result == "io_error" else None,
                "recovered_response": {"status": response.status_code, "body": response.json()},
                "same_cookie": dict(client.cookies) == original_cookie,
                "original_check_budget_seconds": .05, "shared_inflight_verified": True}), encoding="utf-8")
        finally:
            gate.set()
