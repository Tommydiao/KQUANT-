from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .evaluation_models import EvaluationDecision, TradePlanDraft
from .evaluation_policy import evaluate_plan
from .evaluation_store import latest_evaluation_for_plan, save_evaluation, save_trade_plan
from .factor_registry import FactorRegistry
from .model_evidence import get_model_evidence_packet, verify_model_evidence_packet
from .model_registry import ModelArtifactRegistry


class EvaluationAgent:
    """Deterministic final reviewer for all crypto plan outputs."""

    def __init__(
        self,
        db_path: Path,
        registry: FactorRegistry | None = None,
        model_registry: ModelArtifactRegistry | None = None,
        additional_factor_ids: frozenset[str] | set[str] | tuple[str, ...] | None = None,
        allow_alert: bool = False,
        allow_paper: bool = False,
        allow_shadow: bool = False,
    ):
        self.db_path = db_path
        self.registry = registry or FactorRegistry(db_path)
        self.model_registry = model_registry or ModelArtifactRegistry(db_path)
        self.additional_factor_ids = frozenset(additional_factor_ids or ())
        # Explicit release gates remain closed by default.  A later evidence
        # gate may opt in to one downstream capability without changing EVAL.
        self.allow_alert = bool(allow_alert)
        self.allow_paper = bool(allow_paper)
        self.allow_shadow = bool(allow_shadow)

    def _bind_model_evidence(self, draft: TradePlanDraft) -> TradePlanDraft:
        """Copy immutable model metadata into the EVAL payload when bound.

        Candidate assets must reference a packet that already exists in the
        audit database.  The request payload is never trusted as proof of
        persistence; the canonical stored packet is reloaded and verified.
        """

        payload = dict(draft.payload)
        packet = payload.get("model_evidence_packet")
        if isinstance(packet, dict):
            packet_id = str(packet.get("packet_id") or "")
            stored = get_model_evidence_packet(self.db_path, packet_id) if packet_id else None
            if stored is None:
                payload["model_evidence_persisted"] = False
                payload["model_evidence_integrity_issues"] = ["packet_not_found"]
            else:
                valid, issues = verify_model_evidence_packet(stored)
                request_hash = str(packet.get("content_hash") or "")
                stored_hash = str(stored.get("content_hash") or "")
                if request_hash != stored_hash:
                    issues = tuple(dict.fromkeys((*issues, "request_packet_hash_mismatch")))
                    valid = False
                payload["model_evidence_persisted"] = valid
                payload["model_evidence_integrity_issues"] = list(issues)
                if valid:
                    payload["model_evidence_packet"] = stored

        model_id = draft.snapshot_bindings.get("model")
        if not model_id:
            return replace(draft, payload=payload)
        allowed, reasons, artifact = self.model_registry.evidence_gate(model_id)
        payload["model_id"] = model_id
        if artifact is None:
            payload["model_integrity_ok"] = False
            payload["model_evidence_reasons"] = reasons
        else:
            payload.update({
                "model_version": artifact["model_version"],
                "expected_model_version": artifact["model_version"],
                "model_hash": artifact["artifact_hash"],
                "expected_model_hash": artifact["artifact_hash"],
                "feature_order_hash": artifact["feature_order_hash"],
                "expected_feature_order_hash": artifact["feature_order_hash"],
                "test_partition_hash": artifact["test_partition_hash"],
                "expected_test_partition_hash": artifact["test_partition_hash"],
                "calibration_gate_passed": artifact["calibration_gate"] == "passed",
                "test_partition_locked": artifact["status"] in {"validated", "frozen"},
                "model_evidence_reasons": reasons,
            })
        return replace(draft, payload=payload, model_status=draft.model_status if allowed else "unavailable")

    def evaluate(self, draft: TradePlanDraft | dict[str, Any]) -> EvaluationDecision:
        normalized = draft if isinstance(draft, TradePlanDraft) else TradePlanDraft.from_mapping(draft)
        normalized = self._bind_model_evidence(normalized)
        previous = latest_evaluation_for_plan(self.db_path, normalized.plan_id)
        save_trade_plan(self.db_path, normalized)
        result = evaluate_plan(
            normalized,
            previous_decision=previous,
            registered_factor_ids=self.registry.ids | self.additional_factor_ids,
            allow_alert=self.allow_alert,
            allow_paper=self.allow_paper,
            allow_shadow=self.allow_shadow,
        )
        save_evaluation(self.db_path, result)
        return result

    def rerun(self, plan_id: str) -> EvaluationDecision:
        from .evaluation_store import get_trade_plan

        value = get_trade_plan(self.db_path, plan_id)
        if value is None:
            raise KeyError(plan_id)
        return self.evaluate(value)
