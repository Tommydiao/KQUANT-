"""Absent/present policy handling using isolated fixtures, never original-policy recovery."""
from hashlib import sha256
import json

import pytest

from kquant import options_full_watch as full
from kquant import options_profiles as profiles
from kquant import options_signal_copilot as copilot
from kquant.policy_availability import PolicyConfigUnavailable


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.mark.parametrize("capability", ["full_watch", "signal_copilot", "research_profiles"])
def test_missing_policy_is_unavailable_without_reading_or_creating_business_store(tmp_path, monkeypatch, capability):
    source, store = tmp_path / "missing-policy.json", tmp_path / "missing-business.sqlite3"
    if capability == "full_watch":
        monkeypatch.setattr(full, "CONFIG_PATH", source)
        result = full.full_watch_status(store_path=store)
    elif capability == "signal_copilot":
        monkeypatch.setattr(copilot, "CONFIG_PATH", source)
        result = copilot.copilot_status(store_path=store)
        assert result["paper_execution"]["enabled"] is False
    else:
        result = profiles.load_options_profiles(source)
        assert result["profiles"] == [] and result["profile_records_complete"] is False
    assert result["status"] == "UNAVAILABLE" and result["reason"] == "POLICY_CONFIG_MISSING"
    assert result["current_policy_available"] is False
    assert result["historical_records_status"] == "UNKNOWN" and result["position_records_complete"] is False
    assert not result["paper_enabled"] and not result["orders_enabled"]
    assert not store.exists() and not source.exists()


