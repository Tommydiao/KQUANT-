from __future__ import annotations

from pathlib import Path

from kquant.production_readiness import (
    evaluate_go_no_go,
    manual_live_readiness_check,
    write_personal_production_launch_report,
)


def test_go_no_go_stays_blocked_without_real_evidence(tmp_path: Path) -> None:
    report = evaluate_go_no_go(
        db_path=tmp_path / "readiness.sqlite3",
        strategy_version="swing_long_v1.1.0",
        historical_validation={"summary": {"sample_count": 0, "average_r": 0, "profit_factor": 0}},
        security_report={"secrets_exposed": False, "order_submission_enabled": False},
    )
    assert report["decision"] == "NO_GO"
    live = manual_live_readiness_check(
        go_no_go=report, instrument_type="common_stock", risk_per_trade_pct=0.25,
        manual_trades_today=0, data_clean=True, hard_veto_active=False,
    )
    assert live["status"] == "blocked"
    assert live["broker_execution_present"] is False


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
