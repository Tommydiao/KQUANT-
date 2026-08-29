from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .evaluation_models import stable_hash
from .external_evidence import EvidenceCategory, evidence_bundle
from .research_contract import metadata_from_roll_input
from .roll_engine import CRYPTO_ROLL_STRATEGY_VERSION, RollDecision, RollInput, evaluate_roll


ROLL_FEATURE_PACKET_VERSION = "crypto_roll_feature_packet_v1.0.0"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class RollFeaturePacket:
    packet_id: str
    packet_version: str
    asset_id: str
    symbol: str
    strategy_version: str
    decision: dict[str, Any]
    payload: dict[str, Any]
    content_hash: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "packet_version": self.packet_version,
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "strategy_version": self.strategy_version,
            "decision": self.decision,
            "payload": self.payload,
            "content_hash": self.content_hash,
            "research_only": True,
            "eval_authority": "EVAL only",
        }


def build_roll_feature_packet(
    value: RollInput | Mapping[str, Any],
    *,
    decision: RollDecision | Mapping[str, Any] | None = None,
    bayesian: Mapping[str, Any] | None = None,
    monte_carlo: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
    validation: Mapping[str, Any] | None = None,
    model: Mapping[str, Any] | None = None,
    journal: Mapping[str, Any] | None = None,
) -> RollFeaturePacket:
    item = value if isinstance(value, RollInput) else RollInput.from_mapping(dict(value))
    result = decision if isinstance(decision, RollDecision) else evaluate_roll(item) if decision is None else dict(decision)
    decision_mapping = result.to_mapping() if isinstance(result, RollDecision) else dict(result)
    evidence_mapping = _mapping(evidence)
    evidence_items = _mapping(evidence_mapping.get("items"))
    missing_categories = list(evidence_mapping.get("missing_categories") or [])
    if not evidence_mapping:
        missing_categories = [category.value for category in EvidenceCategory]
    normalized_evidence = {
        "items": evidence_items,
        "missing_categories": sorted(set(str(item) for item in missing_categories)),
        "unknown_values_are_blocked": True,
        "not_available": "N/A",
    }
    lineage = metadata_from_roll_input({
        **item.to_mapping(),
        "strategy_version": CRYPTO_ROLL_STRATEGY_VERSION,
    })
    payload = {
        "packet_version": ROLL_FEATURE_PACKET_VERSION,
        "asset": {
            "asset_id": item.asset_id,
            "symbol": item.symbol,
            "asset_type": item.asset_type,
            "instrument_id": item.instrument_id,
        },
        "point_in_time": {
            "as_of_time": item.as_of_time,
            "data_cutoff_time": item.data_cutoff_time,
            "source_status": item.source_status,
            "coverage": item.coverage,
            "hard_veto": item.hard_veto,
            "source_snapshot_ids": list(item.source_snapshot_ids),
        },
        "research_metadata": lineage.to_mapping(),
        "roll": {
            "strategy_version": CRYPTO_ROLL_STRATEGY_VERSION,
            "realized_profit": item.realized_profit,
            "floating_pnl": item.floating_pnl,
            "current_exposure": item.current_exposure,
            "proposed_capital": item.proposed_capital,
            "probability_improvement": item.probability_improvement,
            "current_score": item.current_score,
            "rotation_score": item.rotation_score,
            "rotation_target": item.rotation_target,
        },
        "bayesian": _mapping(bayesian) or {"status": "N/A"},
        "monte_carlo": _mapping(monte_carlo) or {"status": "N/A"},
        "model": _mapping(model) or {"status": "N/A", "authority": "advisory_only"},
        "external_evidence": normalized_evidence,
        "validation": _mapping(validation) or {"status": "N/A"},
        "journal": _mapping(journal) or {"status": "N/A", "ledger": "separate_roll_ledger"},
        "missing_fields": list(item.missing_fields),
        "warnings": list(item.warnings),
        "allowed_llm_actions": ["rank", "explain", "question_risks", "scenario_summary"],
        "llm_authority": "advisory_only",
        "research_only": True,
    }
    content_hash = stable_hash({"decision": decision_mapping, "payload": payload})
    return RollFeaturePacket(
        packet_id=f"roll_packet_{content_hash[:20]}",
        packet_version=ROLL_FEATURE_PACKET_VERSION,
        asset_id=item.asset_id,
        symbol=item.symbol,
        strategy_version=CRYPTO_ROLL_STRATEGY_VERSION,
        decision=decision_mapping,
        payload=payload,
        content_hash=content_hash,
    )


def build_roll_feature_packet_from_db(
    db_path,
    value: RollInput | Mapping[str, Any],
    *,
    decision: RollDecision | Mapping[str, Any] | None = None,
    bayesian: Mapping[str, Any] | None = None,
    monte_carlo: Mapping[str, Any] | None = None,
    validation: Mapping[str, Any] | None = None,
    model: Mapping[str, Any] | None = None,
    journal: Mapping[str, Any] | None = None,
) -> RollFeaturePacket:
    item = value if isinstance(value, RollInput) else RollInput.from_mapping(dict(value))
    return build_roll_feature_packet(
        item,
        decision=decision,
        bayesian=bayesian,
        monte_carlo=monte_carlo,
        evidence=evidence_bundle(db_path, item.asset_id),
        validation=validation,
        model=model,
        journal=journal,
    )


__all__ = [
    "ROLL_FEATURE_PACKET_VERSION",
    "RollFeaturePacket",
    "build_roll_feature_packet",
    "build_roll_feature_packet_from_db",
]
