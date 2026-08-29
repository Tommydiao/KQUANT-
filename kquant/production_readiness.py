from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .forward_pilot import MINIMUM_COMPLETE_MARKET_DAYS, forward_pilot_summary, paper_simulation_summary
from .stock_store import connect
from .stock_quant_validation import latest_stock_quant_validation
from .strategy_freeze import strategy_freeze_status


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _latest_session(db_path: Path, strategy_version: str) -> str | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT session_id FROM forward_pilot_sessions WHERE strategy_version = ? ORDER BY created_at DESC LIMIT 1",
            (strategy_version,),
        ).fetchone()
    return str(row["session_id"]) if row else None


def _paper_for_session(db_path: Path, session_id: str) -> str | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT account_id FROM paper_simulation_accounts WHERE session_id = ?", (session_id,)).fetchone()
    return str(row["account_id"]) if row else None


def _stock_quant_evidence(
    db_path: Path,
    supplied: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(supplied or latest_stock_quant_validation(db_path) or {})
    run = dict(payload.get("run") or payload)
    summary = dict(run.get("summary") or {})
    checks = dict(summary.get("overall_gate_checks") or {})
    deployment_model = summary.get("deployment_model")
    deployment_status = str(summary.get("deployment_status") or "not_available")
    validation_gate = str(run.get("gate_status") or "not_available")
    all_checks_passed = bool(checks) and all(bool(value) for value in checks.values())
    current_contract_compatible = bool(run.get("current_contract_compatible"))
    return {
        "status": str(run.get("status") or payload.get("status") or "not_available"),
        "validation_run_id": run.get("run_id"),
        "validation_version": run.get("validation_version"),
        "dataset_contract_version": run.get("dataset_contract_version"),
        "current_contract_compatible": current_contract_compatible,
        "validation_gate": validation_gate,
        "dataset_integrity_status": run.get("dataset_integrity_status"),
        "deployment_model": deployment_model,
        "deployment_status": deployment_status,
        "deployment_blockers": list(summary.get("deployment_blockers") or []),
        "overall_gate_checks": checks,
        "passed": bool(
            validation_gate == "pass"
            and deployment_status == "eligible"
            and deployment_model
            and run.get("dataset_integrity_status") == "verified"
            and all_checks_passed
            and current_contract_compatible
        ),
    }


def evaluate_go_no_go(
    *,
    db_path: Path,
    strategy_version: str,
    historical_validation: dict[str, Any] | None = None,
    stock_quant_validation: dict[str, Any] | None = None,
    security_report: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate the published personal-production gates without relaxing failures."""

    validation = dict(historical_validation or {})
    historical = dict(validation.get("summary") or validation.get("historical_policy_replay") or {})
    stock_quant = _stock_quant_evidence(db_path, stock_quant_validation)
    freeze = strategy_freeze_status(db_path, strategy_version)
    resolved_session_id = session_id or _latest_session(db_path, strategy_version)
    forward = forward_pilot_summary(db_path, resolved_session_id) if resolved_session_id else None
    account_id = _paper_for_session(db_path, resolved_session_id) if resolved_session_id else None
    paper = paper_simulation_summary(db_path, account_id) if account_id else None
    security = dict(security_report or {})
    completed_forward = int((forward or {}).get("completed_outcome_count") or 0)
    forward_days = int((forward or {}).get("market_day_count") or 0)
    paper_average_r = _number((paper or {}).get("average_r"))
    gates = [
        ("frozen_strategy", bool(freeze and freeze.get("status") == "frozen"), "Strategy version is frozen with a validation manifest."),
        ("stock_quant_phase_five", bool(stock_quant["passed"]), "A verified sealed Stock Quant report must pass every Phase 5 evidence gate."),
        ("stock_quant_deployment_model", bool(stock_quant["deployment_model"] and stock_quant["deployment_status"] == "eligible"), "A validated model must be explicitly eligible for Shadow Observation."),
        ("forward_market_days", forward_days >= MINIMUM_COMPLETE_MARKET_DAYS, f"At least {MINIMUM_COMPLETE_MARKET_DAYS} complete forward observation days are required."),
        ("forward_traceability", bool((forward or {}).get("candidate_traceability_complete")), "Every forward candidate must be traceable."),
        ("forward_data_incidents", int((forward or {}).get("data_incident_count") or 0) == 0, "No material forward data incident is allowed."),
        ("paper_execution", bool(paper and int(paper.get("closed_position_count") or 0) > 0), "At least one completed simulated position must be recorded before execution comparison."),
        ("user_discipline", bool(validation.get("user_discipline_confirmed")), "Manual stop/size discipline must be reviewed and confirmed."),
        ("security_boundary", security.get("secrets_exposed") is False and security.get("order_submission_enabled") is False, "Secrets must remain private and no execution route may exist."),
    ]
    failed = [{"gate": key, "reason": reason} for key, passed, reason in gates if not passed]
    return {
        "strategy_version": strategy_version,
        "decision": "GO" if not failed else "NO_GO",
        "gates": [{"gate": key, "passed": passed, "reason": reason} for key, passed, reason in gates],
        "failed_gate_count": len(failed),
        "failed_gates": failed,
        "historical": {
            "legacy_descriptive_sample_count": int(historical.get("sample_count") or 0),
            "legacy_descriptive_average_r": _number(historical.get("average_r")),
            "legacy_descriptive_profit_factor": _number(historical.get("profit_factor")),
            "not_used_for_phase_five_gate": True,
        },
        "stock_quant": stock_quant,
        "forward": forward,
        "paper": paper,
        "paper_average_r": paper_average_r,
        "real_money_approval": False,
        "automatic_execution_allowed": False,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def manual_live_readiness_check(
    *,
    go_no_go: dict[str, Any],
    instrument_type: str,
    risk_per_trade_pct: float,
    manual_trades_today: int,
    data_clean: bool,
    hard_veto_active: bool,
    is_leveraged_etf: bool = False,
    is_option: bool = False,
) -> dict[str, Any]:
    """A checklist only; it has no broker operation and cannot place a trade."""

    checks = {
        "go_no_go_approved": go_no_go.get("decision") == "GO",
        "common_stock_or_unleveraged_etf": instrument_type in {"common_stock", "unleveraged_etf"} and not is_leveraged_etf,
        "not_option": not is_option,
        "risk_at_or_below_025pct": 0 < _number(risk_per_trade_pct) <= 0.25,
        "at_most_one_manual_trade_today": int(manual_trades_today) < 1,
        "data_clean": bool(data_clean),
        "hard_veto_clear": not bool(hard_veto_active),
        "manual_only": True,
    }
    blockers = [key for key, passed in checks.items() if not passed]
    return {
        "status": "ready_for_human_decision" if not blockers else "blocked",
        "checks": checks,
        "blockers": blockers,
        "broker_execution_present": False,
        "automatic_execution_allowed": False,
        "operator_must_place_any_trade_outside_kquant": True,
    }


def write_personal_production_launch_report(report: dict[str, Any], path: Path) -> dict[str, Any]:
    """Write the Day 84 review, including an explicit no-go when evidence is absent."""

    path.parent.mkdir(parents=True, exist_ok=True)
    forward = report.get("forward") or {}
    paper = report.get("paper") or {}
    lines = [
        "# KQUANT Personal Production Launch Report",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Strategy: `{report.get('strategy_version')}`",
        f"Decision: **{report.get('decision')}**",
        "",
        "## Required Answers",
        "",
        f"1. Is KQUANT stable? {'No blocking operational gate is recorded.' if report.get('decision') == 'GO' else 'Not yet proven for production; review failed gates.'}",
        f"2. Is data trustworthy? {'Only within the recorded clean forward days.' if int(forward.get('data_incident_count') or 0) == 0 else 'No; data incidents require investigation.'}",
        f"3. Is there out-of-sample positive expectancy? {'Yes, subject to the immutable Stock Quant validation report.' if bool((report.get('stock_quant') or {}).get('passed')) else 'Not established.'}",
        f"4. Did execution follow the plan? {'Review recorded paper positions.' if paper else 'No paper execution record is available.'}",
        "5. Did KQUANT reduce user mistakes? Not established until sufficient Decision Ledger evidence exists.",
        "6. Which losses are normal strategy losses? Use the Ledger error_owner classification.",
        "7. Which losses are user violations? Use the Ledger user_* classifications.",
        f"8. Continue small-capital operation? {'Only after all gates remain GO.' if report.get('decision') == 'GO' else 'No. Continue paper-observed work only.'}",
        "9. Increase size? No. Size expansion is outside this report and requires a later evidence review.",
        "10. Single most important next objective: close the highest-priority failed gate without changing a frozen strategy.",
        "",
        "## Gate Results",
        "",
    ]
    for gate in report.get("gates") or []:
        lines.append(f"- {'PASS' if gate.get('passed') else 'FAIL'} `{gate.get('gate')}`: {gate.get('reason')}")
    lines.extend([
        "",
        "KQUANT remains a read-only research and manual-decision tool. This report never enables broker access or automatic execution.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return {"path": str(path), "decision": report.get("decision"), "written": True}


def serialize_go_no_go(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=True, indent=2, default=str)
