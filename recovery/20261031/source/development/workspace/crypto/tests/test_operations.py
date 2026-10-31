from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from kquant_crypto.backup import create_backup, restore_sqlite, verify_backup_restore
from kquant_crypto.dashboard.app import create_app
from kquant_crypto.gateway import GATEWAY_VERSION, create_gateway_app
from kquant_crypto.observability import build_observability_summary
from kquant_crypto.security import hash_password
from kquant_crypto.staging import staging_status


def _client(settings) -> TestClient:
    client = TestClient(create_app(settings))
    response = client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    assert response.status_code == 200
    return client


def test_chart_read_only_routes_and_stream():
    def handler(request):
        if request.url.path.endswith('/chart/stream'):
            return httpx.Response(200, text='event: ready\ndata: {}\n\n', headers={'content-type': 'text/event-stream'})
        return httpx.Response(200, json={'source': 'Longbridge', 'read_only': True})
    client = TestClient(create_gateway_app(stocks_url='http://stock.local', crypto_url='http://crypto.local', transport=httpx.MockTransport(handler)))
    assert client.get('/api/stocks/depth?symbol=COIN').json()['read_only'] is True
    assert 'event: ready' in client.get('/api/stocks/chart/stream?symbol=COIN').text
    assert client.post('/api/stocks/depth', json={}).status_code in (404, 405)
    assert client.post('/api/stocks/chart/stream', json={}).status_code in (404, 405)
    assert client.get('/api/stocks/orders').status_code == 404


def test_gateway_prefers_fast_liveness_and_rejects_html_health():
    import asyncio
    from kquant_crypto.gateway import Backend, _probe_backend
    paths=[]
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200,json={'status':'online','market_data_checked':False})
    backend=Backend('stocks','http://stock.local','','x-kquant-api-token')
    result=asyncio.run(_probe_backend(backend,transport=httpx.MockTransport(handler)))
    assert result['status']=='available' and result['market_data_checked'] is False
    assert paths==['/api/health/live']
    result=asyncio.run(_probe_backend(backend,transport=httpx.MockTransport(lambda req:httpx.Response(200,text='<html>fallback</html>'))))
    assert result['status']=='unhealthy'


def test_operations_endpoints_are_secret_free_and_fail_closed(settings):
    client = _client(settings)
    operations = client.get("/api/operations/observability")
    assert operations.status_code == 200
    body = operations.json()
    assert body["schema"]["latest_version"] == 21
    assert body["version_matrix"]["schema"] == 21
    assert body["started_at"]
    assert body["build_sha"] == "local"
    assert body["staging"]["status"] == "not_configured"
    assert body["secrets_exposed"] is False
    assert client.get("/api/operations/staging").json()["postgres_configured"] is False
    assert client.get("/api/operations/backup/status").json()["restore_verified"] is False
    readiness = client.get("/api/operations/go-no-go")
    assert readiness.status_code == 200
    assert readiness.json()["readiness"]["status"] == "NO_GO"
    assert readiness.json()["readiness"]["research_only"] is True
    assert readiness.json()["readiness"]["order_submission"] is False


def test_gateway_exposes_unified_mode_config_without_merging_databases():
    client = TestClient(create_gateway_app(stocks_url="http://127.0.0.1:1", crypto_url="http://127.0.0.1:2"))
    config = client.get("/api/gateway/config").json()
    assert config["session_mode"] == "unified_gateway_session"
    assert {item["id"] for item in config["modes"]} == {"stocks", "options", "crypto"}
    assert config["data_mixing"] is False
    assert config["secrets_exposed"] is False


def test_backup_and_restore_preserve_sqlite_content(settings, tmp_path):
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("CREATE TABLE backup_probe(value TEXT NOT NULL)")
        conn.execute("INSERT INTO backup_probe(value) VALUES ('ok')")
        conn.commit()
    result = create_backup(db_path=settings.db_path, data_dir=settings.data_dir, output_dir=tmp_path / "backups")
    assert result["data_manifest_mode"] == "metadata_only"
    restored = tmp_path / "restored.sqlite3"
    restore_sqlite(Path(result["backup_dir"]) / "kquant_crypto.sqlite3", restored)
    with sqlite3.connect(restored) as conn:
        assert conn.execute("SELECT value FROM backup_probe").fetchone()[0] == "ok"


def test_backup_restore_verification_updates_manifest(settings, tmp_path):
    result = create_backup(db_path=settings.db_path, data_dir=settings.data_dir, output_dir=tmp_path / "backups")
    restored = tmp_path / "verified.sqlite3"

    verification = verify_backup_restore(Path(result["backup_dir"]), restored)

    assert verification["status"] == "verified"
    assert verification["sqlite_quick_check"] == "ok"
    assert verification["source_sha256"] == verification["restored_sha256"]
    manifest = Path(result["backup_dir"]) / "manifest.json"
    assert '"restore_verified": true' in manifest.read_text(encoding="utf-8")


