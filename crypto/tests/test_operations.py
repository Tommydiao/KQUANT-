from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from kquant_crypto.backup import create_backup, restore_sqlite, verify_backup_restore
from kquant_crypto.dashboard.app import create_app
from kquant_crypto.gateway import GATEWAY_VERSION, create_gateway_app
from kquant_crypto.observability import build_observability_summary
from kquant_crypto.staging import staging_status


def _expected_gateway_build_sha() -> str:
    return (
        os.getenv("KQUANT_BUILD_SHA")
        or os.getenv("GITHUB_SHA")
        or os.getenv("VERCEL_GIT_COMMIT_SHA")
        or "local"
    )[:80]


def _client(settings) -> TestClient:
    client = TestClient(create_app(settings))
    response = client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    assert response.status_code == 200
    return client


def test_operations_endpoints_are_secret_free_and_fail_closed(settings):
    client = _client(settings)
    operations = client.get("/api/operations/observability")
    assert operations.status_code == 200
    body = operations.json()
    assert body["schema"]["latest_version"] == 17
    assert body["version_matrix"]["schema"] == 17
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


def test_gateway_exposes_separate_mode_config_without_proxying_sessions():
    client = TestClient(create_gateway_app(stocks_url="http://127.0.0.1:1", crypto_url="http://127.0.0.1:2"))
    config = client.get("/api/gateway/config").json()
    assert config["session_mode"] == "separate_backend_sessions"
    assert {item["id"] for item in config["modes"]} == {"stocks", "crypto"}
    assert config["data_mixing"] is False
    assert config["secrets_exposed"] is False
    assert config["build_sha"] == _expected_gateway_build_sha()


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
    config = client.get("/api/gateway/config").json()
    assert {item["id"] for item in config["modes"]} == {"stocks", "crypto"}
    assert config["data_mixing"] is False
    health = client.get("/api/gateway/health").json()
    assert health["gateway_version"] == GATEWAY_VERSION
    assert health["data_mixing"] is False
    assert health["session_mode"] == "separate_backend_sessions"
    assert health["order_submission"] is False
    assert health["build_sha"] == _expected_gateway_build_sha()
    assert client.get("/api/version").json()["order_submission"] is False
    platform_health = client.get("/api/platform/health").json()
    assert platform_health["status"] == "degraded"
    summary = client.get("/api/platform/summary").json()
    assert {item["id"] for item in summary["modes"]} == {"stocks", "crypto"}
    assert summary["data_mixing"] is False
    assert summary["order_submission"] is False


def test_observability_summary_is_read_only(settings):
    summary = build_observability_summary(settings.db_path, settings=settings)
    assert summary["research_only"] is True
    assert summary["secrets_exposed"] is False
    assert summary["storage"]["table_counts"]["crypto_shadow_observations"] == 0
