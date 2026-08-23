from __future__ import annotations

from fastapi.testclient import TestClient

from kquant_crypto.dashboard.app import create_app
from kquant_crypto.dex_models import DexMarketStore, DexPairSnapshot, DexSecurityStore, TokenSecurityInput, assess_token_security


def test_health_is_public_but_research_is_authenticated(settings):
    client = TestClient(create_app(settings))
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["read_only"] is True
    assert client.get("/api/crypto/evaluations/latest").status_code == 401
    assert client.get("/api/auth/session").json()["authenticated"] is False


def test_login_unlocks_read_only_routes(settings):
    client = TestClient(create_app(settings))
    response = client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    assert response.status_code == 200
    assert client.get("/api/crypto/evaluations/latest").status_code == 200
    assert client.get("/api/runtime/boundary").json()["eval_is_final_reviewer"] is True


def test_factor_registry_is_exposed_after_login(settings):
    client = TestClient(create_app(settings))
    client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    response = client.get("/api/crypto/factors/registry")
    assert response.status_code == 200
    body = response.json()
    assert body["factor_version"] == "crypto_factor_v1.0.1"
    assert len(body["registered_factor_ids"]) == 12
    assert body["meme_factor_version"] == "crypto_meme_factor_v1.0.0"
    assert len(body["meme_registered_factor_ids"]) == 6
    assert body["llm_can_modify"] is False


def test_data_coverage_exposes_canonical_registry(settings):
    client = TestClient(create_app(settings))
    client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    response = client.get("/api/crypto/data/coverage")
    assert response.status_code == 200
    body = response.json()
    assert "assets" in body
    assert body["registry"]["asset_count"] >= 0
    assert body["coverage_gate"]["evidence_scope"] == "persisted_parquet_span"
    assert "missing_symbols" in body["coverage_gate"]
    assert body["continuous_collection_gate"]["evidence_scope"] == "independent_collector_session"


def test_parquet_validation_endpoint_fails_closed_without_closed_dataset(settings):
    client = TestClient(create_app(settings))
    client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    response = client.post("/api/crypto/validation/runs/from-parquet", json={"symbols": ["SOLUSDT"]})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NO_GO"
    assert body["report"] is None


def test_model_artifact_endpoint_is_authenticated_and_read_only(settings):
    client = TestClient(create_app(settings))
    assert client.get("/api/crypto/models").status_code == 401
    client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    response = client.get("/api/crypto/models")
    assert response.status_code == 200
    assert response.json()["execution_enabled"] is False


def test_model_benchmark_endpoint_is_authenticated_and_does_not_unlock_eval(settings):
    client = TestClient(create_app(settings))
    assert client.get("/api/crypto/validation/model-benchmarks/latest").status_code == 401
    client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    response = client.get("/api/crypto/validation/model-benchmarks/latest")
    assert response.status_code == 200
    assert response.json()["status"] == "not_collected"


def test_validation_gate_endpoint_is_authenticated_and_fail_closed(settings):
    client = TestClient(create_app(settings))
    assert client.get("/api/crypto/validation/gate").status_code == 401
    client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    response = client.get("/api/crypto/validation/gate")
    assert response.status_code == 200
    assert response.json()["status"] == "not_collected"


def test_holder_snapshot_is_authenticated_data_only(settings):
    client = TestClient(create_app(settings))
    assert client.get("/api/crypto/assets/solana:token/holders/latest").status_code == 401
    client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    response = client.get("/api/crypto/assets/solana:token/holders/latest")
    assert response.status_code == 200
    assert response.json()["data_only"] is True
    assert response.json()["eval_allowed"] is False


def test_security_coverage_is_explicit_when_provider_is_disabled(settings):
    client = TestClient(create_app(settings))
    assert client.get("/api/crypto/security/coverage").status_code == 401
    client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    response = client.get("/api/crypto/security/coverage")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "provider_disabled"
    assert body["unknown_security_eval_allowed"] is False


