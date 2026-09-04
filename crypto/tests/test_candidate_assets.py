from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from kquant_crypto.candidate_market import BinanceCandidateMarketVerifier
from kquant_crypto.evaluation_agent import EvaluationAgent
from kquant_crypto.evaluation_models import TradePlanDraft
from kquant_crypto.evaluation_store import save_trade_plan
from kquant_crypto.execution_orchestrator import ExecutionOrchestrator
from kquant_crypto.hyperliquid_reference import HyperliquidPublicReference
from kquant_crypto.model_evidence import build_model_evidence_packet, latest_model_evidence_packet, save_model_evidence_packet
from kquant_crypto.universe import UniverseRegistry
from kquant_crypto.universe_catalog import configured_instruments


def _model_inputs(market_type: str = "spot", symbol: str = ""):
    special_features = {
        "PUMPUSDT": ["gap_risk", "volume_decay", "abnormal_volatility"],
        "HYPEUSDT": ["funding_stress", "oi_change", "basis_signal", "deleveraging_risk"],
    }
    return {
        "bayesian_posterior": {
            "evidence_status": "complete",
            "state_probabilities": {"BULL": 0.7},
            "feature_order": special_features.get(symbol, []),
        },
        "monte_carlo_result": {
            "status": "available",
            "sample_count": 300,
            "config": {"instrument_type": market_type, "paths": 5000},
        },
        "logistic_result": {"status": "validated", "probability": 0.63},
        "expected_return_quantiles": {"status": "validated", "p10": -0.03, "p50": 0.04, "p90": 0.18},
    }


def test_candidate_universe_preserves_market_identity_and_risk_caps(settings):
    snapshot = UniverseRegistry(settings.db_path).ensure_cex_snapshot(settings.core_symbols, root_dir=settings.root_dir)
    members = {item["instrument_id"]: item for item in snapshot["members"] if item.get("instrument_id")}
    assert members["binance:spot:ARBUSDT"]["risk_fraction_cap"] == 0.005
    assert members["binance:spot:PUMPUSDT"]["tier"] == "MEME"
    assert members["binance:perpetual:HYPEUSDT"]["market_type"] == "perpetual"
    assert "binance:spot:HYPEUSDT" not in members


def test_model_evidence_rejects_prelisting_and_market_mismatch(settings):
    values = _model_inputs(symbol="PUMPUSDT")
    with pytest.raises(ValueError, match="signal_precedes_instrument_listing"):
        build_model_evidence_packet(
            asset_id="asset:pump", symbol="PUMPUSDT", market_type="spot",
            strategy_version="crypto_spot_momentum_v2.0.0",
            signal_time="2025-09-10T00:00:00+00:00", available_at="2025-09-10T00:00:00+00:00",
            evidence_history_start="2025-09-10T00:00:00+00:00", calibration_status="passed",
            source_snapshot_ids=("snapshot_1",), **values,
        )
    with pytest.raises(ValueError, match="candidate_market_type_mismatch"):
        build_model_evidence_packet(
            asset_id="asset:hype", symbol="HYPEUSDT", market_type="spot",
            strategy_version="crypto_spot_momentum_v2.0.0",
            signal_time="2026-01-01T00:00:00+00:00", available_at="2026-01-01T00:00:00+00:00",
            evidence_history_start="2025-05-30T10:30:00+00:00", calibration_status="passed",
            source_snapshot_ids=("snapshot_1",), **values,
        )


def test_model_evidence_is_reproducible_persisted_and_fail_closed(settings):
    values = _model_inputs("perpetual", "HYPEUSDT")
    kwargs = dict(
        asset_id="asset:hype", symbol="HYPEUSDT", market_type="perpetual",
        strategy_version="crypto_perpetual_long_v2.0.0",
        signal_time="2026-09-01T00:00:00+00:00", available_at="2026-09-01T00:00:00+00:00",
        evidence_history_start="2025-05-30T10:30:00+00:00", calibration_status="passed",
        source_snapshot_ids=("market_1", "factor_1"), **values,
    )
    first = build_model_evidence_packet(**kwargs)
    second = build_model_evidence_packet(**kwargs)
    assert first.content_hash == second.content_hash
    assert first.promotion_status == "SHADOW_ELIGIBLE"
    save_model_evidence_packet(settings.db_path, first)
    stored = latest_model_evidence_packet(settings.db_path, "asset:hype", "perpetual")
    assert stored is not None and stored["content_hash"] == first.content_hash

    blocked = build_model_evidence_packet(**{**kwargs, "calibration_status": "not_trained"})
    assert blocked.promotion_status == "RESEARCH_ONLY"
    assert "calibration_gate_closed" in blocked.blockers


def test_candidate_specific_features_and_path_count_fail_closed():
    values = _model_inputs("perpetual", "HYPEUSDT")
    values["bayesian_posterior"]["feature_order"] = ["funding_stress"]
    values["monte_carlo_result"]["config"]["paths"] = 1000
    packet = build_model_evidence_packet(
        asset_id="asset:hype", symbol="HYPEUSDT", market_type="perpetual",
        strategy_version="crypto_perpetual_long_v2.0.0",
        signal_time="2026-09-01T00:00:00+00:00", available_at="2026-09-01T00:00:00+00:00",
        evidence_history_start="2025-05-30T10:30:00+00:00", calibration_status="passed",
        source_snapshot_ids=("market_1", "factor_1"), **values,
    )
    assert packet.promotion_status == "RESEARCH_ONLY"
    assert "asset_model_features_missing" in packet.blockers
    assert "monte_carlo_paths_insufficient" in packet.blockers


