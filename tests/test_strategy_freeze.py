from __future__ import annotations

import json
from pathlib import Path

from kquant import strategy_freeze
from kquant.strategy_freeze import freeze_strategy_for_forward_observation, strategy_freeze_status
from kquant.strategy_registry import definition_for_profile


def test_freeze_requires_evidence_then_stays_immutable(tmp_path: Path) -> None:
    definition = definition_for_profile("swing_long_v1", {"name": "swing_long_v1", "score": 88})
    blocked = freeze_strategy_for_forward_observation(
        db_path=tmp_path / "freeze.sqlite3",
        definition=definition,
        validation_audit={"reproducibility_fingerprint": "audit-1"},
        evidence_score=60,
    )
    assert blocked["status"] == "validation_not_passed"
    frozen = freeze_strategy_for_forward_observation(
        db_path=tmp_path / "freeze.sqlite3",
        definition=definition,
        validation_audit={"reproducibility_fingerprint": "audit-1"},
        evidence_score=80,
    )
    assert frozen["status"] == "frozen"
    assert strategy_freeze_status(tmp_path / "freeze.sqlite3", definition.strategy_version)["status"] == "frozen"
    assert freeze_strategy_for_forward_observation(
        db_path=tmp_path / "freeze.sqlite3",
        definition=definition,
        validation_audit={"reproducibility_fingerprint": "audit-1"},
        evidence_score=80,
    )["status"] == "already_frozen"


def _eligible_stock_quant_validation(fingerprint: str = "validation-content-hash") -> dict:
    return {
        "status": "materialized",
        "run": {
            "run_id": "sqv-pass",
            "content_hash": fingerprint,
            "validation_version": "stock_quant_validation_test",
            "gate_status": "pass",
            "dataset_integrity_status": "verified",
            "summary": {
                "deployment_status": "eligible",
                "deployment_model": "logistic",
                "deployment_blockers": [],
                "overall_gate_checks": {"phase_five": True},
            },
        },
    }


def test_stock_quant_freeze_requires_eligible_immutable_validation(tmp_path: Path) -> None:
    definition = definition_for_profile("swing_long_v1", {"name": "swing_long_v1", "score": 88})

    blocked = strategy_freeze.freeze_stock_quant_strategy_for_shadow(
        db_path=tmp_path / "stock-quant-freeze.sqlite3",
        definition=definition,
    )

    assert blocked["status"] == "validation_not_passed"
    assert strategy_freeze_status(tmp_path / "stock-quant-freeze.sqlite3", definition.strategy_version) is None


def test_stock_quant_freeze_links_manifest_to_validation(monkeypatch, tmp_path: Path) -> None:
    definition = definition_for_profile("swing_long_v1", {"name": "swing_long_v1", "score": 88})
    monkeypatch.setattr(
        "kquant.strategy_freeze.latest_stock_quant_validation",
        lambda _db_path: _eligible_stock_quant_validation(),
    )

    frozen = strategy_freeze.freeze_stock_quant_strategy_for_shadow(
        db_path=tmp_path / "stock-quant-freeze.sqlite3",
        definition=definition,
    )

    assert frozen["status"] == "frozen"
    manifest = json.loads(frozen["freeze"]["manifest_json"])
    assert manifest["validation_fingerprint"] == "validation-content-hash"
    assert manifest["validation_run_id"] == "sqv-pass"
    assert manifest["deployment_model"] == "logistic"
