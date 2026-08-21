from __future__ import annotations

from pathlib import Path

import pytest

from kquant.forward_pilot import (
    activate_forward_pilot,
    enter_paper_position,
    exit_paper_position,
    initialize_paper_simulation,
    prepare_forward_pilot,
    record_forward_day,
    record_forward_outcome,
)
from kquant.strategy_freeze import freeze_strategy_for_forward_observation
from kquant.strategy_registry import definition_for_profile


def _eligible_stock_quant_validation(fingerprint: str = "validation-fingerprint") -> dict:
    return {
        "status": "materialized",
        "run": {
            "run_id": "sqv-pass",
            "content_hash": fingerprint,
            "validation_version": "stock_quant_validation_test",
            "gate_status": "pass",
            "dataset_integrity_status": "verified",
            "current_contract_compatible": True,
            "summary": {
                "deployment_status": "eligible",
                "deployment_model": "logistic",
                "deployment_blockers": [],
                "overall_gate_checks": {"phase_five": True},
            },
        },
    }


def _frozen_session(tmp_path: Path, monkeypatch) -> tuple[Path, str]:
    db = tmp_path / "pilot.sqlite3"
    definition = definition_for_profile("swing_long_v1", {"name": "swing_long_v1", "score": 88})
    monkeypatch.setattr(
        "kquant.forward_pilot.latest_stock_quant_validation",
        lambda _db_path: _eligible_stock_quant_validation(),
    )
    freeze_strategy_for_forward_observation(
        db_path=db,
        definition=definition,
        validation_audit={"reproducibility_fingerprint": "validation-fingerprint"},
        evidence_score=80,
    )
    session = prepare_forward_pilot(
        db_path=db, strategy_version=definition.strategy_version, universe_name="default",
        universe_snapshot_hash="universe-hash", start_date="2026-07-24",
    )
    return db, session["session"]["session_id"]


def test_forward_pilot_requires_frozen_strategy_and_preserves_candidates(tmp_path: Path, monkeypatch) -> None:
    blocked = prepare_forward_pilot(
        db_path=tmp_path / "blocked.sqlite3", strategy_version="swing_long_v1.1.0", universe_name="default",
        universe_snapshot_hash="hash", start_date="2026-07-24",
    )
    assert blocked["status"] == "blocked"
    db, session_id = _frozen_session(tmp_path, monkeypatch)
    activate_forward_pilot(db, session_id)
    summary = record_forward_day(
        db_path=db, session_id=session_id, market_date="2026-07-24", preflight={"status": "pass"},
        scan={"run_id": "run-1", "daily_candidates": {"buy_setups": [{"symbol": "NVDA", "rank": 1, "bucket": "BUY SETUP", "data_status": "clean", "plan": {"entry_high": 101}}], "watch": []}},
    )
    assert summary["candidate_count"] == 1
    candidate_id = summary["session"]["session_id"]
    with pytest.raises(ValueError):
        record_forward_outcome(db_path=db, candidate_id=candidate_id, outcome_status="target")


def test_paper_simulation_enforces_no_chasing_and_risk_limits(tmp_path: Path, monkeypatch) -> None:
    db, session_id = _frozen_session(tmp_path, monkeypatch)
    activate_forward_pilot(db, session_id)
    summary = record_forward_day(
        db_path=db, session_id=session_id, market_date="2026-07-24", preflight={"status": "pass"},
        scan={"run_id": "run-1", "daily_candidates": {"buy_setups": [{"symbol": "NVDA", "rank": 1, "bucket": "BUY SETUP", "data_status": "clean", "plan": {"entry_high": 101}}], "watch": []}},
    )
    with pytest.raises(ValueError):
        initialize_paper_simulation(db_path=db, session_id=session_id, initial_cash=10_000, risk_per_trade_pct=0.3)
    account = initialize_paper_simulation(db_path=db, session_id=session_id, initial_cash=10_000)
    candidate_id = summary["session"]["session_id"]
    with __import__("kquant.stock_store", fromlist=["connect"]).connect(db) as conn:
        candidate_id = conn.execute("SELECT candidate_id FROM forward_pilot_candidates").fetchone()["candidate_id"]
    with pytest.raises(ValueError):
        enter_paper_position(
            db_path=db, account_id=account["account"]["account_id"], candidate_id=candidate_id,
            entry_time="2026-07-24T14:30:00+00:00", entry_price=102, stop_price=98, target_price=110,
        )
    entered = enter_paper_position(
        db_path=db, account_id=account["account"]["account_id"], candidate_id=candidate_id,
        entry_time="2026-07-24T14:30:00+00:00", entry_price=100, stop_price=98, target_price=110,
    )
    position_id = entered["positions"][0]["position_id"]
    closed = exit_paper_position(
        db_path=db, account_id=account["account"]["account_id"], position_id=position_id,
        exit_time="2026-07-25T14:30:00+00:00", exit_price=104,
    )
    assert closed["closed_position_count"] == 1
    assert closed["simulated_only"] is True


def test_forward_pilot_blocks_generic_freeze_without_stock_quant_validation(tmp_path: Path) -> None:
    db = tmp_path / "generic-freeze.sqlite3"
    definition = definition_for_profile("swing_long_v1", {"name": "swing_long_v1", "score": 88})
    freeze_strategy_for_forward_observation(
        db_path=db,
        definition=definition,
        validation_audit={"reproducibility_fingerprint": "generic-validation"},
        evidence_score=80,
    )

    blocked = prepare_forward_pilot(
        db_path=db,
        strategy_version=definition.strategy_version,
        universe_name="default",
        universe_snapshot_hash="universe-hash",
        start_date="2026-07-24",
    )

    assert blocked["status"] == "blocked"
    assert blocked["shadow_start"]["code"] == "stock_quant_validation_not_passed"
