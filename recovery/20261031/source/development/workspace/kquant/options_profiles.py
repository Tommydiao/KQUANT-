from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from .policy_availability import PolicyConfigUnavailable, read_policy


DEFAULT_PROFILE_PATH = Path(__file__).resolve().parents[1] / "config" / "options_research_profiles_v1.json"
PENDING_FIELDS = (
    "holding_period_policy",
    "expiry_selection_policy",
    "moneyness_selection_policy",
    "delta_range",
    "liquidity_selection_policy",
    "event_risk_policy",
    "factor_policy",
    "entry_policy",
    "exit_policy",
    "position_sizing_policy",
    "model_artifact_id",
)
PROFILE_IDS = (
    "SHORT_ATM_DAYS_WEEK",
    "MEDIUM_ATM_WEEKS_MONTHS",
    "LONG_OTM_MONTHS_YEAR",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_profile_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("schema_version") != "options_research_profiles_draft_v1":
        errors.append("Unsupported profile schema version.")
    if payload.get("purpose") != "METADATA_AND_OBSERVATION_ONLY":
        errors.append("Profiles must remain metadata and observation only.")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or len(profiles) != 3:
        errors.append("Exactly three research profiles are required.")
        profiles = []
    ids = [item.get("profile_id") for item in profiles if isinstance(item, dict)]
    if tuple(ids) != PROFILE_IDS:
        errors.append("Profile identifiers or order do not match the frozen contract.")
    for item in profiles:
        if not isinstance(item, dict):
            errors.append("Each profile must be an object.")
            continue
        profile_id = str(item.get("profile_id") or "unknown")
        if item.get("option_rights") != ["CALL", "PUT"]:
            errors.append(f"{profile_id}: Call and Put directions must remain separate and available.")
        if item.get("strategy_status") != "PENDING_STRATEGY_DEFINITION":
            errors.append(f"{profile_id}: strategy status must remain pending.")
        for flag in ("signal_generation_enabled", "trade_simulation_enabled", "automatic_order_enabled"):
            if item.get(flag) is not False:
                errors.append(f"{profile_id}: {flag} must be false.")
        for field in PENDING_FIELDS:
            if item.get(field) is not None:
                errors.append(f"{profile_id}: {field} must remain null.")
    return {"status": "pass" if not errors else "fail", "errors": errors}


def validate_profile_activation(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = validate_profile_metadata(payload)
    blockers = list(metadata["errors"])
    for item in payload.get("profiles") or []:
        profile_id = str(item.get("profile_id") or "unknown")
        pending = [field for field in PENDING_FIELDS if item.get(field) is None]
        if pending:
            blockers.append(f"{profile_id}: pending policy fields: {', '.join(pending)}")
        if item.get("strategy_status") == "PENDING_STRATEGY_DEFINITION":
            blockers.append(f"{profile_id}: strategy definition is pending.")
    return {
        "status": "blocked",
        "activation_allowed": False,
        "blockers": blockers or ["Activation is disabled by the foundation policy."],
    }


def load_options_profiles(path: Path | None = None) -> dict[str, Any]:
    source = Path(path or os.getenv("KQUANT_OPTIONS_PROFILE_CONFIG", "") or DEFAULT_PROFILE_PATH).resolve()
    try:
        payload = read_policy(source, capability="research_profiles")
    except PolicyConfigUnavailable as exc:
        return {**exc.status(), "profiles": [], "profile_records_complete": False,
                "strategy_status": "UNAVAILABLE", "performance_status": "NOT_EVALUATED",
                "trade_simulation_enabled": False, "automatic_order_enabled": False}
    metadata = validate_profile_metadata(payload)
    activation = validate_profile_activation(payload)
    if metadata["status"] != "pass":
        raise ValueError("Invalid options profile metadata: " + "; ".join(metadata["errors"]))
    return {
        **payload,
        "current_policy_available": True,
        "config_path": str(source),
        "config_sha256": _sha256(source),
        "metadata_validation": metadata,
        "activation_validation": activation,
        "strategy_status": "PENDING_STRATEGY_DEFINITION",
        "performance_status": "NOT_EVALUATED",
        "signal_generation_enabled": False,
        "trade_simulation_enabled": False,
        "automatic_order_enabled": False,
    }


def capability_evidence() -> dict[str, Any]:
    configured = os.getenv("KQUANT_OPTION_CAPABILITY_EVIDENCE", "").strip()
    if not configured:
        return {"status": "not_configured", "evidence_level": "UNAVAILABLE_OR_CONFLICTED"}
    source = Path(configured).resolve()
    if not source.exists():
        return {"status": "missing", "path": str(source), "evidence_level": "UNAVAILABLE_OR_CONFLICTED"}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "path": str(source), "error_type": type(exc).__name__,
                "evidence_level": "UNAVAILABLE_OR_CONFLICTED"}
    return {
        "status": "available",
        "path": str(source),
        "sha256": _sha256(source),
        "generated_at": payload.get("generated_at"),
        "market_session": payload.get("market_session"),
        "entitlement_status": payload.get("entitlement_status"),
        "quote_capability_status": payload.get("quote_capability_status"),
        "clock_status": payload.get("clock_status"),
        "evidence_level": payload.get("evidence_level"),
        "market_day_validation_status": payload.get("market_day_validation_status"),
    }


def options_foundation_status(*, supervisor: dict[str, Any] | None = None) -> dict[str, Any]:
    profiles = load_options_profiles()
    return {
        **({"status": "UNAVAILABLE", "reason": profiles["reason"], "current_policy_available": False}
           if profiles.get("status") == "UNAVAILABLE" else {}),
        "generated_at": datetime.now(UTC).isoformat(),
        "profiles": profiles,
        "capability_evidence": capability_evidence(),
        "supervisor": supervisor,
        "strategy_status": "UNAVAILABLE" if profiles.get("status") == "UNAVAILABLE" else "PENDING_STRATEGY_DEFINITION",
        "performance_status": "NOT_EVALUATED",
        "trading_enabled": False,
        "simulation_enabled": False,
        "order_submission_enabled": False,
    }
