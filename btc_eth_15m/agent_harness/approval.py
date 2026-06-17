from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from btc_eth_15m.agent_harness.audit_log import AuditLogger
from btc_eth_15m.agent_harness.state_store import StateStore


class ApprovalManager:
    def __init__(self, store: StateStore, audit: AuditLogger) -> None:
        self.store = store
        self.audit = audit

    def create_request(
        self,
        *,
        task_id: str | None,
        approval_type: str,
        request_summary: str,
        risk_summary: str,
        payload: dict[str, Any],
        expires_in_seconds: int = 3600,
    ) -> dict[str, Any]:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)).isoformat()
        approval = self.store.create_approval_request(
            task_id=task_id,
            approval_type=approval_type,
            request_summary=request_summary,
            risk_summary=risk_summary,
            payload=payload,
            expires_at=expires_at,
        )
        self.audit.record(
            "approval.requested",
            task_id=task_id,
            actor="approval_manager",
            message=f"Approval requested: {approval_type}",
            action=approval_type,
            risk_level=payload.get("risk_level"),
            status="pending",
            metadata={"approval_id": approval["id"], "risk_summary": risk_summary},
        )
        return approval

    def get(self, approval_id: str) -> dict[str, Any] | None:
        approval = self.store.get_approval(approval_id)
        if approval and approval["status"] == "pending" and self._expired(approval):
            approval = self.expire(approval_id)
        return approval

    def pending(self, task_id: str | None = None) -> list[dict[str, Any]]:
        pending = []
        for approval in self.store.list_pending_approvals(task_id):
            if self._expired(approval):
                self.expire(approval["id"])
            else:
                pending.append(approval)
        return pending

    def approve(self, approval_id: str, *, decided_by: str = "cli", reason: str = "") -> dict[str, Any]:
        approval = self.store.decide_approval(
            approval_id,
            status="approved",
            decided_by=decided_by,
            reason=reason,
        )
        self.audit.record(
            "approval.approved",
            task_id=approval.get("task_id"),
            actor=decided_by,
            message="Approval approved.",
            action=approval.get("approval_type"),
            status="approved",
            metadata={"approval_id": approval_id, "reason": reason},
        )
        return approval

    def reject(self, approval_id: str, *, decided_by: str = "cli", reason: str = "") -> dict[str, Any]:
        approval = self.store.decide_approval(
            approval_id,
            status="rejected",
            decided_by=decided_by,
            reason=reason,
        )
        self.audit.record(
            "approval.rejected",
            task_id=approval.get("task_id"),
            actor=decided_by,
            message="Approval rejected.",
            action=approval.get("approval_type"),
            status="rejected",
            metadata={"approval_id": approval_id, "reason": reason},
        )
        return approval

    def expire(self, approval_id: str) -> dict[str, Any]:
        approval = self.store.decide_approval(
            approval_id,
            status="expired",
            decided_by="system",
            reason="Approval expired.",
        )
        self.audit.record(
            "approval.rejected",
            task_id=approval.get("task_id"),
            actor="approval_manager",
            message="Approval expired.",
            action=approval.get("approval_type"),
            status="expired",
            metadata={"approval_id": approval_id},
        )
        return approval

    @staticmethod
    def _expired(approval: dict[str, Any]) -> bool:
        expires_at = approval.get("expires_at")
        if not expires_at:
            return False
        try:
            parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= datetime.now(timezone.utc)