def test_gateway_keeps_backends_separate():
    client = TestClient(create_gateway_app(stocks_url="http://127.0.0.1:1", crypto_url="http://127.0.0.1:2"))
    page = client.get("/")
    assert page.status_code == 200
    assert "KQUANT" in page.text
    assert "Stocks" in page.text or "unified" in page.text.lower()
    assert "Crypto" in page.text or "unified" in page.text.lower()
    assert "/api/gateway/health" in page.text or "unified" in page.text.lower()
    health = client.get("/api/gateway/health").json()
    assert health["gateway_version"] == GATEWAY_VERSION
    assert health["data_mixing"] is False
    assert health["session_mode"] == "unified_gateway_session"
    assert health["order_submission"] is False


def test_unified_gateway_login_and_allowlisted_proxy(monkeypatch):
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_ENABLED", "true")
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH", hash_password("correct horse battery staple"))
    monkeypatch.setenv("KQUANT_WORKSPACE_SESSION_SECRET", "s" * 48)
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        return httpx.Response(200, json={"status": "ok", "read_only": True}, request=request)

    transport = httpx.MockTransport(handler)
    client = TestClient(
        create_gateway_app(
            stocks_url="http://stock.local",
            crypto_url="http://crypto.local",
            stocks_api_token="stock-token",
            crypto_api_token="crypto-token",
            transport=transport,
        )
    )
    assert client.get("/api/stocks/health").status_code == 401
    assert client.post("/api/options/event-sources/reviews", json={}).status_code == 401
    login = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery staple"})
    assert login.status_code == 200
    assert "kquant_workspace_session" in client.cookies
    assert client.get("/api/stocks/health").json()["status"] == "ok"
    assert client.get("/api/crypto/health").json()["status"] == "ok"
    assert client.post("/api/options/event-sources/reviews", json={}).status_code == 200
    assert any(headers.get("x-kquant-workspace-user") == "owner@example.com" for headers in seen_headers)
    assert any(headers.get("x-kquant-api-token") == "stock-token" for headers in seen_headers)
    assert any(headers.get("x-kquant-crypto-internal-token") == "crypto-token" for headers in seen_headers)
    assert client.get("/api/stocks/account").status_code == 404
    assert client.get("/api/crypto/wallet").status_code == 404
    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert client.get("/api/stocks/health").status_code == 401


def test_login_file_change_blocks_protected_routes_until_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_ENABLED", "true")
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH", hash_password("correct horse battery staple"))
    monkeypatch.setenv("KQUANT_WORKSPACE_SESSION_SECRET", "s" * 48)
    login_file = tmp_path / "KQUANT" / "workspace_login.dpapi"
    login_file.parent.mkdir()
    login_file.write_text("original", encoding="utf-8")
    client = TestClient(create_gateway_app(stocks_url="http://stock.local", crypto_url="http://crypto.local"))
    assert client.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery staple"}).status_code == 200
    assert client.get("/api/auth/session").json()["authenticated"] is True

    login_file.write_text("replacement", encoding="utf-8")
    session = client.get("/api/auth/session").json()
    assert session["restart_required"] is True
    assert session["authenticated"] is False
    assert client.get("/api/stocks/health").status_code == 503
    assert client.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery staple"}).status_code == 503


def test_new_login_file_blocks_unprotected_running_gateway(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for name in ("KQUANT_WORKSPACE_LOGIN_ENABLED", "KQUANT_WORKSPACE_LOGIN_EMAIL", "KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH", "KQUANT_WORKSPACE_SESSION_SECRET"):
        monkeypatch.delenv(name, raising=False)
    client = TestClient(create_gateway_app(stocks_url="http://stock.local", crypto_url="http://crypto.local"))
    login_file = tmp_path / "KQUANT" / "workspace_login.dpapi"
    login_file.parent.mkdir()
    login_file.write_text("new", encoding="utf-8")
    assert client.get("/api/auth/session").json()["restart_required"] is True
    assert client.get("/api/stocks/health").status_code == 503


def test_slow_login_file_check_is_single_flight_and_does_not_block_live(monkeypatch, tmp_path):
    import asyncio
    from pathlib import Path
    from threading import Event
    from time import monotonic

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for name in ("KQUANT_WORKSPACE_LOGIN_ENABLED", "KQUANT_WORKSPACE_LOGIN_EMAIL", "KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH", "KQUANT_WORKSPACE_SESSION_SECRET"):
        monkeypatch.delenv(name, raising=False)
    app = create_gateway_app(stocks_url="http://stock.local", crypto_url="http://crypto.local")
    blocked = Event()
    entered = Event()
    original = Path.read_bytes
    reads = []

    def delayed(path):
        if path.name == "workspace_login.dpapi":
            reads.append(1)
            entered.set()
            blocked.wait(2)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", delayed)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway.local") as client:
            started = monotonic()
            results = await asyncio.gather(*[client.get("/api/options/opening-trend/current") for _ in range(6)])
            assert monotonic() - started < .5
            assert all(r.status_code == 503 and r.json()["detail"] == "LOGIN_CONFIGURATION_CHECK_UNAVAILABLE" for r in results)
            assert entered.is_set()
            assert len(reads) == 1
            for _ in range(6):
                assert (await client.get("/api/health/live")).status_code == 200
            assert len(reads) == 1
            blocked.set()
            await asyncio.wrap_future(app.state.login_fingerprint_check.future)
            session = (await client.get("/api/auth/session")).json()
            assert session["configuration_check_unavailable"] is False
            assert session["restart_required"] is False

    try:
        asyncio.run(exercise())
    finally:
        blocked.set()
        app.state.login_fingerprint_check.close()