def test_evaluation_binds_only_persisted_candidate_evidence(settings):
    values = _model_inputs("perpetual", "HYPEUSDT")
    packet = build_model_evidence_packet(
        asset_id="asset:hype", symbol="HYPEUSDT", market_type="perpetual",
        strategy_version="crypto_perpetual_long_v2.0.0",
        signal_time="2026-09-01T00:00:00+00:00", available_at="2026-09-01T00:00:00+00:00",
        evidence_history_start="2025-05-30T10:30:00+00:00", calibration_status="passed",
        source_snapshot_ids=("market_1", "factor_1"), **values,
    )
    save_model_evidence_packet(settings.db_path, packet)
    now = datetime.now(UTC)
    plan = TradePlanDraft.from_mapping({
        "plan_id": "plan_hype_evidence",
        "asset_id": "asset:hype",
        "symbol": "HYPEUSDT",
        "asset_type": "cex_perpetual",
        "strategy_version": "crypto_perpetual_long_v2.0.0",
        "identity_status": "verified",
        "data_quality_status": "live",
        "security_status": "passed",
        "liquidity_status": "passed",
        "market_regime": "bull",
        "model_status": "passed",
        "entry_zone": [45.0],
        "stop_zone": [43.0],
        "target_zone": [49.0],
        "risk_reward": 2.0,
        "valid_until": (now + timedelta(hours=1)).isoformat(),
        "invalid_conditions": ["close below 43"],
        "payload": {"model_evidence_packet": packet.to_mapping()},
    })
    result = EvaluationAgent(settings.db_path).evaluate(plan)
    codes = {item["code"] for item in result.blockers}
    assert "model_evidence_integrity_failed" not in codes
    assert "model_evidence_not_persisted" not in codes


def test_candidate_market_verifier_checks_spot_and_perpetual_contracts(settings):
    def request_json(market_type, _path):
        wanted = "HYPEUSDT" if market_type == "perpetual" else "PUMPUSDT"
        return {"symbols": [{
            "symbol": wanted, "status": "TRADING",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.001"},
                {"filterType": "LOT_SIZE", "stepSize": "0.1", "minQty": "0.1"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
            ],
        }]}

    definitions = tuple(item for item in configured_instruments(settings.root_dir) if item.symbol in {"PUMPUSDT", "HYPEUSDT"})
    UniverseRegistry(settings.db_path).ensure_cex_snapshot(settings.core_symbols, root_dir=settings.root_dir)
    result = BinanceCandidateMarketVerifier(settings.db_path, request_json=request_json).verify(definitions)
    assert result["status"] == "available"
    assert all(item["tradable"] for item in result["items"])


def test_hyperliquid_reference_is_public_and_never_connects_wallet():
    payload = [
        {"universe": [{"name": "BTC"}, {"name": "HYPE"}]},
        [{"markPx": "1"}, {"markPx": "45", "oraclePx": "44.9", "funding": "0.0001", "openInterest": "100", "dayNtlVlm": "5000"}],
    ]
    result = HyperliquidPublicReference(request_json=lambda _: payload).hype_snapshot()
    assert result["status"] == "available"
    assert result["wallet_connected"] is False
    assert result["mark_price"] == "45"


class _Controller:
    def __init__(self, symbols):
        self.settings = SimpleNamespace(symbols=tuple(symbols), risk_per_trade_fraction=0.01)

    def execute_intent(self, intent, *, evaluation_decision):
        return {"intent": intent.as_dict(), "decision": evaluation_decision}


def test_candidate_execution_caps_risk_and_never_promotes_hype_to_spot(settings, monkeypatch):
    now = datetime.now(UTC)
    plan = TradePlanDraft.from_mapping({
        "plan_id": "plan_pump", "asset_id": "asset:pump", "symbol": "PUMPUSDT",
        "asset_type": "cex_spot", "strategy_version": "crypto_spot_momentum_v2.0.0",
        "entry_zone": [1.0], "stop_zone": [0.9], "target_zone": [1.2],
        "valid_until": (now + timedelta(hours=1)).isoformat(), "material_state_hash": "pump_state",
    })
    save_trade_plan(settings.db_path, plan)
    monkeypatch.setattr("kquant_crypto.execution_orchestrator.latest_validation_gate_for_unit", lambda *args, **kwargs: {"status": "PASS"})
    evaluation = {
        "evaluation_id": "eval_pump", "plan_id": plan.plan_id, "symbol": "PUMPUSDT",
        "strategy_version": plan.strategy_version, "decision": "SHADOW_ELIGIBLE",
        "allowed_shadow": True, "material_state_hash": "pump_state",
    }
    result = ExecutionOrchestrator(settings.db_path, _Controller(("PUMPUSDT",))).admit(evaluation, execute=False)
    assert result["status"] == "intent_created"
    assert result["intent"]["requested_risk_fraction"] == 0.0025
    assert result["intent"]["market_type"] == "spot"

    hype_plan = TradePlanDraft.from_mapping({**plan.to_mapping(), "plan_id": "plan_hype", "symbol": "HYPEUSDT"})
    save_trade_plan(settings.db_path, hype_plan)
    hype = ExecutionOrchestrator(settings.db_path, _Controller(("HYPEUSDT",))).admit({**evaluation, "plan_id": "plan_hype", "symbol": "HYPEUSDT"})
    assert hype["status"] == "blocked"
    assert "candidate_market_type_mismatch" in hype["blockers"]