def test_missing_full_watch_policy_rejects_scan_and_quote_probe_before_side_effects(tmp_path, monkeypatch):
    monkeypatch.setattr(full, "CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(full, "initialize_full_watch_store", lambda *a, **k: pytest.fail("store initialized"))
    monkeypatch.setattr(full, "option_expiries", lambda *a, **k: pytest.fail("provider called"))
    with pytest.raises(PolicyConfigUnavailable, match="POLICY_CONFIG_MISSING"):
        full.run_full_watch_scan(tmp_path / "main.sqlite3", store_path=tmp_path / "watch.sqlite3")
    with pytest.raises(PolicyConfigUnavailable, match="POLICY_CONFIG_MISSING"):
        full.check_full_watch_options("NVDA", store_path=tmp_path / "watch.sqlite3")


def test_missing_copilot_policy_rejects_overlay_before_signal_read_quote_or_write(tmp_path, monkeypatch):
    monkeypatch.setattr(copilot, "CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(copilot, "signal_detail", lambda *a, **k: pytest.fail("signal/store read"))
    with pytest.raises(PolicyConfigUnavailable, match="POLICY_CONFIG_MISSING"):
        copilot.confirm_paper_intent(signal_id="TEST_ONLY", action="ENTRY", confirmation_id="TEST_ONLY",
            confirmation_text="CONFIRM PAPER ENTRY", contract={}, store_path=tmp_path / "paper.sqlite3",
            quote_fetcher=lambda: pytest.fail("provider called"))
    assert not (tmp_path / "paper.sqlite3").exists()


def test_present_config_keeps_identity_validation_and_safe_overlay_gate(tmp_path, monkeypatch):
    source = write(tmp_path / "watch.json", {"config_id": full.SCOPE_ID, "paper_scope_approved": False})
    monkeypatch.setattr(full, "CONFIG_PATH", source)
    assert full.full_watch_policy_status()["current_policy_available"] is True
    assert full.full_watch_status(store_path=tmp_path / "absent-store.sqlite3")["status"] == "NOT_STARTED"
    write(source, {"config_id": "WRONG"})
    with pytest.raises(ValueError, match="FULL_WATCH_CONFIG_ID_MISMATCH"):
        full._config()
    source = write(tmp_path / "copilot.json", {"effective": False,
        "safety": {"real_order_enabled": False, "real_account_access_enabled": False}})
    monkeypatch.setattr(copilot, "CONFIG_PATH", source)
    assert copilot.load_copilot_config()["config_hash"]
    assert copilot.copilot_status(store_path=tmp_path / "absent-store.sqlite3")["status"] == "NOT_INITIALIZED"
    write(source, {"safety": {"real_order_enabled": True}})
    with pytest.raises(RuntimeError, match="REAL_ORDER_PERMISSION_FORBIDDEN"):
        copilot.load_copilot_config()


def test_present_profile_metadata_is_read_and_hashed_without_activating_strategy(tmp_path):
    payload = {"schema_version": "options_research_profiles_draft_v1", "purpose": "METADATA_AND_OBSERVATION_ONLY",
               "profiles": [{"profile_id": name, "option_rights": ["CALL", "PUT"],
                   "strategy_status": "PENDING_STRATEGY_DEFINITION", "signal_generation_enabled": False,
                   "trade_simulation_enabled": False, "automatic_order_enabled": False,
                   **dict.fromkeys(profiles.PENDING_FIELDS)} for name in profiles.PROFILE_IDS]}
    source = write(tmp_path / "profiles.json", payload)
    result = profiles.load_options_profiles(source)
    assert len(result["profiles"]) == 3 and result["config_sha256"] == sha256(source.read_bytes()).hexdigest()
    assert result["metadata_validation"]["status"] == "pass"
    assert result["activation_validation"]["activation_allowed"] is False
    assert not result["signal_generation_enabled"]


def test_invalid_json_is_blocked_as_invalid_not_missing_or_default_policy(tmp_path, monkeypatch):
    source = tmp_path / "invalid.json"
    source.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(full, "CONFIG_PATH", source)
    result = full.full_watch_status(store_path=tmp_path / "business.sqlite3")
    assert result["status"] == "UNAVAILABLE" and result["reason"] == "POLICY_CONFIG_INVALID"
    assert result["current_policy_available"] is False


def test_missing_policy_status_and_write_routes_are_explicit_without_provider_or_overlay(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from kquant.config import KquantConfig
    from kquant.dashboard import app as dashboard
    from kquant import options_two_hour
    for flag in ("KQUANT_REALTIME_SUPERVISOR_ENABLED", "KQUANT_OPTION_RADAR_ENABLED", "KQUANT_REQUIRE_API_AUTH"):
        monkeypatch.setenv(flag, "false")
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_ENABLED", "false")
    monkeypatch.setattr(profiles, "DEFAULT_PROFILE_PATH", tmp_path / "absent-profiles.json")
    monkeypatch.delenv("KQUANT_OPTIONS_PROFILE_CONFIG", raising=False)
    monkeypatch.setattr(full, "CONFIG_PATH", tmp_path / "absent-watch.json")
    monkeypatch.setattr(copilot, "CONFIG_PATH", tmp_path / "absent-copilot.json")
    monkeypatch.setattr(options_two_hour, "status", lambda: {"status": "TEST_ONLY"})
    monkeypatch.setattr(dashboard, "option_contract_snapshot", lambda *a, **k: pytest.fail("SDK quote requested"))
    client = TestClient(dashboard.create_app(config=KquantConfig(db_path=tmp_path / "test-main.sqlite3", outputs_dir=tmp_path / "outputs"),
        research_store=tmp_path / "test-research.sqlite3", manual_store=tmp_path / "test-manual.sqlite3"))
    for endpoint in ("/api/options/profiles", "/api/options/foundation/status", "/api/options/copilot/status", "/api/options/full-watch/status?operations_only=true"):
        response = client.get(endpoint)
        assert response.status_code == 200
        assert response.json()["status"] == "UNAVAILABLE" and response.json()["reason"] == "POLICY_CONFIG_MISSING"
    for endpoint, payload in (("/api/options/full-watch/scan", None), ("/api/options/full-watch/options/NVDA", None),
        ("/api/options/copilot/signals/test-only/state", {"state": "WATCH", "reason": "TEST_ONLY"}),
        ("/api/options/copilot/paper/confirm", {"signal_id": "TEST_ONLY", "action": "ENTRY", "confirmation_id": "TEST_ONLY",
            "confirmation_text": "CONFIRM PAPER ENTRY", "contract_id": "TEST_ONLY", "underlying": "NVDA", "limit_price": 1,
            "contract_multiplier": 100, "theme_id": "TEST_ONLY"})):
        response = client.post(endpoint, json=payload)
        assert response.status_code == 503, (endpoint, response.text)
        assert response.json()["detail"]["reason"] == "POLICY_CONFIG_MISSING"
