from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


TASK_STATUSES = {
    "created",
    "queued",
    "running",
    "waiting_approval",
    "paused",
    "completed",
    "failed",
    "cancelled",
}

APPROVAL_STATUSES = {"pending", "approved", "rejected", "expired"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def json_loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


class StateStore:
    def __init__(self, db_path: str | Path = "work/market.sqlite3") -> None:
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        self.ensure_schema(connection)
        return connection

    def ensure_schema(self, connection: sqlite3.Connection | None = None) -> None:
        owns_connection = connection is None
        if connection is None:
            connection = sqlite3.connect(self.db_path, timeout=10)
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_message TEXT,
                    created_by TEXT NOT NULL DEFAULT 'system',
                    current_step TEXT,
                    requires_approval INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    created_at TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    permission_level TEXT NOT NULL,
                    input_summary TEXT NOT NULL,
                    output_summary TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    duration_ms INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_checks (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    created_at TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    rules_checked_json TEXT NOT NULL,
                    violations_json TEXT NOT NULL,
                    recommendation TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_requests (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    approval_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_summary TEXT NOT NULL,
                    risk_summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    decision_reason TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    message TEXT NOT NULL,
                    tool_name TEXT,
                    action TEXT,
                    input_summary TEXT,
                    output_summary TEXT,
                    risk_level TEXT,
                    status TEXT,
                    error_message TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_orders (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    status TEXT NOT NULL,
                    strategy_id TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS backtest_results (
                    id TEXT PRIMARY KEY,
                    strategy_id TEXT,
                    task_id TEXT,
                    created_at TEXT NOT NULL,
                    symbol TEXT,
                    timeframe TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    metrics_json TEXT NOT NULL,
                    summary TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS strategies (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    notes TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_eval_runs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    suite TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_score REAL NOT NULL DEFAULT 0,
                    passed INTEGER NOT NULL DEFAULT 0,
                    safety_passed INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '',
                    report_path TEXT,
                    report_json_path TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_eval_cases (
                    id TEXT PRIMARY KEY,
                    eval_run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    case_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score REAL NOT NULL,
                    max_score REAL NOT NULL,
                    passed INTEGER NOT NULL,
                    category_scores_json TEXT NOT NULL,
                    failures_json TEXT NOT NULL,
                    task_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.commit()
        finally:
            if owns_connection:
                connection.close()

    def create_task(
        self,
        task_type: str,
        payload: dict[str, Any] | None = None,
        *,
        priority: int = 0,
        created_by: str = "cli",
    ) -> dict[str, Any]:
        task_id = "task-" + uuid4().hex[:16]
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_tasks (
                    id, created_at, updated_at, task_type, status, priority,
                    payload_json, result_json, created_by, current_step, requires_approval
                )
                VALUES (?, ?, ?, ?, 'created', ?, ?, '{}', ?, NULL, 0)
                """,
                (task_id, timestamp, timestamp, task_type, int(priority), json_dumps(payload or {}), created_by),
            )
            connection.commit()
        return self.get_task(task_id) or {}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_row(row) if row else None

    def list_tasks(self, limit: int = 20, task_type: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM agent_tasks"
        params: tuple[Any, ...] = ()
        if task_type:
            query += " WHERE task_type = ?"
            params = (task_type,)
        query += " ORDER BY updated_at DESC, created_at DESC, rowid DESC LIMIT ?"
        params += (int(limit),)
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._task_row(row) for row in rows]

    def create_agent_eval_run(self, *, suite: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        eval_run_id = "eval-" + uuid4().hex[:16]
        created_at = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_eval_runs (
                    id, created_at, suite, status, metadata_json
                )
                VALUES (?, ?, ?, 'running', ?)
                """,
                (eval_run_id, created_at, suite, json_dumps(metadata or {})),
            )
            connection.commit()
        return self.get_agent_eval_run(eval_run_id) or {}

    def complete_agent_eval_run(
        self,
        eval_run_id: str,
        *,
        status: str,
        total_score: float,
        passed: bool,
        safety_passed: bool,
        summary: str,
        report_path: str | None,
        report_json_path: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_agent_eval_run(eval_run_id)
        if not existing:
            raise KeyError(f"Agent eval run was not found: {eval_run_id}")
        next_metadata = dict(existing.get("metadata", {}))
        if metadata:
            next_metadata.update(metadata)
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE agent_eval_runs
                SET completed_at = ?,
                    status = ?,
                    total_score = ?,
                    passed = ?,
                    safety_passed = ?,
                    summary = ?,
                    report_path = ?,
                    report_json_path = ?,
                    metadata_json = ?
                WHERE id = ?
                """,
                (
                    now_iso(),
                    status,
                    float(total_score),
                    1 if passed else 0,
                    1 if safety_passed else 0,
                    summary,
                    report_path,
                    report_json_path,
                    json_dumps(next_metadata),
                    eval_run_id,
                ),
            )
            connection.commit()
        return self.get_agent_eval_run(eval_run_id) or {}

    def record_agent_eval_case(
        self,
        *,
        eval_run_id: str,
        case_name: str,
        status: str,
        score: float,
        max_score: float,
        passed: bool,
        category_scores: dict[str, Any],
        failures: list[str],
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        case_id = "eval-case-" + uuid4().hex[:16]
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_eval_cases (
                    id, eval_run_id, created_at, case_name, status, score,
                    max_score, passed, category_scores_json, failures_json,
                    task_id, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    eval_run_id,
                    now_iso(),
                    case_name,
                    status,
                    float(score),
                    float(max_score),
                    1 if passed else 0,
                    json_dumps(category_scores),
                    json_dumps(failures),
                    task_id,
                    json_dumps(metadata or {}),
                ),
            )
            connection.commit()
        return self.get_agent_eval_case(case_id) or {}

    def get_agent_eval_run(self, eval_run_id: str, *, include_cases: bool = False) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM agent_eval_runs WHERE id = ?", (eval_run_id,)).fetchone()
        if not row:
            return None
        payload = self._eval_run_row(row)
        if include_cases:
            payload["cases"] = self.list_agent_eval_cases(eval_run_id)
        return payload

    def list_agent_eval_runs(self, limit: int = 20, suite: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM agent_eval_runs"
        params: tuple[Any, ...] = ()
        if suite:
            query += " WHERE suite = ?"
            params = (suite,)
        query += " ORDER BY created_at DESC LIMIT ?"
        params += (int(limit),)
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._eval_run_row(row) for row in rows]

    def get_agent_eval_case(self, case_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM agent_eval_cases WHERE id = ?", (case_id,)).fetchone()
        return self._eval_case_row(row) if row else None

    def list_agent_eval_cases(self, eval_run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_eval_cases WHERE eval_run_id = ? ORDER BY created_at ASC",
                (eval_run_id,),
            ).fetchall()
        return [self._eval_case_row(row) for row in rows]

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        current_step: str | None = None,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
        requires_approval: bool | None = None,
    ) -> dict[str, Any]:
        existing = self.get_task(task_id)
        if not existing:
            raise KeyError(f"Task was not found: {task_id}")
        next_status = status or existing["status"]
        if next_status not in TASK_STATUSES:
            raise ValueError(f"Unsupported task status: {next_status}")
        values = {
            "updated_at": now_iso(),
            "status": next_status,
            "current_step": current_step if current_step is not None else existing.get("current_step"),
            "result_json": json_dumps(result if result is not None else existing.get("result", {})),
            "error_message": error_message,
            "requires_approval": int(
                existing.get("requires_approval") if requires_approval is None else bool(requires_approval)
            ),
            "id": task_id,
        }
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE agent_tasks
                SET updated_at = :updated_at,
                    status = :status,
                    current_step = :current_step,
                    result_json = :result_json,
                    error_message = :error_message,
                    requires_approval = :requires_approval
                WHERE id = :id
                """,
                values,
            )
            connection.commit()
        return self.get_task(task_id) or {}

    def record_tool_call(
        self,
        *,
        task_id: str | None,
        tool_name: str,
        permission_level: str,
        input_summary: dict[str, Any],
        output_summary: dict[str, Any],
        status: str,
        error_message: str | None = None,
        duration_ms: int = 0,
    ) -> dict[str, Any]:
        call_id = "tool-" + uuid4().hex[:16]
        created_at = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_calls (
                    id, task_id, created_at, tool_name, permission_level,
                    input_summary, output_summary, status, error_message, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    task_id,
                    created_at,
                    tool_name,
                    permission_level,
                    json_dumps(input_summary),
                    json_dumps(output_summary),
                    status,
                    error_message,
                    int(duration_ms),
                ),
            )
            connection.commit()
        return self.get_tool_call(call_id) or {}

    def get_tool_call(self, call_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tool_calls WHERE id = ?", (call_id,)).fetchone()
        return self._json_row(row, {"input_summary", "output_summary"}) if row else None

    def list_tool_calls(self, task_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM tool_calls"
        params: tuple[Any, ...] = ()
        if task_id:
            query += " WHERE task_id = ?"
            params = (task_id,)
        query += " ORDER BY created_at DESC LIMIT ?"
        params += (int(limit),)
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._json_row(row, {"input_summary", "output_summary"}) for row in rows]

    def record_risk_check(
        self,
        *,
        task_id: str | None,
        action_type: str,
        risk_level: str,
        passed: bool,
        rules_checked: list[dict[str, Any]],
        violations: list[str],
        recommendation: str,
    ) -> dict[str, Any]:
        risk_id = "risk-" + uuid4().hex[:16]
        created_at = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO risk_checks (
                    id, task_id, created_at, action_type, risk_level, passed,
                    rules_checked_json, violations_json, recommendation
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    risk_id,
                    task_id,
                    created_at,
                    action_type,
                    risk_level,
                    1 if passed else 0,
                    json_dumps(rules_checked),
                    json_dumps(violations),
                    recommendation,
                ),
            )
            connection.commit()
        return self.get_risk_check(risk_id) or {}

    def get_risk_check(self, risk_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM risk_checks WHERE id = ?", (risk_id,)).fetchone()
        if not row:
            return None
        payload = self._json_row(row, {"rules_checked_json", "violations_json"})
        payload["passed"] = bool(payload["passed"])
        payload["rules_checked"] = payload.pop("rules_checked_json")
        payload["violations"] = payload.pop("violations_json")
        return payload

    def create_approval_request(
        self,
        *,
        task_id: str | None,
        approval_type: str,
        request_summary: str,
        risk_summary: str,
        payload: dict[str, Any],
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        approval_id = "approval-" + uuid4().hex[:16]
        created_at = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO approval_requests (
                    id, task_id, created_at, expires_at, approval_type, status,
                    request_summary, risk_summary, payload_json
                )
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    approval_id,
                    task_id,
                    created_at,
                    expires_at,
                    approval_type,
                    request_summary,
                    risk_summary,
                    json_dumps(payload),
                ),
            )
            connection.commit()
        return self.get_approval(approval_id) or {}

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM approval_requests WHERE id = ?", (approval_id,)).fetchone()
        return self._approval_row(row) if row else None

    def list_pending_approvals(self, task_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM approval_requests WHERE status = 'pending'"
        params: tuple[Any, ...] = ()
        if task_id:
            query += " AND task_id = ?"
            params = (task_id,)
        query += " ORDER BY created_at ASC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._approval_row(row) for row in rows]

    def decide_approval(
        self,
        approval_id: str,
        *,
        status: str,
        decided_by: str,
        reason: str,
    ) -> dict[str, Any]:
        if status not in {"approved", "rejected", "expired"}:
            raise ValueError(f"Unsupported approval decision: {status}")
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE approval_requests
                SET status = ?, decided_at = ?, decided_by = ?, decision_reason = ?
                WHERE id = ?
                """,
                (status, now_iso(), decided_by, reason, approval_id),
            )
            connection.commit()
        approval = self.get_approval(approval_id)
        if not approval:
            raise KeyError(f"Approval was not found: {approval_id}")
        return approval

    def record_audit_event(
        self,
        *,
        task_id: str | None,
        event_type: str,
        actor: str,
        message: str,
        metadata: dict[str, Any] | None = None,
        tool_name: str | None = None,
        action: str | None = None,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        risk_level: str | None = None,
        status: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        event_id = "evt-" + uuid4().hex[:16]
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    id, task_id, created_at, event_type, actor, message,
                    tool_name, action, input_summary, output_summary, risk_level,
                    status, error_message, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    task_id,
                    now_iso(),
                    event_type,
                    actor,
                    message,
                    tool_name,
                    action,
                    json_dumps(input_summary) if input_summary is not None else None,
                    json_dumps(output_summary) if output_summary is not None else None,
                    risk_level,
                    status,
                    error_message,
                    json_dumps(metadata or {}),
                ),
            )
            connection.commit()
        return self.get_audit_event(event_id) or {}

    def get_audit_event(self, event_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM audit_events WHERE id = ?", (event_id,)).fetchone()
        return self._audit_row(row) if row else None

    def list_audit_events(self, task_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM audit_events"
        params: tuple[Any, ...] = ()
        if task_id:
            query += " WHERE task_id = ?"
            params = (task_id,)
        query += " ORDER BY created_at ASC LIMIT ?"
        params += (int(limit),)
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._audit_row(row) for row in rows]

    def create_paper_order(
        self,
        *,
        task_id: str | None,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float,
        status: str,
        strategy_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        order_id = "paper-order-" + uuid4().hex[:16]
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO paper_orders (
                    id, task_id, created_at, symbol, side, order_type, quantity,
                    price, status, strategy_id, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    task_id,
                    now_iso(),
                    symbol,
                    side,
                    order_type,
                    float(quantity),
                    float(price),
                    status,
                    strategy_id,
                    json_dumps(metadata or {}),
                ),
            )
            connection.commit()
        return self.get_paper_order(order_id) or {}

    def get_paper_order(self, order_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM paper_orders WHERE id = ?", (order_id,)).fetchone()
        return self._json_row(row, {"metadata_json"}) if row else None

    def create_backtest_result(
        self,
        *,
        task_id: str | None,
        strategy_id: str | None,
        symbol: str | None,
        timeframe: str | None,
        start_time: str | None,
        end_time: str | None,
        metrics: dict[str, Any],
        summary: str,
    ) -> dict[str, Any]:
        result_id = "backtest-" + uuid4().hex[:16]
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO backtest_results (
                    id, strategy_id, task_id, created_at, symbol, timeframe,
                    start_time, end_time, metrics_json, summary
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    strategy_id,
                    task_id,
                    now_iso(),
                    symbol,
                    timeframe,
                    start_time,
                    end_time,
                    json_dumps(metrics),
                    summary,
                ),
            )
            connection.commit()
        return self.get_backtest_result(result_id) or {}

    def get_backtest_result(self, result_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM backtest_results WHERE id = ?", (result_id,)).fetchone()
        return self._json_row(row, {"metrics_json"}) if row else None

    def has_backtest_result(self, strategy_id: str | None) -> bool:
        if not strategy_id:
            return False
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM backtest_results WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
        return bool(row and int(row[0] or 0) > 0)

    def has_paper_order(self, strategy_id: str | None) -> bool:
        if not strategy_id:
            return False
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM paper_orders WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
        return bool(row and int(row[0] or 0) > 0)

    def has_audit_events(self, task_id: str | None) -> bool:
        if not task_id:
            return False
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) FROM audit_events WHERE task_id = ?", (task_id,)).fetchone()
        return bool(row and int(row[0] or 0) > 0)

    def _task_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["payload"] = json_loads(payload.pop("payload_json"), {})
        payload["result"] = json_loads(payload.pop("result_json"), {})
        payload["requires_approval"] = bool(payload["requires_approval"])
        return payload

    def _approval_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = self._json_row(row, {"payload_json"})
        payload["payload"] = payload.pop("payload_json")
        return payload

    def _audit_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = self._json_row(row, {"metadata_json", "input_summary", "output_summary"})
        payload["metadata"] = payload.pop("metadata_json")
        return payload

    def _eval_run_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = self._json_row(row, {"metadata_json"})
        payload["metadata"] = payload.pop("metadata_json")
        payload["passed"] = bool(payload["passed"])
        payload["safety_passed"] = bool(payload["safety_passed"])
        return payload

    def _eval_case_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = self._json_row(row, {"category_scores_json", "failures_json", "metadata_json"})
        payload["category_scores"] = payload.pop("category_scores_json")
        payload["failures"] = payload.pop("failures_json")
        payload["metadata"] = payload.pop("metadata_json")
        payload["passed"] = bool(payload["passed"])
        return payload

    def _json_row(self, row: sqlite3.Row, json_fields: set[str]) -> dict[str, Any]:
        payload = dict(row)
        for field in json_fields:
            if field in payload:
                payload[field] = json_loads(payload[field], {})
        return payload
