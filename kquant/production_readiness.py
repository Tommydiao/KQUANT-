from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .forward_pilot import forward_pilot_summary, paper_simulation_summary
from .stock_store import connect
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


def evaluate_go_no_go(
    *,
    db_path: Path,
    strategy_version: str,
    historical_validation: dict[str, Any] | None = None,
    security_report: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate the published personal-production gates without relaxing failures."""

    validation = dict(historical_validation or {})
    historical = dict(validation.get("summary") or validation.get("historical_policy_replay") or {})
    freeze = strategy_freeze_status(db_path, strategy_version)
    resolved_session_id = session_id or _latest_session(db_path, strategy_version)
    forward = forward_pilot_summary(db_path, resolved_session_id) if resolved_session_id else None
    account_id = _paper_for_session(db_path, resolved_session_id) if resolved_session_id else None
    paper = paper_simulation_summary(db_path, account_id) if account_id else None
    security = dict(security_report or {})
    sample_count = int(historical.get("sample_count") or 0)
    average_r = _number(historical.get("average_r"))
    profit_factor = _number(historical.get("profit_factor"))
    completed_forward = int((forward or {}).get("completed_outcome_count") or 0)
    forward_days = int((forward or {}).get("market_day_count") or 0)
    paper_average_r = _number((paper or {}).get("average_r"))
    gates = [
        ("frozen_strategy", bool(freeze and freeze.get("status") == "frozen"), "Strategy version is frozen with a validation manifest."),
        ("historical_sample_count", sample_count >= 100, "At least 100 completed historical samples are required."),
        ("out_of_sample_average_r", average_r > 0, "Historical/out-of-sample average R must be positive."),
        ("profit_factor", profit_factor > 1, "Historical/out-of-sample Profit Factor must exceed 1."),
        ("conservative_costs", bool(validation.get("conservative_costs_positive")), "Conservative execution-cost result must remain positive."),
        ("forward_market_days", forward_days >= 15, "At least 15 complete forward observation or simulation days are required."),
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
        "historical": {"sample_count": sample_count, "average_r": average_r, "profit_factor": profit_factor},
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
        f"3. Is there out-of-sample positive expectancy? {'Yes, subject to the frozen validation report.' if _number(report.get('historical', {}).get('average_r')) > 0 else 'Not established.'}",
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
