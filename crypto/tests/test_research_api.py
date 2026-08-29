from __future__ import annotations

from fastapi.testclient import TestClient

from kquant_crypto.dashboard.app import create_app


def _client(settings) -> TestClient:
    client = TestClient(create_app(settings))
    response = client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    assert response.status_code == 200
    return client


def _roll_payload():
    return {
        "asset_id": "asset:ETH",
        "symbol": "ETH",
        "asset_type": "crypto_spot",
        "as_of_time": "2026-08-23T12:00:00+00:00",
        "data_cutoff_time": "2026-08-23T11:59:00+00:00",
        "source_status": "live",
        "coverage": 1.0,
        "hard_veto": False,
        "market_state": "BULL",
        "state_probability": 0.82,
        "target_before_stop_probability": 0.72,
        "positive_return_probability": 0.70,
        "drawdown_probability": 0.18,
        "feature_snapshot_id": "bayes_features_1",
        "model_version": "crypto_bayesian_v1.0.0",
    }


def test_roll_api_persists_deterministic_research_decision(settings):
    client = _client(settings)
    response = client.post("/api/crypto/roll/evaluate", json={**_roll_payload(), "trade_plan": {}})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["action"] == "ROLL_BUY"
    assert body["decision"]["strategy_version"] == "crypto_roll_v1.0.0"
    assert body["execution_enabled"] is False
    assert body["evaluation"]["decision"] == "REJECTED"
    assert body["evaluation"]["allowed_alert"] is False
    roll_id = body["decision"]["roll_id"]
    assert client.get(f"/api/crypto/roll/{roll_id}").status_code == 200
    assert client.get("/api/crypto/roll/current").json()["items"]


def test_bayesian_and_monte_carlo_api_preserve_unavailable_states(settings):
    client = _client(settings)
    bayesian = client.post("/api/crypto/research/bayesian", json={
        "asset_id": "asset:BTC",
        "symbol": "BTC",
        "signal_time": "2026-08-23T12:00:00+00:00",
        "available_at": "2026-08-23T11:59:00+00:00",
        "source_status": "stale",
        "features": {"trend_score": 0.5},
        "required_features": ["trend_score", "relative_strength"],
    })
    assert bayesian.status_code == 200
    assert bayesian.json()["posterior"]["evidence_status"] == "data_caution"
    assert bayesian.json()["posterior"]["target_before_stop_probability"] is None
    assert bayesian.json()["posterior"]["feature_order_hash"]
    assert bayesian.json()["posterior"]["evidence"]
    assert client.get("/api/crypto/research/bayesian/asset:BTC").status_code == 200

    future_training_window = client.post("/api/crypto/research/bayesian", json={
        "asset_id": "asset:BTC",
        "symbol": "BTC",
        "signal_time": "2026-08-23T12:00:00+00:00",
        "available_at": "2026-08-23T11:59:00+00:00",
        "source_status": "live",
        "features": {"trend_score": 0.5, "relative_strength": 0.2},
        "training_window_end": "2026-08-23T12:01:00+00:00",
    })
    assert future_training_window.status_code == 422

    monte_carlo = client.post("/api/crypto/research/monte-carlo", json={
        "asset_id": "asset:BTC",
        "symbol": "BTC",
        "returns": [0.01, -0.01],
        "config": {"paths": 100},
    })
    assert monte_carlo.status_code == 200
    assert monte_carlo.json()["status"] == "simulation_unavailable"
    assert monte_carlo.json()["horizons"] == {}
    assert client.get("/api/crypto/research/monte-carlo/asset:BTC").status_code == 200


def test_roll_feature_packet_and_ocr_preview_never_write_permissions(settings):
    client = _client(settings)
    packet = client.post("/api/crypto/roll/feature-packet", json={"roll_input": _roll_payload()})
    assert packet.status_code == 200
    body = packet.json()
    assert body["research_only"] is True
    assert body["decision"]["payload"]["allowed_paper"] is False
    preview = client.post("/api/crypto/roll/ledger/ocr-preview", json={
        "text": "symbol: ETH\nrealized profit: 100\nroll capital: 50\nremaining risk: 50"
    })
    assert preview.status_code == 200
    assert preview.json()["write_allowed"] is False
    assert preview.json()["confirmation_required"] is True
    blocked_write = client.post("/api/crypto/roll-journal/confirm", json={
        "symbol": "ETH",
        "realized_profit": 100,
        "rolled_capital": 50,
        "remaining_risk": 50,
    })
    assert blocked_write.status_code == 409
    confirmed = client.post("/api/crypto/roll-journal/confirm", json={
        "preview_id": preview.json()["preview_id"],
        "asset_id": "asset:eth",
        "symbol": "ETH",
        "event_type": "manual_confirmed_journal",
        "realized_profit": 100,
        "rolled_capital": 50,
        "remaining_risk": 50,
        "user_note": "confirmed",
        "occurred_at": "2026-08-23T12:01:00+00:00",
        "confirm_write": True,
    })
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmation"]["status"] == "confirmed"
    duplicate = client.post("/api/crypto/roll-journal/confirm", json={
        "preview_id": preview.json()["preview_id"],
        "asset_id": "asset:eth",
        "symbol": "ETH",
        "event_type": "manual_confirmed_journal",
        "realized_profit": 100,
        "rolled_capital": 50,
        "remaining_risk": 50,
        "occurred_at": "2026-08-23T12:02:00+00:00",
        "confirm_write": True,
    })
    assert duplicate.status_code == 422


def test_shadow_observation_requires_no_downstream_permission(settings):
    client = _client(settings)
    payload = {
        "asset_scope": "crypto",
        "asset_id": "asset:ETH",
        "symbol": "ETH",
        "strategy_version": "crypto_roll_v1.0.0",
        "action": "DATA_BLOCKED",
        "strategy_stage": "UNKNOWN",
        "as_of_time": "2026-08-23T12:00:00+00:00",
        "data_cutoff_time": "2026-08-23T11:59:00+00:00",
        "source_status": "stale",
        "coverage": 0.0,
        "hard_veto": True,
    }
    response = client.post("/api/crypto/shadow/observations", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["observation"]["research_only"] is True
    observation_id = body["observation"]["observation_id"]
    reviewed = client.post(
        f"/api/crypto/shadow/{observation_id}/review",
        json={"user_status": "skipped", "user_note": "data blocked"},
    )
    assert reviewed.status_code == 200
    summary = client.get("/api/crypto/shadow/summary")
    assert summary.status_code == 200
    assert summary.json()["status"] == "NO_GO"


def test_shadow_active_action_requires_eval_approval(settings):
    client = _client(settings)
    payload = {
        "asset_scope": "crypto",
        "asset_id": "asset:ETH",
        "symbol": "ETH",
        "strategy_version": "crypto_roll_v1.0.0",
        "action": "ROLL_BUY",
        "strategy_stage": "ARMED",
        "as_of_time": "2026-08-23T12:00:00+00:00",
        "data_cutoff_time": "2026-08-23T11:59:00+00:00",
        "source_status": "live",
        "coverage": 1.0,
        "hard_veto": False,
    }
    response = client.post("/api/crypto/shadow/observations", json=payload)
    assert response.status_code == 409
