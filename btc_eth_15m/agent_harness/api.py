from __future__ import annotations

from pathlib import Path
from typing import Any

from btc_eth_15m.agent_harness.eval import AgentEvaluator
from btc_eth_15m.agent_harness.runtime import default_runtime


def install_agent_routes(app: Any, *, db_path: str | Path, outputs_dir: str | Path) -> None:
    runtime = default_runtime(db_path, outputs_dir)

    @app.post("/api/agent/tasks")
    def create_agent_task(payload: dict[str, Any]) -> dict[str, Any]:
        task_id = runtime.create_task(
            str(payload.get("task_type") or payload.get("type") or "dry_run"),
            dict(payload.get("payload") or {}),
            priority=int(payload.get("priority", 0)),
            created_by=str(payload.get("created_by", "api")),
        )
        return runtime.get_task_status(task_id)

    @app.get("/api/agent/tasks")
    def list_agent_tasks(limit: int = 10, task_type: str | None = None) -> dict[str, Any]:
        return {"tasks": runtime.store.list_tasks(limit=limit, task_type=task_type)}

    @app.get("/api/agent/tasks/{task_id}")
    def get_agent_task(task_id: str) -> dict[str, Any]:
        return runtime.get_task_status(task_id)

    @app.get("/api/agent/tasks/{task_id}/events")
    def get_agent_task_events(task_id: str) -> dict[str, Any]:
        return {"task_id": task_id, "events": runtime.store.list_audit_events(task_id)}

    @app.post("/api/agent/evals/run")
    def run_agent_eval(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        evaluator = AgentEvaluator(runtime, outputs_dir)
        return {"eval": evaluator.run_suite(str(body.get("suite", "safety_core")))}

    @app.get("/api/agent/evals")
    def list_agent_evals(limit: int = 10, suite: str | None = None) -> dict[str, Any]:
        return {"evals": runtime.store.list_agent_eval_runs(limit=limit, suite=suite)}

    @app.get("/api/agent/evals/{eval_run_id}")
    def get_agent_eval(eval_run_id: str) -> dict[str, Any]:
        payload = runtime.store.get_agent_eval_run(eval_run_id, include_cases=True)
        if payload is None:
            return {"error": "agent_eval_not_found", "eval_run_id": eval_run_id}
        return {"eval": payload}

    @app.post("/api/agent/tasks/{task_id}/run")
    def run_agent_task(task_id: str) -> dict[str, Any]:
        runtime.run_task(task_id)
        return runtime.get_task_status(task_id)

    @app.post("/api/agent/tasks/{task_id}/pause")
    def pause_agent_task(task_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        runtime.pause_task(task_id, str((payload or {}).get("reason", "api pause")))
        return runtime.get_task_status(task_id)

    @app.post("/api/agent/tasks/{task_id}/resume")
    def resume_agent_task(task_id: str) -> dict[str, Any]:
        runtime.resume_task(task_id)
        return runtime.get_task_status(task_id)

    @app.post("/api/agent/tasks/{task_id}/cancel")
    def cancel_agent_task(task_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        runtime.cancel_task(task_id, str((payload or {}).get("reason", "api cancel")))
        return runtime.get_task_status(task_id)

    @app.get("/api/agent/approvals/pending")
    def get_pending_approvals() -> dict[str, Any]:
        return {"approvals": runtime.approval_manager.pending()}

    @app.get("/api/agent/approvals/{approval_id}")
    def get_approval(approval_id: str) -> dict[str, Any]:
        approval = runtime.approval_manager.get(approval_id)
        if approval is None:
            return {"error": "approval_not_found", "approval_id": approval_id}
        return approval

    @app.post("/api/agent/approvals/{approval_id}/approve")
    def approve(approval_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        return runtime.approval_manager.approve(
            approval_id,
            decided_by=str(body.get("decided_by", "api")),
            reason=str(body.get("reason", "")),
        )

    @app.post("/api/agent/approvals/{approval_id}/reject")
    def reject(approval_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        return runtime.approval_manager.reject(
            approval_id,
            decided_by=str(body.get("decided_by", "api")),
            reason=str(body.get("reason", "")),
        )

    @app.get("/api/agent/audit/events")
    def get_audit_events(task_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        return {"events": runtime.store.list_audit_events(task_id, limit=limit)}
