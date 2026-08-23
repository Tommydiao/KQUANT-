from __future__ import annotations

import pytest

from kquant_crypto.evaluation_agent import EvaluationAgent
import kquant_crypto.paper_store as paper_store
from kquant_crypto.paper_store import PaperGateError, create_paper_observation


def test_paper_observation_cannot_bypass_eval_gate(settings):
    result = EvaluationAgent(settings.db_path).evaluate({
        "plan_id": "plan_paper_gate",
        "asset_id": "cex:binance:spot:SOLUSDT",
        "symbol": "SOLUSDT",
        "asset_type": "cex_spot",
        "strategy_version": "crypto_early_v1.0.0",
        "identity_status": "known",
        "security_status": "pass",
        "data_quality_status": "live",
        "liquidity_status": "pass",
        "market_regime": "RISK_ON",
        "model_status": "passed",
        "factor_snapshot_hash": "factor-paper",
        "snapshot_bindings": {
            "market": "market-1", "regime": "regime-1", "factor": "factor-paper",
            "security": "security-1", "liquidity": "liquidity-1", "derivative": "derivative-1",
            "signal": "signal-1", "plan": "plan_paper_gate", "model": "model-1",
            "universe": "universe-1", "eval_policy": "crypto_eval_v1.0.2",
        },
        "entry_zone": [100, 101],
        "stop_zone": [96, 97],
        "target_zone": [110, 112],
        "risk_reward": 2.5,
        "valid_until": "2099-01-01T00:00:00+00:00",
        "invalid_conditions": ["close_below_stop"],
        "requested_execution_class": "paper_only",
    })
    assert result.allowed_paper is False
    with pytest.raises(PaperGateError, match="evaluation_paper_gate_closed"):
        create_paper_observation(settings.db_path, {
            "evaluation_id": result.evaluation_id,
            "plan_id": "plan_paper_gate",
            "asset_id": "cex:binance:spot:SOLUSDT",
            "asset_type": "cex_spot",
            "symbol": "SOLUSDT",
            "entry_price": 100,
            "units": 1,
            "risk_per_unit": 4,
            "entry_snapshot_id": "market-1",
        })


def test_paper_observation_must_match_eval_identity_and_snapshot(settings, monkeypatch):
    evaluation = {
        "evaluation_id": "eva-approved",
        "decision": "PAPER_REVIEW",
        "allowed_paper": True,
        "plan_id": "plan-approved",
        "asset_id": "solana:token",
        "asset_type": "dex_meme",
        "symbol": "MOON",
        "source_snapshot_ids": ["pool-snapshot-1"],
        "snapshot_bindings": {"liquidity": "pool-snapshot-1"},
    }
    monkeypatch.setattr(paper_store, "_evaluation", lambda _db_path, _evaluation_id: evaluation)
    base = {
        "evaluation_id": "eva-approved",
        "plan_id": "plan-approved",
        "asset_id": "solana:token",
        "asset_type": "dex_meme",
        "symbol": "MOON",
        "entry_price": 1.0,
        "units": 10,
        "risk_per_unit": 0.1,
        "entry_snapshot_id": "pool-snapshot-1",
    }
    with pytest.raises(PaperGateError, match="paper_payload_evaluation_mismatch"):
        create_paper_observation(settings.db_path, {**base, "symbol": "FAKE"})
    with pytest.raises(PaperGateError, match="entry_snapshot_not_bound_to_evaluation"):
        create_paper_observation(settings.db_path, {**base, "entry_snapshot_id": "other-snapshot"})