def test_meme_factors_use_point_in_time_security_and_holder_snapshots(settings):
    market = DexMarketStore(settings.db_path)
    security = DexSecurityStore(settings.db_path)
    for index, (minute, price) in enumerate((("00:00", 0.10), ("00:05", 0.12), ("00:10", 0.15))):
        market.save_pair(DexPairSnapshot(
            chain_id="solana",
            dex_id="raydium",
            pair_address=f"pool-{index}",
            base_contract="token1",
            quote_contract="usdc",
            base_symbol="MOON",
            quote_symbol="USDC",
            price_usd=price,
            liquidity_usd=100_000 + index * 10_000,
            volume_5m_usd=10_000 + index * 5_000,
            buys_5m=40 + index * 10,
            sells_5m=20,
            pair_created_at="2026-08-22T00:00:00+00:00",
            fetched_at=f"2026-08-22T{minute}:00+00:00",
        ))
    unknown = TokenSecurityInput("solana:token1", "solana", "goplus", "unavailable")
    security.save_security(unknown, assess_token_security(unknown), source_time="2026-08-22T00:05:00+00:00")
    passed = TokenSecurityInput(
        "solana:token1", "solana", "goplus", "live", honeypot=False,
        sell_enabled=True, buy_tax=0.01, sell_tax=0.01,
        blacklist=False, lp_locked=True, holder_count=1000,
        top10_concentration=0.30,
    )
    security.save_security(passed, assess_token_security(passed), source_time="2026-08-22T00:10:00+00:00")

    from kquant_crypto.db.migrations import connect
    with connect(settings.db_path) as conn:
        saved_times = [row[0] for row in conn.execute(
            "SELECT d.source_time FROM crypto_dex_market_snapshots d JOIN crypto_liquidity_pools p ON p.pool_id=d.pool_id WHERE p.base_asset_id=? ORDER BY d.source_time",
            ("solana:token1",),
        )]
    assert saved_times == ["2026-08-22T00:00:00+00:00", "2026-08-22T00:05:00+00:00", "2026-08-22T00:10:00+00:00"]

    client = TestClient(create_app(settings))
    client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    past = client.get("/api/crypto/assets/solana:token1/meme-factors?as_of=2026-08-22T00:05:00%2B00:00")
    assert past.status_code == 200
    assert "meme_security_pass" in past.json()["missing_factor_ids"]
    current = client.get("/api/crypto/assets/solana:token1/meme-factors?as_of=2026-08-22T00:15:00%2B00:00")
    assert current.status_code == 200
    assert "meme_security_pass" not in current.json()["missing_factor_ids"]


def test_trade_plan_is_projected_into_eval_gated_instruction(settings):
    client = TestClient(create_app(settings))
    client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    response = client.post("/api/crypto/trade-plans", json={
        "plan_id": "plan_dashboard_instruction",
        "asset_id": "cex:binance:spot:SOLUSDT",
        "symbol": "SOLUSDT",
        "asset_type": "cex_spot",
        "strategy_version": "crypto_early_v1.0.0",
        "identity_status": "known",
        "security_status": "unknown",
        "data_quality_status": "live",
        "liquidity_status": "pass",
        "market_regime": "RISK_ON",
        "model_status": "passed",
        "factor_snapshot_hash": "factor-1",
        "entry_zone": [100, 101],
        "stop_zone": [96, 97],
        "target_zone": [110, 112],
        "risk_reward": 2.5,
        "valid_until": "2099-01-01T00:00:00+00:00",
        "invalid_conditions": ["close_below_stop"],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["evaluation"]["decision"] == "REJECTED"
    assert body["instruction"]["state"] == "INVALIDATED"
    assert client.get("/api/crypto/instructions/current").status_code == 200
    assert client.get("/api/runtime/supervisor-status").json()["order_submission"] is False


def test_advisory_endpoint_is_non_authoritative_and_audited(settings):
    client = TestClient(create_app(settings))
    client.post("/api/auth/login", json={"email": settings.login_email, "password": "correct horse battery staple"})
    response = client.post("/api/crypto/trade-plans", json={
        "plan_id": "plan_dashboard_advisory",
        "asset_id": "cex:binance:spot:SOLUSDT",
        "symbol": "SOLUSDT",
        "asset_type": "cex_spot",
        "strategy_version": "crypto_early_v1.0.0",
        "identity_status": "known",
        "security_status": "unknown",
        "data_quality_status": "live",
        "liquidity_status": "pass",
        "market_regime": "RISK_ON",
        "model_status": "passed",
        "factor_snapshot_hash": "factor-1",
        "entry_zone": [100, 101],
        "stop_zone": [96, 97],
        "target_zone": [110, 112],
        "risk_reward": 2.5,
        "valid_until": "2099-01-01T00:00:00+00:00",
        "invalid_conditions": ["close_below_stop"],
    })
    evaluation = response.json()["evaluation"]
    reviewed = client.post(
        f"/api/crypto/evaluations/{evaluation['evaluation_id']}/advisory",
        json={"factor_ids": [], "summary": "explain only", "decision": "PAPER_REVIEW"},
    )
    assert reviewed.status_code == 200
    body = reviewed.json()
    assert body["decision"] == evaluation["decision"]
    assert body["allowed_paper"] == evaluation["allowed_paper"] is False
    assert body["llm_advisory"]["status"] == "rejected"
    assert client.get(f"/api/crypto/evaluations/{evaluation['evaluation_id']}/advisories").json()["items"]
