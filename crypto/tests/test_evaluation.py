from __future__ import annotations

from kquant_crypto.evaluation_agent import EvaluationAgent
from kquant_crypto.evaluation_models import TradePlanDraft
from kquant_crypto.evaluation_policy import evaluate_plan
from kquant_crypto.factor_registry import FactorRegistry
from kquant_crypto.llm_advisor import apply_advisory
from kquant_crypto.llm_advisor import list_advisory_reviews, save_advisory_review
from kquant_crypto.signal_agent import SetupStage, propose_signal
from kquant_crypto.trade_plan_agent import build_trade_plan_draft


def plan(**overrides):
    value = {
        "plan_id": "plan_rklb",
        "asset_id": "cex:binance:spot:solusdt",
        "symbol": "SOLUSDT",
        "asset_type": "cex_spot",
        "strategy_version": "crypto_early_v1.0.0",
        "identity_status": "known",
        "data_quality_status": "live",
        "security_status": "pass",
        "liquidity_status": "pass",
        "market_regime": "RISK_ON",
        "model_status": "passed",
        "factor_snapshot_hash": "factor-hash",
        "snapshot_bindings": {
            "market": "market-snap-1",
            "regime": "regime-snap-1",
            "factor": "factor-hash",
            "security": "security-snap-1",
            "liquidity": "liquidity-snap-1",
            "derivative": "derivative-snap-1",
            "signal": "signal-snap-1",
            "plan": "plan_rklb",
            "model": "model-snap-1",
            "universe": "universe-snap-1",
            "eval_policy": "crypto_eval_v1.0.2",
        },
        "factor_ids": [],
        "entry_zone": [100, 101],
        "stop_zone": [96, 97],
        "target_zone": [110, 112],
        "risk_reward": 2.5,
        "valid_until": "2099-01-01T00:00:00+00:00",
        "invalid_conditions": ["close_below_stop"],
        "requested_execution_class": "paper_only",
    }
    value.update(overrides)
    return value


def test_unknown_security_is_rejected():
    result = evaluate_plan(TradePlanDraft.from_mapping(plan(security_status="unknown")))
    assert result.decision == "REJECTED"
    assert result.allowed_paper is False
    assert result.blockers[0]["code"] == "security_snapshot_unknown"


def test_provider_availability_is_not_security_approval():
    result = evaluate_plan(TradePlanDraft.from_mapping(plan(security_status="live")))
    assert result.decision == "REJECTED"
    assert any(item["code"] == "security_blocked" for item in result.blockers)


def test_complete_foundation_plan_is_still_watch_only():
    result = evaluate_plan(TradePlanDraft.from_mapping(plan()))
    assert result.decision == "WATCH_ONLY"
    assert result.allowed_alert is False
    assert result.allowed_paper is False
    assert any(item["code"] == "foundation_gate_closed" for item in result.warnings)


def test_explicit_eval_release_flags_authorize_only_the_requested_downstream_path():
    draft = TradePlanDraft.from_mapping(plan(proposed_stage="BUY_REVIEW"))
    result = evaluate_plan(draft, allow_alert=True, allow_paper=True)
    assert result.decision == "PAPER_REVIEW"
    assert result.evaluation_status == "passed"
    assert result.allowed_alert is True
    assert result.allowed_paper is True
    assert result.allowed_shadow is False


def test_eval_release_flags_do_not_bypass_blockers():
    result = evaluate_plan(
        TradePlanDraft.from_mapping(plan(proposed_stage="BUY_REVIEW", security_status="unknown")),
        allow_alert=True,
        allow_paper=True,
        allow_shadow=True,
    )
    assert result.decision == "REJECTED"
    assert result.evaluation_status == "rejected"
    assert result.allowed_alert is False
    assert result.allowed_paper is False
    assert result.allowed_shadow is False


def test_missing_fields_cannot_be_promoted(settings):
    result = EvaluationAgent(settings.db_path).evaluate(plan(entry_zone=[]))
    assert result.decision in {"WATCH_ONLY", "REJECTED"}
    assert result.allowed_paper is False


def test_forming_candle_is_a_data_blocker():
    result = evaluate_plan(TradePlanDraft.from_mapping(plan(payload={"forming_candle": True})))
    assert result.decision == "WATCH_ONLY"
    assert any(item["code"] == "forming_candle_not_eligible" for item in result.blockers)


