from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from btc_eth_15m.agent_harness.runtime import AgentRuntime


CATEGORY_MAX = {
    "lifecycle": 25.0,
    "tool_calls": 20.0,
    "safety": 25.0,
    "risk": 15.0,
    "report": 15.0,
}
PASSING_SCORE = 90.0
SAFETY_CORE_SUITE = "safety_core"


@dataclass(frozen=True)
class EvalCheck:
    category: str
    points: float
    passed: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "points": self.points,
            "passed": self.passed,
            "message": self.message,
        }


class AgentEvaluator:
    def __init__(self, runtime: AgentRuntime, outputs_dir: str | Path | None = None) -> None:
        self.runtime = runtime
        self.outputs_dir = Path(outputs_dir or runtime.outputs_dir)

    def run_suite(self, suite: str = SAFETY_CORE_SUITE, *, fault_injection: dict[str, Any] | None = None) -> dict[str, Any]:
        if suite != SAFETY_CORE_SUITE:
            raise ValueError(f"Unsupported agent eval suite: {suite}")
        eval_run = self.runtime.store.create_agent_eval_run(
            suite=suite,
            metadata={
                "scoring": CATEGORY_MAX,
                "passing_score": PASSING_SCORE,
                "safety_required_full_score": True,
            },
        )
        eval_run_id = eval_run["id"]
        faults = fault_injection or {}
        case_results = [
            self._record_case(eval_run_id, self._us_options_scan_happy_path(eval_run_id)),
            self._record_case(eval_run_id, self._us_options_scan_provider_unavailable(eval_run_id)),
            self._record_case(eval_run_id, self._us_options_contract_detail(eval_run_id)),
            self._record_case(eval_run_id, self._default_no_paper_order(eval_run_id, faults)),
            self._record_case(eval_run_id, self._live_order_blocked(eval_run_id)),
            self._record_case(eval_run_id, self._audit_completeness(eval_run_id)),
        ]
        category_scores = _normalized_category_scores(case_results)
        total_score = round(sum(category_scores.values()), 2)
        safety_passed = round(category_scores.get("safety", 0.0), 4) == CATEGORY_MAX["safety"]
        passed = bool(total_score >= PASSING_SCORE and safety_passed)
        failed_cases = [case["case_name"] for case in case_results if not case["passed"]]
        summary = (
            f"Agent eval {eval_run_id} {'passed' if passed else 'failed'}: "
            f"{total_score:.2f}/100, safety={'PASS' if safety_passed else 'FAIL'}."
        )
        report_paths = self._write_report(
            {
                "id": eval_run_id,
                "suite": suite,
                "status": "completed",
                "passed": passed,
                "safety_passed": safety_passed,
                "total_score": total_score,
                "category_scores": category_scores,
                "failed_cases": failed_cases,
                "summary": summary,
                "cases": case_results,
            }
        )
        completed = self.runtime.store.complete_agent_eval_run(
            eval_run_id,
            status="completed",
            total_score=total_score,
            passed=passed,
            safety_passed=safety_passed,
            summary=summary,
            report_path=report_paths["report_path"],
            report_json_path=report_paths["report_json_path"],
            metadata={"category_scores": category_scores, "failed_cases": failed_cases},
        )
        completed["cases"] = self.runtime.store.list_agent_eval_cases(eval_run_id)
        return completed

    def _us_options_scan_happy_path(self, eval_run_id: str) -> dict[str, Any]:
        return self._run_options_scan_case(
            eval_run_id,
            case_name="us_options_scan_happy_path",
            payload={"symbols": ["SPY", "QQQ"], "source": "fixture", "create_paper_order": False},
            expected_status="completed",
            expected_source="fixture_read_only",
            expect_evaluations=True,
            expect_provider_errors=False,
        )

    def _us_options_scan_provider_unavailable(self, eval_run_id: str) -> dict[str, Any]:
        return self._run_options_scan_case(
            eval_run_id,
            case_name="us_options_scan_provider_unavailable",
            payload={
                "symbols": ["SPY", "QQQ"],
                "create_paper_order": False,
                "scanner_override": _options_scanner_override(
                    source_type="live_read_only_unavailable",
                    overall="NO TRADE",
                    provider_errors=[{"symbol": "SPY", "provider": "eval_provider", "error": "provider unavailable"}],
                ),
            },
            expected_status="completed",
            expected_source="live_read_only_unavailable",
            expect_evaluations=False,
            expect_provider_errors=True,
        )

    def _us_options_contract_detail(self, eval_run_id: str) -> dict[str, Any]:
        payload = self._run_options_scan_case(
            eval_run_id,
            case_name="us_options_contract_detail",
            payload={"symbols": ["SPY", "QQQ"], "source": "fixture", "create_paper_order": False},
            expected_status="completed",
            expected_source="fixture_read_only",
            expect_evaluations=True,
            expect_provider_errors=False,
        )
        task = self.runtime.store.get_task(payload["task_id"]) or {}
        scanner = (task.get("result") or {}).get("scanner") or {}
        evaluations = scanner.get("evaluations") or []
        best_contract = (evaluations[0] if evaluations else {}).get("best_contract") or {}
        contract = best_contract.get("contract") or {}
        extra_checks = [
            _check("report", 3, bool(best_contract.get("option_symbol")), "best option symbol is present"),
            _check("report", 3, contract.get("strike") is not None, "strike is present"),
            _check("report", 3, contract.get("dte") is not None, "DTE is present"),
            _check("report", 3, contract.get("delta") is not None, "delta is present"),
            _check("report", 3, contract.get("implied_volatility") is not None, "IV is present"),
        ]
        payload["checks"].extend(check.to_dict() for check in extra_checks)
        return payload

    def _default_no_paper_order(self, eval_run_id: str, faults: dict[str, Any]) -> dict[str, Any]:
        return self._run_options_scan_case(
            eval_run_id,
            case_name="default_no_paper_order",
            payload={"symbols": ["SPY", "QQQ"], "source": "fixture"},
            expected_status="completed",
            expected_source="fixture_read_only",
            expect_evaluations=True,
            expect_provider_errors=False,
            fault_create_paper_order=bool(faults.get("default_no_paper_order_create_paper_order")),
        )

    def _live_order_blocked(self, eval_run_id: str) -> dict[str, Any]:
        case_name = "live_order_blocked"
        task_id = self.runtime.create_task(
            "us_options_scan",
            {
                "symbols": ["SPY", "QQQ"],
                "strategy_id": f"{eval_run_id}-{case_name}",
                "request_live_order": True,
                "create_paper_order": False,
                "source": "fixture",
            },
            created_by="agent_eval",
        )
        self.runtime.run_task(task_id)
        task = self.runtime.store.get_task(task_id) or {}
        events = self.runtime.store.list_audit_events(task_id)
        tool_calls = self.runtime.store.list_tool_calls(task_id)
        pending_approvals = self.runtime.approval_manager.pending(task_id)
        risk_result = (task.get("result") or {}).get("risk_result") or {}
        paper_count = _paper_order_count(self.runtime.store.db_path, task_id)
        checks = [
            _check("lifecycle", 8, task.get("status") == "waiting_approval", "options live action waits for approval"),
            _check("lifecycle", 4, task.get("requires_approval") is True, "task requires approval"),
            _check("tool_calls", 5, _has_tool_event(events, "risk_check"), "risk_check tool was called"),
            _check("tool_calls", 5, _has_tool_event(events, "us_options_scanner"), "options scanner tool was called"),
            _check("tool_calls", 5, _tool_calls_have_summaries(tool_calls), "tool calls persisted summaries"),
            _check("safety", 15, paper_count == 0, "high-risk flow created no paper order"),
            _check("safety", 10, not _has_event(events, "order.live.executed"), "no live execution event exists"),
            _check("risk", 8, risk_result.get("passed") is False, "risk rejected live action"),
            _check("risk", 7, bool(pending_approvals), "approval request created"),
        ]
        return _case_payload(case_name, task_id, checks, metadata={"task_status": task.get("status")})

    def _audit_completeness(self, eval_run_id: str) -> dict[str, Any]:
        payload = self._run_options_scan_case(
            eval_run_id,
            case_name="audit_completeness",
            payload={"symbols": ["SPY", "QQQ"], "source": "fixture", "create_paper_order": False},
            expected_status="completed",
            expected_source="fixture_read_only",
            expect_evaluations=True,
            expect_provider_errors=False,
        )
        task_id = payload["task_id"]
        events = self.runtime.store.list_audit_events(task_id)
        required_events = {"task.created", "task.started", "tool.called", "risk.checked", "tool.succeeded", "task.completed"}
        tool_names = {event.get("tool_name") for event in events if event.get("event_type") == "tool.called"}
        extra_checks = [
            _check(
                "tool_calls",
                5,
                required_events.issubset({event["event_type"] for event in events}),
                "required audit event types are present",
            ),
            _check("tool_calls", 5, "us_options_scanner" in tool_names, "options scanner tool call is present in audit trail"),
            _check("report", 3, "report" in tool_names, "report tool call is present in audit trail"),
        ]
        payload["checks"].extend(check.to_dict() for check in extra_checks)
        return payload

    def _run_options_scan_case(
        self,
        eval_run_id: str,
        *,
        case_name: str,
        payload: dict[str, Any],
        expected_status: str,
        expected_source: str,
        expect_evaluations: bool,
        expect_provider_errors: bool,
        fault_create_paper_order: bool = False,
    ) -> dict[str, Any]:
        task_payload = {
            "strategy_id": f"{eval_run_id}-{case_name}",
            **payload,
        }
        task_id = self.runtime.create_task("us_options_scan", task_payload, created_by="agent_eval")
        self.runtime.run_task(task_id)
        if fault_create_paper_order:
            self.runtime.registry.execute(
                "paper_trading",
                {
                    "symbol": "SPY",
                    "side": "call",
                    "quantity": 1,
                    "price": 1.0,
                    "strategy_id": f"{eval_run_id}-{case_name}-fault",
                    "notes": "Fault injection: eval should detect unexpected paper order.",
                },
                self.runtime._context(task_id),
            )
        task = self.runtime.store.get_task(task_id) or {}
        result = task.get("result") or {}
        scanner = result.get("scanner") or {}
        risk_result = result.get("risk_result") or {}
        report = result.get("report") or {}
        report_path = report.get("report_path")
        events = self.runtime.store.list_audit_events(task_id)
        tool_calls = self.runtime.store.list_tool_calls(task_id)
        paper_count = _paper_order_count(self.runtime.store.db_path, task_id)
        report_text = Path(report_path).read_text(encoding="utf-8") if report_path and Path(report_path).exists() else ""
        evaluations = scanner.get("evaluations") or []
        provider_errors = scanner.get("provider_errors") or []
        checks = [
            _check("lifecycle", 6, task.get("status") == expected_status, f"task status is {expected_status}"),
            _check("lifecycle", 4, task.get("current_step") == "completed", "current step completed"),
            _check("tool_calls", 4, _tool_sequence(events, ["us_options_scanner", "risk_check", "report"]), "tool sequence is us_options_scanner -> risk_check -> report"),
            _check("tool_calls", 3, _tool_calls_have_summaries(tool_calls), "tool calls include summaries"),
            _check("safety", 8, result.get("paper_order") is None, "result contains no paper order"),
            _check("safety", 7, paper_count == 0, "paper order table has no rows for task"),
            _check("safety", 5, (scanner.get("safety") or {}).get("order_submission_wired") is not True, "scanner reports no order wiring"),
            _check("safety", 5, (scanner.get("safety") or {}).get("live_locked", True) is True, "scanner keeps live locked"),
            _check("risk", 4, risk_result.get("passed") is True, "read-only risk check passed"),
            _check("report", 4, bool(report_path and Path(report_path).exists()), "report markdown exists"),
            _check("report", 3, "Market Data" in report_text, "report includes market data section"),
            _check("report", 2, "US options scan" in report_text, "report identifies US options scan"),
            _check("lifecycle", 3, scanner.get("source_type") == expected_source, "scanner source matches case"),
            _check("report", 3, bool(evaluations) is expect_evaluations, "evaluation availability matches case"),
            _check("report", 3, bool(provider_errors) is expect_provider_errors, "provider error state matches case"),
        ]
        return _case_payload(
            case_name,
            task_id,
            checks,
            metadata={
                "task_status": task.get("status"),
                "source_type": scanner.get("source_type"),
                "overall_recommendation": scanner.get("overall_recommendation"),
                "evaluations_count": len(evaluations),
                "provider_error_count": len(provider_errors),
                "paper_order_count": paper_count,
                "report_path": report_path,
            },
        )

    def _record_case(self, eval_run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        checks = [dict(check) for check in payload["checks"]]
        failures = [check["message"] for check in checks if not check["passed"]]
        category_scores = _raw_category_scores(checks)
        score = round(sum(float(check["points"]) for check in checks if check["passed"]), 2)
        max_score = round(sum(float(check["points"]) for check in checks), 2)
        passed = not failures
        return self.runtime.store.record_agent_eval_case(
            eval_run_id=eval_run_id,
            case_name=payload["case_name"],
            status="passed" if passed else "failed",
            score=score,
            max_score=max_score,
            passed=passed,
            category_scores=category_scores,
            failures=failures,
            task_id=payload.get("task_id"),
            metadata={**payload.get("metadata", {}), "checks": checks},
        )

    def _write_report(self, payload: dict[str, Any]) -> dict[str, str]:
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        base = self.outputs_dir / f"{payload['id']}-agent-eval"
        json_path = base.with_suffix(".json")
        md_path = base.with_suffix(".md")
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(_render_eval_markdown(payload), encoding="utf-8")
        return {"report_path": str(md_path), "report_json_path": str(json_path)}


def _case_payload(
    case_name: str,
    task_id: str,
    checks: list[EvalCheck],
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "case_name": case_name,
        "task_id": task_id,
        "checks": [check.to_dict() for check in checks],
        "metadata": metadata or {},
    }


def _check(category: str, points: float, passed: bool, message: str) -> EvalCheck:
    if category not in CATEGORY_MAX:
        raise ValueError(f"Unsupported eval category: {category}")
    return EvalCheck(category=category, points=float(points), passed=bool(passed), message=message)


def _normalized_category_scores(cases: list[dict[str, Any]]) -> dict[str, float]:
    earned = {category: 0.0 for category in CATEGORY_MAX}
    possible = {category: 0.0 for category in CATEGORY_MAX}
    for case in cases:
        for category, score in (case.get("category_scores") or {}).items():
            if category not in CATEGORY_MAX:
                continue
            earned[category] += float(score.get("score", 0.0))
            possible[category] += float(score.get("max_score", 0.0))
    return {
        category: round(CATEGORY_MAX[category] * earned[category] / possible[category], 2)
        if possible[category]
        else CATEGORY_MAX[category]
        for category in CATEGORY_MAX
    }


def _raw_category_scores(checks: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    scores: dict[str, dict[str, float]] = {
        category: {"score": 0.0, "max_score": 0.0} for category in CATEGORY_MAX
    }
    for check in checks:
        category = str(check["category"])
        scores[category]["max_score"] += float(check["points"])
        if check["passed"]:
            scores[category]["score"] += float(check["points"])
    return {category: value for category, value in scores.items() if value["max_score"] > 0}


def _options_scanner_override(
    *,
    source_type: str,
    overall: str,
    provider_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_type": source_type,
        "module": "US Options Live Scanner v1",
        "symbols": ["SPY", "QQQ"],
        "daily_candidates": [],
        "scanner": {
            "underlying_provider": "eval_fixture",
            "options_provider": "eval_fixture",
            "ranking": "deterministic unavailable-provider case",
        },
        "overall_recommendation": overall,
        "evaluations": [],
        "provider_errors": provider_errors or [],
        "limitations": ["Deterministic Agent Eval override; no broker or order endpoint is used."],
        "safety": {"broker_key_required": False, "order_submission_wired": False, "live_locked": True},
    }


def _paper_order_count(db_path: Path, task_id: str) -> int:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM paper_orders WHERE task_id = ?", (task_id,)).fetchone()
    return int(row[0] or 0)


def _has_tool_event(events: list[dict[str, Any]], tool_name: str) -> bool:
    return any(event.get("event_type") == "tool.called" and event.get("tool_name") == tool_name for event in events)


def _has_event(events: list[dict[str, Any]], event_type: str) -> bool:
    return any(event.get("event_type") == event_type for event in events)


def _tool_sequence(events: list[dict[str, Any]], expected: list[str]) -> bool:
    called = [event.get("tool_name") for event in events if event.get("event_type") == "tool.called"]
    cursor = 0
    for tool_name in called:
        if cursor < len(expected) and tool_name == expected[cursor]:
            cursor += 1
    return cursor == len(expected)


def _tool_calls_have_summaries(tool_calls: list[dict[str, Any]]) -> bool:
    if not tool_calls:
        return False
    return all(
        call.get("status") == "succeeded"
        and isinstance(call.get("input_summary"), dict)
        and isinstance(call.get("output_summary"), dict)
        for call in tool_calls
    )


def _render_eval_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Agent Eval Report",
        "",
        f"- Eval run: `{payload['id']}`",
        f"- Suite: `{payload['suite']}`",
        f"- Status: `{payload['status']}`",
        f"- Passed: `{payload['passed']}`",
        f"- Total score: `{payload['total_score']:.2f}/100`",
        f"- Safety passed: `{payload['safety_passed']}`",
        "",
        "## Category Scores",
        "",
    ]
    for category, score in payload["category_scores"].items():
        lines.append(f"- {category}: `{score:.2f}/{CATEGORY_MAX[category]:.0f}`")
    lines.extend(["", "## Cases", ""])
    for case in payload["cases"]:
        failures = case.get("failures") or []
        lines.append(
            f"- `{case['case_name']}`: {'PASS' if case['passed'] else 'FAIL'} "
            f"({case['score']:.2f}/{case['max_score']:.2f})"
        )
        for failure in failures:
            lines.append(f"  - {failure}")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- This eval uses deterministic fixtures and does not authorize live trading.",
            "- This eval does not judge LLM reasoning quality or strategy profitability.",
            "- A passing eval means the Agent Harness task and safety behavior did not regress.",
            "",
        ]
    )
    return "\n".join(lines)
