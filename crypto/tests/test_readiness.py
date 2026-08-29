from kquant_crypto.readiness import evaluate_readiness


def _complete_inputs():
    return {
        "validation_gate": {"status": "PASS"},
        "coverage_gate": {
            "coverage_index_status": "complete",
            "continuous_collection_gate": {"status": "PASS"},
        },
        "evidence_coverage": {"status": "available", "categories": {"etf": {"status": "complete"}}},
        "staging": {"connection_status": "available", "migration_status": "migrated"},
        "shadow": {"status": "PASS", "observed_trading_days": 15},
        "backup": {"status": "available", "restore_verified": True},
        "raw_index_repair_required": False,
        "research_only": True,
        "order_submission": False,
    }


def test_readiness_requires_every_release_gate():
    result = evaluate_readiness(**_complete_inputs())

    assert result["status"] == "GO"
    assert result["failed_checks"] == []
    assert result["release_state"] == "SHADOW_ONLY"


def test_readiness_missing_evidence_and_shadow_is_no_go():
    values = _complete_inputs()
    values["evidence_coverage"] = {"status": "available", "categories": {"etf": {"status": "partial"}}}
    values["shadow"] = {"status": "NO_GO", "observed_trading_days": 0}

    result = evaluate_readiness(**values)

    assert result["status"] == "NO_GO"
    assert "external_evidence" in result["failed_checks"]
    assert "shadow_observation" in result["failed_checks"]
    assert result["research_only"] is True
    assert result["order_submission"] is False