def test_llm_advisory_does_not_change_deterministic_decision():
    result = evaluate_plan(TradePlanDraft.from_mapping(plan())).to_mapping()
    reviewed = apply_advisory(result, {"factor_ids": [], "summary": "make it paper"}, set())
    assert reviewed["decision"] == result["decision"]
    assert reviewed["allowed_paper"] is False
    assert reviewed["allowed_paper"] == result["allowed_paper"]


def test_llm_unknown_factor_is_rejected_without_changing_result():
    result = evaluate_plan(TradePlanDraft.from_mapping(plan())).to_mapping()
    reviewed = apply_advisory(result, {"factor_ids": ["invented_factor"]}, set())
    assert reviewed["llm_advisory"]["status"] == "rejected"
    assert reviewed["decision"] == result["decision"]


def test_llm_cannot_submit_or_rewrite_a_trade_plan():
    result = evaluate_plan(TradePlanDraft.from_mapping(plan())).to_mapping()
    reviewed = apply_advisory(result, {"factor_ids": [], "entry_zone": [1, 2], "decision": "PAPER_REVIEW"}, set())
    assert reviewed["llm_advisory"]["status"] == "rejected"
    assert "forbidden_authority_field" in reviewed["llm_advisory"]["rejection_reasons"]
    assert reviewed["decision"] == result["decision"]


def test_llm_advisory_is_persisted_without_authority(settings):
    result = EvaluationAgent(settings.db_path).evaluate(plan()).to_mapping()
    reviewed = save_advisory_review(
        settings.db_path,
        result,
        {"factor_ids": [], "summary": "explain only"},
        set(),
    )
    assert reviewed["decision"] == result["decision"]
    assert reviewed["allowed_paper"] is False
    rows = list_advisory_reviews(settings.db_path, result["evaluation_id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "accepted"


def test_signal_and_trade_plan_are_reviewed_by_registered_eval(settings):
    registry = FactorRegistry(settings.db_path)
    signal = propose_signal(
        registry,
        asset_id="cex:binance:spot:solusdt",
        symbol="SOLUSDT",
        asset_type="cex_spot",
        strategy_version="crypto_early_v1.0.0",
        factor_values={"trend_ema_reclaim": 1.0, "trend_ema_slope": 1.0, "relative_strength_btc": 1.0},
        weights={"trend_ema_reclaim": 30.0, "trend_ema_slope": 30.0, "relative_strength_btc": 30.0},
        trigger_score=80.0,
        data_quality_status="live",
        security_status="pass",
        liquidity_status="pass",
        market_regime="RISK_ON",
        as_of_time="2026-08-22T00:00:00+00:00",
    )
    assert signal.stage == SetupStage.BUY_REVIEW.value
    draft = build_trade_plan_draft(
        signal,
        entry_zone=[100, 101],
        stop_zone=[96, 97],
        target_zone=[110, 112],
        risk_reward=2.5,
        source_snapshot_ids=["snap_market_1"],
        factor_snapshot_hash="factor-hash",
    )
    result = EvaluationAgent(settings.db_path).evaluate(draft)
    assert result.decision == "WATCH_ONLY"
    assert any(item["code"] == "snapshot_binding_incomplete" for item in result.blockers)
    assert result.allowed_alert is False
    assert result.allowed_paper is False

    import sqlite3

    with sqlite3.connect(settings.db_path) as conn:
        evidence_count = conn.execute(
            "SELECT COUNT(*) FROM crypto_evaluation_evidence WHERE evaluation_id=?",
            (result.evaluation_id,),
        ).fetchone()[0]
    assert evidence_count >= 1


def test_microstructure_and_model_integrity_blockers_are_explicit():
    result = evaluate_plan(TradePlanDraft.from_mapping(plan(payload={
        "bbo_valid": False,
        "spread_bps": 250,
        "funding_rate": 0.02,
        "estimated_price_impact_bps": 300,
        "model_version": "old",
        "expected_model_version": "new",
        "dataset_hash_mismatch": True,
    })))
    codes = {item["code"] for item in result.blockers}
    assert {"bbo_unavailable", "spread_too_wide", "funding_extreme", "price_impact_too_high", "model_version_mismatch", "dataset_integrity_failed"} <= codes
    assert result.allowed_paper is False


def test_dex_lp_and_tax_blockers_are_explicit():
    result = evaluate_plan(TradePlanDraft.from_mapping(plan(
        asset_type="dex_token",
        payload={"lp_status": "removed", "buy_tax": 0.2, "sell_tax": 0.2},
    )))
    codes = {item["code"] for item in result.blockers}
    assert {"lp_not_safe", "buy_tax_too_high", "sell_tax_too_high"} <= codes
