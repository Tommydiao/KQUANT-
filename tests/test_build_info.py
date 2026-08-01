from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from btc_eth_15m.dashboard.app import create_app
from kquant.build_info import build_info


def test_build_info_uses_explicit_release_environment(monkeypatch) -> None:
    monkeypatch.setenv("KQUANT_BUILD_SHA", "a" * 40)
    monkeypatch.setenv("KQUANT_BUILD_TIME", "2026-08-01T12:00:00Z")
    monkeypatch.setenv("KQUANT_ENVIRONMENT", "staging")
    build_info.cache_clear()

    payload = build_info()

    assert payload["build_sha"] == "a" * 40
    assert payload["build_sha_short"] == "aaaaaaa"
    assert payload["build_time"] == "2026-08-01T12:00:00Z"
    assert payload["environment"] == "staging"
    build_info.cache_clear()


def test_version_and_health_share_the_same_build_identity(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KQUANT_BUILD_SHA", "b" * 40)
    monkeypatch.setenv("KQUANT_BUILD_TIME", "2026-08-01T13:00:00Z")
    monkeypatch.setenv("KQUANT_ENVIRONMENT", "test")
    build_info.cache_clear()
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["SPY"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(config_path))

    version = client.get("/api/version").json()
    health = client.get("/api/health").json()

    assert version["build_sha"] == "b" * 40
    assert health["build_sha"] == version["build_sha"]
    assert health["environment"] == "test"
    assert health["broker_order_wiring_enabled"] is False
    build_info.cache_clear()
