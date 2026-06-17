from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from btc_eth_15m.agent_harness.eval import AgentEvaluator
from btc_eth_15m.agent_harness.runtime import default_runtime


def add_agent_parser(subparsers: argparse._SubParsersAction) -> None:
    agent = subparsers.add_parser("agent", help="Run the Crypto AI Agent Harness MVP.")
    agent.add_argument("--db-path", default="work/market.sqlite3", help="SQLite DB path for harness state.")
    agent.add_argument("--outputs-dir", default="outputs", help="Directory for harness reports.")
    agent_sub = agent.add_subparsers(dest="agent_command", required=True)

    task = agent_sub.add_parser("task", help="Create and manage agent tasks.")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    create = task_sub.add_parser("create", help="Create an agent task.")
    create.add_argument("--type", required=True, dest="task_type")
    create.add_argument("--payload", default="{}", help="JSON string or path to JSON payload file.")
    create.add_argument("--priority", type=int, default=0)
    create.add_argument("--created-by", default="cli")
    run = task_sub.add_parser("run", help="Run an agent task.")
    run.add_argument("task_id")
    status = task_sub.add_parser("status", help="Show task status.")
    status.add_argument("task_id")
    events = task_sub.add_parser("events", help="Show task audit events.")
    events.add_argument("task_id")
    pause = task_sub.add_parser("pause", help="Pause a task.")
    pause.add_argument("task_id")
    pause.add_argument("--reason", default="manual pause")
    resume = task_sub.add_parser("resume", help="Resume a task.")
    resume.add_argument("task_id")
    cancel = task_sub.add_parser("cancel", help="Cancel a task.")
    cancel.add_argument("task_id")
    cancel.add_argument("--reason", default="manual cancel")

    eval_parser = agent_sub.add_parser("eval", help="Run and inspect Agent Harness evaluations.")
    eval_sub = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_run = eval_sub.add_parser("run", help="Run an agent eval suite.")
    eval_run.add_argument("--suite", default="safety_core")
    eval_list = eval_sub.add_parser("list", help="List recent agent eval runs.")
    eval_list.add_argument("--suite", default=None)
    eval_list.add_argument("--limit", type=int, default=10)
    eval_show = eval_sub.add_parser("show", help="Show one agent eval run.")
    eval_show.add_argument("eval_run_id")

    approvals = agent_sub.add_parser("approvals", help="Manage approval requests.")
    approvals_sub = approvals.add_subparsers(dest="approval_command", required=True)
    approvals_sub.add_parser("pending", help="List pending approvals.")
    approve = approvals_sub.add_parser("approve", help="Approve an approval request.")
    approve.add_argument("approval_id")
    approve.add_argument("--reason", default="")
    approve.add_argument("--decided-by", default="cli")
    reject = approvals_sub.add_parser("reject", help="Reject an approval request.")
    reject.add_argument("approval_id")
    reject.add_argument("--reason", default="")
    reject.add_argument("--decided-by", default="cli")


def run_agent_command(args: argparse.Namespace) -> int:
    runtime = default_runtime(args.db_path, args.outputs_dir)
    if args.agent_command == "task":
        return _run_task_command(runtime, args)
    if args.agent_command == "eval":
        return _run_eval_command(runtime, args)
    if args.agent_command == "approvals":
        return _run_approval_command(runtime, args)
    raise ValueError(f"Unsupported agent command: {args.agent_command}")


def _run_task_command(runtime: Any, args: argparse.Namespace) -> int:
    if args.task_command == "create":
        task_id = runtime.create_task(
            args.task_type,
            _payload(args.payload),
            priority=args.priority,
            created_by=args.created_by,
        )
        print(json.dumps({"task_id": task_id}, indent=2, ensure_ascii=False))
        return 0
    if args.task_command == "run":
        runtime.run_task(args.task_id)
        print(json.dumps(runtime.get_task_status(args.task_id), indent=2, ensure_ascii=False))
        return 0
    if args.task_command == "status":
        print(json.dumps(runtime.get_task_status(args.task_id), indent=2, ensure_ascii=False))
        return 0
    if args.task_command == "events":
        print(json.dumps(runtime.store.list_audit_events(args.task_id), indent=2, ensure_ascii=False))
        return 0
    if args.task_command == "pause":
        runtime.pause_task(args.task_id, args.reason)
        print(json.dumps(runtime.get_task_status(args.task_id), indent=2, ensure_ascii=False))
        return 0
    if args.task_command == "resume":
        runtime.resume_task(args.task_id)
        print(json.dumps(runtime.get_task_status(args.task_id), indent=2, ensure_ascii=False))
        return 0
    if args.task_command == "cancel":
        runtime.cancel_task(args.task_id, args.reason)
        print(json.dumps(runtime.get_task_status(args.task_id), indent=2, ensure_ascii=False))
        return 0
    raise ValueError(f"Unsupported task command: {args.task_command}")


def _run_eval_command(runtime: Any, args: argparse.Namespace) -> int:
    if args.eval_command == "run":
        evaluator = AgentEvaluator(runtime, runtime.outputs_dir)
        print(json.dumps(evaluator.run_suite(args.suite), indent=2, ensure_ascii=False))
        return 0
    if args.eval_command == "list":
        print(
            json.dumps(
                {"evals": runtime.store.list_agent_eval_runs(limit=args.limit, suite=args.suite)},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.eval_command == "show":
        payload = runtime.store.get_agent_eval_run(args.eval_run_id, include_cases=True)
        if payload is None:
            raise KeyError(f"Agent eval run was not found: {args.eval_run_id}")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    raise ValueError(f"Unsupported eval command: {args.eval_command}")


def _run_approval_command(runtime: Any, args: argparse.Namespace) -> int:
    if args.approval_command == "pending":
        print(json.dumps(runtime.approval_manager.pending(), indent=2, ensure_ascii=False))
        return 0
    if args.approval_command == "approve":
        print(
            json.dumps(
                runtime.approval_manager.approve(
                    args.approval_id,
                    decided_by=args.decided_by,
                    reason=args.reason,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.approval_command == "reject":
        print(
            json.dumps(
                runtime.approval_manager.reject(
                    args.approval_id,
                    decided_by=args.decided_by,
                    reason=args.reason,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    raise ValueError(f"Unsupported approval command: {args.approval_command}")


def _payload(value: str) -> dict[str, Any]:
    candidate = Path(value)
    if candidate.exists() and candidate.is_file():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(value)
