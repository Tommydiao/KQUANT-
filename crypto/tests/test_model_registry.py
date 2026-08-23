from __future__ import annotations

import pytest

from kquant_crypto.evaluation_agent import EvaluationAgent
from kquant_crypto.model_registry import ModelArtifact, ModelArtifactRegistry


def test_model_artifact_is_immutable_and_gate_is_fail_closed(settings):
    registry = ModelArtifactRegistry(settings.db_path)
    artifact = ModelArtifact.from_metadata(
        model_id="model_rules_v1",
        model_version="rules_v1.0.0",
        model_type="rules",
        dataset_version="dataset_v1",
        dataset_hash="dataset-hash",
        feature_order=["trend_ema_reclaim", "volume_acceleration"],
        test_partition_hash="test-hash",
    )
    saved = registry.register(artifact)
    assert saved["model_id"] == "model_rules_v1"
    allowed, reasons, _ = registry.evidence_gate("model_rules_v1")
    assert allowed is False
    assert {"model_artifact_not_frozen", "calibration_gate_closed"} == set(reasons)

    with pytest.raises(ValueError, match="immutable"):
        registry.register(ModelArtifact.from_metadata(
            model_id="model_rules_v1",
            model_version="rules_v1.0.1",
            model_type="rules",
            dataset_version="dataset_v1",
            dataset_hash="different-dataset",
            feature_order=["volume_acceleration"],
            test_partition_hash="different-test",
        ))


def test_eval_binds_registered_model_evidence_and_keeps_gate_closed(settings):
    registry = ModelArtifactRegistry(settings.db_path)
    registry.register(ModelArtifact.from_metadata(
        model_id="model_frozen",
        model_version="rules_v1.0.0",
        model_type="rules",
        dataset_version="dataset_v1",
        dataset_hash="dataset-hash",
        feature_order=["trend_ema_reclaim"],
        test_partition_hash="test-hash",
        calibration_gate="passed",
        status="frozen",
    ))
    result = EvaluationAgent(settings.db_path).evaluate({
        "plan_id": "plan_model_binding",
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
        "model_probability": 0.7,
        "model_id": "ignored_outside_binding",
        "factor_snapshot_hash": "factor-1",
        "snapshot_bindings": {"model": "model_frozen"},
    })
    assert result.decision == "REJECTED"
    assert not any(item["code"] == "model_hash_mismatch" for item in result.blockers)
