from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .option_event_coverage import option_event_context
from .options_expression import option_chain, option_contract_snapshots, option_expiries
from .options_forward_paper import load_forward_policy
from .options_paper_engineering import evaluate_candidate
from .options_breakout_math import factor_funnel
from .options_research_features import content_hash, compute_option_feature_snapshot
from .options_research_scenarios import local_greeks_scenario_grid
from .options_research_workbench import DEFAULT_RESEARCH_DB, workbench_payload
from .options_review_r1 import review_r1_payload
from .stock_signals import api_stock_quote


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / "config" / "options_research_protocol_v0_1.json"
TOOL_VERSION = "options-signal-tools-v1.0.0"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _envelope(name: str, inputs: dict[str, Any], payload: dict[str, Any], *, started_at: str) -> dict[str, Any]:
    completed_at = _now()
    quality_flags = sorted(set(str(item) for item in payload.get("quality_flags", []) if item))
    material = {
        "tool": name,
        "version": TOOL_VERSION,
        "inputs": inputs,
        "payload": payload,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    return {
        "tool_run_id": f"tlr_{content_hash(material)[:24]}",
        "tool": name,
        "tool_version": TOOL_VERSION,
        "started_at": started_at,
        "completed_at": completed_at,
        "input_hash": content_hash(inputs),
        "output_hash": content_hash(payload),
        "quality_flags": quality_flags,
        "payload": payload,
        "read_only": True,
        "order_path": False,
    }


def get_market_snapshot(*, symbol: str, db_path: Path) -> dict[str, Any]:
    started = _now()
    quote = api_stock_quote(symbol, db_path=db_path)
    flags = []
    if quote.get("provider_status") != "available":
        flags.append("PROVIDER_NOT_AVAILABLE")
    if quote.get("source_bbo_time") is None:
        flags.append("SOURCE_BBO_TIME_UNKNOWN")
    return _envelope(
        "get_market_snapshot",
        {"symbol": symbol.upper()},
        {"snapshot": quote, "quality_flags": flags, "not_an_order_quote": True},
        started_at=started,
    )


def compute_registered_features(*, symbol: str, research_db: Path = DEFAULT_RESEARCH_DB) -> dict[str, Any]:
    started = _now()
    payload = workbench_payload(research_db)
    equity = [item for item in payload.get("equity_feature_snapshots", []) if str(item.get("entity_id") or "").upper() == symbol.upper()]
    option = [item for item in payload.get("option_feature_snapshots", []) if str(item.get("underlying_symbol") or item.get("symbol") or "").upper() == symbol.upper()]
    flags = [] if equity or option else ["NO_REGISTERED_FEATURE_SNAPSHOT_FOR_SYMBOL"]
    return _envelope(
        "compute_registered_features",
        {"symbol": symbol.upper(), "research_db": str(research_db)},
        {
            "feature_definitions": payload.get("feature_definitions", []),
            "equity_snapshots": equity,
            "option_snapshots": option,
            "quality_flags": flags,
            "point_in_time_only": True,
        },
        started_at=started,
    )


def evaluate_frozen_policy(*, symbol: str, right: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    started = _now()
    policy = load_forward_policy()
    normalized_right = right.upper()
    scope = policy["scope"]
    in_scope = symbol.upper() in policy["frozen_universe"] and normalized_right in scope["rights"]
    snapshot = {**(evidence or {}), "symbol": symbol.upper(), "right": normalized_right,
                "frozen_universe": policy["frozen_universe"]}
    evaluation = evaluate_candidate(snapshot, policy=policy)
    evaluation['factor_funnel'] = factor_funnel(snapshot)
    if snapshot.get("data_blockers") or any(snapshot.get(k) is None for k in ("compression_ratio", "opening_participation")):
        evaluation["state"] = "DATA_BLOCKED"
        evaluation["reasons"] = sorted(set(evaluation["reasons"]) | set(snapshot.get("data_blockers") or []) | {"REQUIRED_INPUT_UNAVAILABLE"})
    return _envelope(
        "evaluate_frozen_policy",
        {"symbol": symbol.upper(), "right": normalized_right, "evidence_hash": content_hash(evidence or {})},
        {
            "eligible_scope": in_scope,
            "policy_id": policy["policy_id"],
            "strategy_id": policy["selected_policy_ids"]["strategy"],
            "policy_hash": policy["policy_hash"],
            "profile_id": scope["profile_id"],
            "rights_separate": scope["evidence_strata_separate"],
            "decision": evaluation["state"] if in_scope else "OUT_OF_APPROVED_SCOPE",
            "evaluation": evaluation,
            "quality_flags": evaluation["reasons"],
            "contract_qualification": "NOT_EVALUATED",
            "capital_qualification": "NOT_EVALUATED",
            "does_not_generate_signal": True,
        },
        started_at=started,
    )


def get_contract_candidates(*, symbol: str, expiry: str | None = None, limit: int = 12) -> dict[str, Any]:
    started = _now()
    expiry_payload = option_expiries(symbol)
    selected_expiry = expiry
    if not selected_expiry:
        values = list(expiry_payload.get("expiries") or [])
        selected_expiry = str(values[0]) if values else None
    if not selected_expiry:
        return _envelope(
            "get_contract_candidates",
            {"symbol": symbol.upper(), "expiry": None, "limit": limit},
            {"contracts": [], "quality_flags": ["NO_UNEXPIRED_OPTION_EXPIRY"], "selection_performed": False},
            started_at=started,
        )
    chain = option_chain(symbol, selected_expiry)
    rows = list(chain.get("contracts") or chain.get("items") or [])[: max(1, min(int(limit), 50))]
    ids = [str(item.get("contract_symbol") or item.get("contract_id") or item.get("symbol") or "") for item in rows]
    ids = [item for item in ids if item]
    snapshots = option_contract_snapshots(ids) if ids else {"snapshots": []}
    flags = []
    if not ids:
        flags.append("OPTION_CHAIN_EMPTY")
    return _envelope(
        "get_contract_candidates",
        {"symbol": symbol.upper(), "expiry": selected_expiry, "limit": limit},
        {
            "expiry": selected_expiry,
            "chain_rows": rows,
            "snapshots": snapshots.get("snapshots", []),
            "quality_flags": flags,
            "selection_performed": False,
            "quotes_are_reference_evidence": True,
        },
        started_at=started,
    )


def run_option_scenarios(*, sample: dict[str, Any], as_of: str) -> dict[str, Any]:
    started = _now()
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8-sig"))
    feature = compute_option_feature_snapshot(sample, as_of=as_of)
    scenario = local_greeks_scenario_grid(feature, protocol)
    flags = list(feature.get("quality_flags") or [])
    if scenario.get("status") != "COMPLETE":
        flags.append("SCENARIO_INPUTS_PARTIAL")
    return _envelope(
        "run_option_scenarios",
        {"contract_id": sample.get("contract_id"), "as_of": as_of, "sample_hash": content_hash(sample)},
        {
            "feature_snapshot": feature,
            "scenario": scenario,
            "quality_flags": flags,
            "probability_claim": False,
            "executable_price_claim": False,
        },
        started_at=started,
    )


def get_event_evidence(*, symbol: str, db_path: Path, as_of: str | None = None) -> dict[str, Any]:
    started = _now()
    evidence = option_event_context(db_path, symbol, as_of)
    flags = ["EVENT_COVERAGE_INCOMPLETE"] if evidence.get("status") == "incomplete" else []
    return _envelope(
        "get_event_evidence",
        {"symbol": symbol.upper(), "as_of": as_of},
        {"event_evidence": evidence, "quality_flags": flags, "unknown_is_not_no_event": True},
        started_at=started,
    )


def get_research_result(*, experiment_id: str = "E-S-001", research_db: Path = DEFAULT_RESEARCH_DB) -> dict[str, Any]:
    started = _now()
    review = review_r1_payload()
    experiment = review.get("experiment") or {}
    registered_ids = {
        "E-S-001",
        "E-S-001_EXCESS_RS20_TO_FORWARD5",
        str(experiment.get("experiment_id") or ""),
    }
    match = experiment if experiment_id in registered_ids and review.get("status") == "AVAILABLE" else None
    flags = [] if match else ["RESEARCH_RESULT_NOT_FOUND"]
    return _envelope(
        "get_research_result",
        {"experiment_id": experiment_id},
        {
            "experiment": match,
            "status": match.get("status") if match else review.get("status"),
            "conclusion": match.get("conclusion") if match else None,
            "dataset_manifest": review.get("dataset") if match else None,
            "review_bundle": {
                "bundle_id": review.get("bundle_id"),
                "bundle_hash": review.get("bundle_hash"),
            },
            "authoritative_source": "OPTIONS_REVIEW_R1_ADJUSTED_DATA_ARTIFACT",
            "legacy_workbench_status_not_used": True,
            "quality_flags": flags,
            "dev_only": True,
            "stock_research_is_not_option_performance": True,
        },
        started_at=started,
    )


TOOL_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "get_market_snapshot": get_market_snapshot,
    "compute_registered_features": compute_registered_features,
    "evaluate_frozen_policy": evaluate_frozen_policy,
    "get_contract_candidates": get_contract_candidates,
    "run_option_scenarios": run_option_scenarios,
    "get_event_evidence": get_event_evidence,
    "get_research_result": get_research_result,
}


TOOL_SCHEMAS = [
    {"type": "function", "name": "get_market_snapshot", "description": "Read the current underlying snapshot with timestamps and quality flags.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"], "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "compute_registered_features", "description": "Read registered point-in-time stock and option feature snapshots.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"], "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "evaluate_frozen_policy", "description": "Check scope and identity of the frozen policy without generating a signal.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "right": {"type": "string", "enum": ["CALL", "PUT"]}}, "required": ["symbol", "right"], "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "get_contract_candidates", "description": "Read a bounded option-chain sample and reference snapshots without selecting a trade.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "expiry": {"type": ["string", "null"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, "required": ["symbol"], "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "run_option_scenarios", "description": "Run deterministic local-Greeks scenarios without probabilities or executable-price claims.", "parameters": {"type": "object", "properties": {"sample": {"type": "object"}, "as_of": {"type": "string"}}, "required": ["sample", "as_of"], "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "get_event_evidence", "description": "Read point-in-time event coverage; unknown remains unknown.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "as_of": {"type": ["string", "null"]}}, "required": ["symbol"], "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "get_research_result", "description": "Read the registered E-S-001 result without treating stock research as option performance.", "parameters": {"type": "object", "properties": {"experiment_id": {"type": "string"}}, "required": [], "additionalProperties": False}, "strict": True},
]


def call_tool(name: str, arguments: dict[str, Any], *, db_path: Path) -> dict[str, Any]:
    if name not in TOOL_REGISTRY:
        raise ValueError("TOOL_NOT_ALLOWLISTED")
    kwargs = dict(arguments)
    if name in {"get_market_snapshot", "get_event_evidence"}:
        kwargs["db_path"] = db_path
    return TOOL_REGISTRY[name](**kwargs)


__all__ = ["TOOL_REGISTRY", "TOOL_SCHEMAS", "TOOL_VERSION", "call_tool"]
