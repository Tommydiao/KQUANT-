from __future__ import annotations

from pathlib import Path

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
