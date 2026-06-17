from __future__ import annotations

from typing import Any

from btc_eth_15m.agent_harness.state_store import StateStore


class AuditLogger:
    def __init__(self, store: StateStore) -> None:
        self.store = store

    def record(
        self,
        event_type: str,
        *,
        task_id: str | None = None,
        actor: str = "system",
        message: str = "",
        metadata: dict[str, Any] | None = None,
        tool_name: str | None = None,
        action: str | None = None,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        risk_level: str | None = None,
        status: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        return self.store.record_audit_event(
            task_id=task_id,
            event_type=event_type,
            actor=actor,
            message=message,
            metadata=metadata,
            tool_name=tool_name,
            action=action,
            input_summary=input_summary,
            output_summary=output_summary,
            risk_level=risk_level,
            status=status,
            error_message=error_message,
        )