def test_unified_gateway_development_proxy_has_local_identity(monkeypatch):
    for name in (
        "KQUANT_WORKSPACE_LOGIN_ENABLED",
        "KQUANT_WORKSPACE_LOGIN_EMAIL",
        "KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH",
        "KQUANT_WORKSPACE_SESSION_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        return httpx.Response(200, json={"status": "ok", "read_only": True}, request=request)

    client = TestClient(
        create_gateway_app(
            stocks_url="http://stock.local",
            crypto_url="http://crypto.local",
            crypto_api_token="crypto-token",
            transport=httpx.MockTransport(handler),
        )
    )
    response = client.get("/api/crypto/providers/status")
    assert response.status_code == 200
    assert any(headers.get("x-kquant-crypto-internal-token") == "crypto-token" for headers in seen_headers)
    assert any(headers.get("x-kquant-workspace-user") == "local@kquant.local" for headers in seen_headers)


def test_gateway_preserves_json_body_type_for_allowed_mutations() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("content-type"),
                     request.headers.get("user-agent"), json.loads(request.content)))
        return httpx.Response(200, json={"status": "accepted"}, request=request)

    client = TestClient(create_gateway_app(
        stocks_url="http://stock.local", crypto_url="http://crypto.local",
        transport=httpx.MockTransport(handler)))
    payload = {"endpoint": "https://push.example.test/subscription/abc",
               "keys": {"p256dh": "fixture", "auth": "fixture"}}
    response = client.post("/api/stocks/notifications/web-push/subscribe", json=payload,
                           headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    assert response.status_code == 200
    assert seen == [("/api/notifications/web-push/subscribe", "application/json",
                     "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", payload)]


def test_gateway_options_proxy_is_explicitly_allowlisted() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"status": "ok"}, request=request)

    client = TestClient(
        create_gateway_app(
            stocks_url="http://stock.local",
            crypto_url="http://crypto.local",
            transport=httpx.MockTransport(handler),
        )
    )

    assert client.get("/api/options/radar/signals").status_code == 200
    assert client.post("/api/options/watchlist", json={"plan_id": "plan-1"}).status_code == 200
    assert client.post("/api/options/status", json={}).status_code == 404
    assert client.post("/api/options/full-watch/observations", json={"evaluation_id": "e", "active": True}).status_code == 200
    assert client.delete("/api/options/full-watch/observations").status_code == 404
    assert client.post("/api/options/full-watch/observations/anything", json={}).status_code == 404
    assert client.get("/api/options/orders").status_code == 404
    assert ("GET", "/api/options/radar/signals") in seen
    assert ("POST", "/api/options/watchlist") in seen


def test_gateway_allows_grouped_watchlist_without_opening_order_paths() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"status": "ok"}, request=request)

    client = TestClient(create_gateway_app(stocks_url="http://stock.local", crypto_url="http://crypto.local", transport=httpx.MockTransport(handler)))
    assert client.get("/api/stocks/watchlist/groups").status_code == 200
    assert client.post("/api/stocks/watchlist/members", json={"group_id": "m7", "symbol": "SPY"}).status_code == 200
    assert client.delete("/api/stocks/watchlist/members/watch-1").status_code == 200
    assert client.post("/api/stocks/orders", json={}).status_code == 404
    assert ("GET", "/api/stocks/watchlist/groups") in seen
    assert ("POST", "/api/stocks/watchlist/members") in seen


def test_observability_summary_is_read_only(settings):
    summary = build_observability_summary(settings.db_path, settings=settings)
    assert summary["research_only"] is True
    assert summary["secrets_exposed"] is False
    assert summary["storage"]["table_counts"]["crypto_shadow_observations"] == 0
def test_gateway_progress_is_not_a_notification():
    from kquant_crypto.gateway import alert_stream_event_name
    assert alert_stream_event_name('{"type":"options_two_hour_progress"}') == "operations"
    assert alert_stream_event_name('{"type":"options_two_hour_research"}') == "alert"
    assert alert_stream_event_name('not-json') == "alert"
