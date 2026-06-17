from __future__ import annotations

import time
from typing import Any

from btc_eth_15m.agent_harness.audit_log import AuditLogger
from btc_eth_15m.agent_harness.state_store import StateStore
from btc_eth_15m.agent_harness.tool_base import ToolBase, WRITE_HIGH_RISK


class ToolRegistry:
    def __init__(self, store: StateStore, audit: AuditLogger) -> None:
        self.store = store
        self.audit = audit
        self._tools: dict[str, ToolBase] = {}

    def register(self, tool: ToolBase) -> None:
        if not tool.name:
            raise ValueError("Tool name is required.")
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolBase:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "permission_level": tool.permission_level,
                "requires_approval": tool.requires_approval,
                "input_schema": tool.input_schema(),
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, input_data: dict[str, Any] | None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        tool = self.get(name)
        payload = input_data or {}
        run_context = context or {}
        task_id = run_context.get("task_id")
        if tool.requires_approval and not run_context.get("approval_granted"):
            if tool.permission_level == WRITE_HIGH_RISK:
                raise PermissionError(f"Tool requires approval: {tool.name}")
        tool.validate_input(payload)
        started = time.monotonic()
        self.audit.record(
            "tool.called",
            task_id=task_id,
            actor=run_context.get("actor", "agent"),
            message=f"Tool called: {tool.name}",
            tool_name=tool.name,
            input_summary=summarize(payload),
            risk_level=tool.permission_level,
            status="started",
        )
        try:
            result = tool.execute(payload, run_context)
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            self.store.record_tool_call(
                task_id=task_id,
                tool_name=tool.name,
                permission_level=tool.permission_level,
                input_summary=summarize(payload),
                output_summary={},
                status="failed",
                error_message=str(exc),
                duration_ms=duration_ms,
            )
            self.audit.record(
                "tool.failed",
                task_id=task_id,
                actor=run_context.get("actor", "agent"),
                message=f"Tool failed: {tool.name}",
                tool_name=tool.name,
                input_summary=summarize(payload),
                risk_level=tool.permission_level,
                status="failed",
                error_message=str(exc),
            )
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        self.store.record_tool_call(
            task_id=task_id,
            tool_name=tool.name,
            permission_level=tool.permission_level,
            input_summary=summarize(payload),
            output_summary=summarize(result),
            status="succeeded",
            duration_ms=duration_ms,
        )
        self.audit.record(
            "tool.succeeded",
            task_id=task_id,
            actor=run_context.get("actor", "agent"),
            message=f"Tool succeeded: {tool.name}",
            tool_name=tool.name,
            input_summary=summarize(payload),
            output_summary=summarize(result),
            risk_level=tool.permission_level,
            status="succeeded",
        )
        return result


def summarize(value: Any, *, max_text: int = 500) -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in {"api_key", "api_secret", "secret", "token", "password", "private_key"}:
                result[key] = "[REDACTED]"
            elif isinstance(item, (str, int, float, bool)) or item is None:
                text = str(item)
                result[key] = text[:max_text] if len(text) > max_text else item
            elif isinstance(item, list):
                result[key] = {"type": "list", "count": len(item)}
            elif isinstance(item, dict):
                result[key] = {"type": "object", "keys": sorted(item)[:20]}
            else:
                result[key] = str(type(item).__name__)
        return result
    if isinstance(value, list):
        return {"type": "list", "count": len(value)}
    return {"value": str(value)[:max_text]}
