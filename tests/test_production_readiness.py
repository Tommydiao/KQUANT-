from __future__ import annotations

from pathlib import Path

from kquant.production_readiness import (
    evaluate_go_no_go,
    manual_live_readiness_check,
    write_personal_production_launch_report,
)


def _passing_stock_quant_validation() -> dict:
    return {
        "status": "materialized",
        "run": {
            "run_id": "sqv-pass",
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


def test_go_no_go_stays_blocked_without_real_evidence(tmp_path: Path) -> None:
    report = evaluate_go_no_go(
        db_path=tmp_path / "readiness.sqlite3",
        strategy_version="swing_long_v1.1.0",
        historical_validation={"summary": {"sample_count": 0, "average_r": 0, "profit_factor": 0}},
        security_report={"secrets_exposed": False, "order_submission_enabled": False},
    )
    assert report["decision"] == "NO_GO"
    assert report["stock_quant"]["passed"] is False
    assert any(item["gate"] == "stock_quant_phase_five" and not item["passed"] for item in report["gates"])
    live = manual_live_readiness_check(
        go_no_go=report, instrument_type="common_stock", risk_per_trade_pct=0.25,
        manual_trades_today=0, data_clean=True, hard_veto_active=False,
    )
    assert live["status"] == "blocked"
    assert live["broker_execution_present"] is False


def test_go_no_go_uses_stock_quant_evidence_not_legacy_descriptive_statistics(tmp_path: Path) -> None:
    report = evaluate_go_no_go(
        db_path=tmp_path / "readiness.sqlite3",
        strategy_version="swing_long_v1.1.0",
        historical_validation={"summary": {"sample_count": 0, "average_r": -2, "profit_factor": 0}},
        stock_quant_validation=_passing_stock_quant_validation(),
        security_report={"secrets_exposed": False, "order_submission_enabled": False},
    )

    gates = {item["gate"]: item["passed"] for item in report["gates"]}
    assert gates["stock_quant_phase_five"] is True
    assert gates["stock_quant_deployment_model"] is True
    assert "historical_sample_count" not in gates
    assert report["historical"]["not_used_for_phase_five_gate"] is True
    assert report["decision"] == "NO_GO"


def test_go_no_go_rejects_a_validation_report_from_an_incompatible_contract(tmp_path: Path) -> None:
    legacy = _passing_stock_quant_validation()
    legacy["run"]["current_contract_compatible"] = False

    report = evaluate_go_no_go(
        db_path=tmp_path / "legacy-readiness.sqlite3",
        strategy_version="swing_long_v1.1.0",
        stock_quant_validation=legacy,
        security_report={"secrets_exposed": False, "order_submission_enabled": False},
    )

    assert report["stock_quant"]["passed"] is False
    assert report["stock_quant"]["current_contract_compatible"] is False


def test_launch_report_records_no_go_without_claiming_approval(tmp_path: Path) -> None:
    report = {
        "strategy_version": "swing_long_v1.1.0", "decision": "NO_GO", "generated_at": "2026-07-24T00:00:00+00:00",
        "historical": {"average_r": 0}, "forward": {}, "paper": {},
        "gates": [{"gate": "forward_market_days", "passed": False, "reason": "Need 15 days."}],
    }
    result = write_personal_production_launch_report(report, tmp_path / "personal_production_launch_report.md")
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "**NO_GO**" in text
    assert "automatic execution" in text.lower()
