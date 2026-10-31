from __future__ import annotations

import json
import getpass
import hashlib
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

from .options_api_budget import api_budget_status
from .options_llm_credentials import api_key, credential_source
from .options_signal_copilot import DEFAULT_STORE_PATH


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "options_model_router_v1.json"
CAPABILITY_DIR = REPO_ROOT / "work" / "options_signal_copilot" / "model_capabilities"
LEGACY_ASTRA_CAPABILITY_PATH = REPO_ROOT / "work" / "options_signal_copilot" / "astra_capability.json"
ROUTER_VERSION = "sol-astra-router-v1"
PROGRAM_ONLY_TASKS = {
    "feature_math",
    "policy_evaluation",
    "numeric_formatting",
    "notification_text",
    "deduplication",
    "pnl",
    "risk_limits",
}


def load_model_router_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("router_version") != ROUTER_VERSION:
        raise ValueError("MODEL_ROUTER_VERSION_MISMATCH")
    return payload


def _key() -> str:
    return api_key()


def authentication_configuration() -> dict[str, Any]:
    """Expose configuration provenance, never credentials or URL query strings."""
    configured = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
    official = "https://api.openai.com/v1"
    endpoint = (configured or official).rstrip("/")
    key = _key()
    key_present = bool(key)
    return {
        "credential_source": credential_source(),
        "credential_present": key_present,
        "endpoint_source": "PROCESS_ENV" if configured else "OFFICIAL_DEFAULT",
        "configured_endpoint_host": urlparse(endpoint).hostname,
        "effective_endpoint": official,
        "api_family": "responses",
        "endpoint_match": endpoint == official,
        "status": "ENDPOINT_APPROVAL_REQUIRED" if endpoint != official else ("CONFIGURED_NOT_AUTHENTICATED" if key_present else "MISSING_OR_UNREADABLE_KEY"),
        "paid_inference_attempted": False,
        "configuration_hash": hashlib.sha256(json.dumps({"endpoint": endpoint, "source": credential_source(),
            "credential_digest": hashlib.sha256(key.encode()).hexdigest()}, sort_keys=True).encode()).hexdigest(),
    }


def _capability_path(role: str) -> Path:
    return CAPABILITY_DIR / f"{role.strip().lower()}.json"


def _read_capability(role: str) -> dict[str, Any] | None:
    path = _capability_path(role)
    if not path.exists() and role.strip().upper() == "ASTRA" and LEGACY_ASTRA_CAPABILITY_PATH.exists():
        path = LEGACY_ASTRA_CAPABILITY_PATH
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_capability(role: str, payload: dict[str, Any]) -> None:
    CAPABILITY_DIR.mkdir(parents=True, exist_ok=True)
    sanitized = {
        key: value for key, value in payload.items()
        if key not in {"api_key", "authorization", "request_headers", "response_headers"}
    }
    sanitized["credentials_exposed"] = False
    sanitized["configuration_hash"] = authentication_configuration()["configuration_hash"]
    path = _capability_path(role)
    history = CAPABILITY_DIR / "history"
    history.mkdir(exist_ok=True)
    for record in (_read_capability(role), sanitized):
        if record:
            encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2)
            identity = hashlib.sha256(encoded.encode()).hexdigest()
            archived = history / f"{role.lower()}-{identity}.json"
            if not archived.exists():
                archived.write_text(encoded + "\n", encoding="utf-8")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def current_capability(role, config=None, authentication=None):
    saved = _read_capability(role)
    if not saved:
        return None
    config = config or load_model_router_config()
    authentication = authentication or authentication_configuration()
    current = (saved.get("configuration_hash") == authentication["configuration_hash"]
               and saved.get("requested_model_id") == config["roles"][role]["requested_model_id"]
               and saved.get("endpoint") == authentication["effective_endpoint"])
    return {**saved, "status": saved.get("status") if current else "HISTORICAL_CONFIGURATION",
            "historical_status": saved.get("status"), "current_configuration": current}


def probe_role_access(role: str, *, timeout: int = 20) -> dict[str, Any]:
    config = load_model_router_config()
    normalized = role.strip().upper()
    if normalized not in config["roles"]:
        raise ValueError("UNKNOWN_MODEL_ROLE")
    model_id = str(config["roles"][normalized]["requested_model_id"])
    authentication = authentication_configuration()
    if not authentication["endpoint_match"]:
        result = {"role": normalized, "requested_model_id": model_id, "actual_model_id": None,
                  "status": "ENDPOINT_APPROVAL_REQUIRED", "authentication": authentication,
                  "paid_inference_used": False, "checked_at": datetime.now(UTC).isoformat()}
        _write_capability(normalized, result)
        return result
    if not _key():
        result = {
            "role": normalized,
            "requested_model_id": model_id,
            "actual_model_id": None,
            "status": "MISSING_KEY",
            "endpoint": "https://api.openai.com/v1",
            "paid_inference_used": False,
            "checked_at": datetime.now(UTC).isoformat(),
        }
        _write_capability(normalized, result)
        return result
    try:
        response = requests.get(
            f"https://api.openai.com/v1/models/{quote(model_id, safe='')}",
            headers={"Authorization": f"Bearer {_key()}"},
            timeout=timeout,
        )
        body = response.json() if response.content else {}
        result = {
            "role": normalized,
            "requested_model_id": model_id,
            "actual_model_id": body.get("id") if response.ok else None,
            "status": "ACCESSIBLE" if response.ok and body.get("id") == model_id else "NOT_ACCESSIBLE",
            "http_status": response.status_code,
            "error_type": (body.get("error") or {}).get("type") if isinstance(body, dict) else None,
            "endpoint": "https://api.openai.com/v1",
            "paid_inference_used": False,
            "checked_at": datetime.now(UTC).isoformat(),
        }
    except Exception as exc:  # pragma: no cover - network dependent
        result = {
            "role": normalized,
            "requested_model_id": model_id,
            "actual_model_id": None,
            "status": "PROBE_FAILED",
            "error_type": type(exc).__name__,
            "endpoint": "https://api.openai.com/v1",
            "paid_inference_used": False,
            "checked_at": datetime.now(UTC).isoformat(),
        }
    _write_capability(normalized, result)
    return result


def route_research_task(
    *,
    task_kind: str,
    candidate_id: str = "",
    escalation_reason: str | None = None,
    hard_data_failure: bool = False,
) -> dict[str, Any]:
    config = load_model_router_config()
    if task_kind in PROGRAM_ONLY_TASKS:
        return {
            "route": "PROGRAM_ONLY",
            "model_role": None,
            "candidate_id": candidate_id,
            "paid_call_allowed": False,
            "reason": "DETERMINISTIC_PROGRAM_RESPONSIBILITY",
        }
    if hard_data_failure:
        return {
            "route": "DATA_BLOCKED",
            "model_role": None,
            "candidate_id": candidate_id,
            "paid_call_allowed": False,
            "reason": config["hard_data_failure_action"],
        }
    primary = str(config["primary_research_role"])
    selected = primary
    route = "PRIMARY_RESEARCH"
    escalation_deferred = False
    if escalation_reason:
        if escalation_reason not in config["allowed_escalation_reasons"]:
            return {
                "route": "ESCALATION_REJECTED",
                "model_role": primary,
                "candidate_id": candidate_id,
                "paid_call_allowed": False,
                "reason": "ESCALATION_REASON_NOT_ALLOWLISTED",
            }
        escalation = str(config["escalation_role"])
        capability = current_capability(escalation, config) or {}
        escalation_config = config["roles"][escalation]
        if capability.get("status") == "ACCESSIBLE" and escalation_config.get("paid_enabled") and config.get("budget_approved"):
            selected = escalation
            route = "ESCALATED_RESEARCH"
        else:
            escalation_deferred = True
            selected = primary
            route = "PRIMARY_RESEARCH_ESCALATION_DEFERRED"
    role_config = config["roles"][selected]
    capability = current_capability(selected, config) or {}
    paid_allowed = bool(
        role_config.get("paid_enabled")
        and config.get("budget_approved")
        and authentication_configuration()["endpoint_match"]
        and capability.get("status") == "ACCESSIBLE"
        and capability.get("actual_model_id") == role_config.get("requested_model_id")
    )
    return {
        "route": route,
        "model_role": selected,
        "requested_model_id": role_config.get("requested_model_id"),
        "actual_model_id": capability.get("actual_model_id"),
        "candidate_id": candidate_id,
        "paid_call_allowed": paid_allowed,
        "execution_state": "READY" if paid_allowed else "BUDGET_OR_CAPABILITY_BLOCKED",
        "escalation_reason": escalation_reason,
        "escalation_deferred": escalation_deferred,
        "silent_fallback_used": False,
        "cbrm_in_active_context": False,
    }


def _execution_evidence(path: Path, model: str, config_version: str) -> dict[str, str]:
    result = {"real_response_status": "NOT_VERIFIED", "tool_roundtrip_status": "NOT_VERIFIED"}
    if not path.exists():
        return result
    try:
        with sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True) as connection:
            rows = connection.execute("SELECT payload_json FROM ai_assessments WHERE model_id=? AND state='COMPLETED' ORDER BY rowid DESC LIMIT 50", (model,)).fetchall()
        for row in rows:
            payload = json.loads(row[0])
            if payload.get("real_transport") is not True or payload.get("actual_model") != model or payload.get("config_version") != config_version:
                continue
            result["real_response_status"] = "VERIFIED"
            if payload.get("executed_tool_run_ids"):
                result["tool_roundtrip_status"] = "VERIFIED"
                break
    except (sqlite3.Error, ValueError):
        result = {"real_response_status": "EVIDENCE_UNAVAILABLE", "tool_roundtrip_status": "EVIDENCE_UNAVAILABLE"}
    return result


def model_router_status(*, budget_store: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    config = load_model_router_config()
    authentication = authentication_configuration()
    budget = api_budget_status(store_path=budget_store)
    roles: dict[str, Any] = {}
    for role, role_config in config["roles"].items():
        capability = current_capability(role, config, authentication)
        price = (config.get("verified_price_schedule") or {}).get(role_config.get("requested_model_id")) or {}
        price_verified = bool(price.get("verified_at") and price.get("input_usd_per_million") is not None and price.get("output_usd_per_million") is not None)
        roles[role] = {
            **role_config,
            **_execution_evidence(budget_store, role_config.get("requested_model_id"), config["router_version"]),
            "capability": capability,
            "credential_present": authentication["credential_present"],
            "price_schedule_verified": price_verified,
            "paid_call_ready": bool(
                role_config.get("paid_enabled")
                and price_verified
                and config.get("budget_approved")
                and authentication["endpoint_match"]
                and capability
                and capability.get("status") == "ACCESSIBLE"
                and capability.get("actual_model_id") == role_config.get("requested_model_id")
            ),
        }
    return {
        "status": "READY_NO_PAID_INFERENCE" if not config.get("budget_approved") else "CONFIGURED",
        "router_version": ROUTER_VERSION,
        "authentication": authentication,
        "budget_approved": bool(config.get("budget_approved")),
        "runtime_identity": getpass.getuser(),
        "primary_research_role": config["primary_research_role"],
        "escalation_role": config["escalation_role"],
        "roles": roles,
        "budget": budget,
        "test_only": _test_only_status(authentication, roles, budget),
        "limits": {key: value for key, value in config.items() if key.startswith("max_")},
        "template_notifications_without_llm": bool(config["template_notifications_without_llm"]),
        "repeat_notifications_trigger_inference": bool(config["repeat_notifications_trigger_inference"]),
        "cbrm_in_active_context": False,
        "paper_ledger_write_allowed": False,
        "real_orders_enabled": False,
    }


def _test_only_status(authentication: dict, roles: dict, budget: dict) -> dict:
    try:
        selected = current_test_approval()
        if selected is None:
            return {"status": "CLOSED_OR_NEEDS_EXPLICIT_APPROVAL", "production_paid_calls_enabled": False}
        approval, _ = selected
        identity = str(approval["approval_id"])
        expiry = datetime.fromisoformat(approval["expires_at"].replace("Z", "+00:00"))
        directory = REPO_ROOT / "work/options_signal_copilot/test_only" / hashlib.sha256(identity.encode()).hexdigest()
        binding_path = directory / "credential_binding.json"
        binding = json.loads(binding_path.read_text(encoding="utf-8")) if binding_path.exists() else {}
        bound = binding.get("configuration_hash") == authentication["configuration_hash"]
        costs = [row for row in budget.get("reservations", []) if row.get("approval_id") == identity]
        from decimal import Decimal
        committed = sum((Decimal(str(row.get("actual_cost_usd") or 0)) if row.get("state") == "SETTLED"
                         else Decimal(str(row.get("reserved_usd") or 0)) if row.get("state") in {"RESERVED", "USAGE_UNKNOWN"}
                         else Decimal("0") for row in costs), Decimal("0"))
        outcomes = {}
        for role in ("SOL", "ASTRA"):
            evidence_path = directory / role / "evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.exists() else {}
            result = evidence.get("payload") if isinstance(evidence.get("payload"), dict) else evidence
            capability = (roles.get(role) or {}).get("capability") or {}
            outcomes[role] = {"requested_model": approval.get("roles", {}).get(role),
                              "access": capability.get("status", "NOT_CHECKED"),
                              "assessment_state": evidence.get("state", "NOT_RUN"),
                              "actual_model": result.get("actual_model"),
                              "tool_roundtrip": "VERIFIED" if result.get("executed_tool_run_ids") else "NOT_VERIFIED",
                              "request_count": len(result.get("provider_request_ids") or [])}
        return {"status": "READY_FOR_LOCAL_TEST" if approval.get("status") == "APPROVED" and datetime.now(UTC) < expiry
                and authentication.get("credential_present") and authentication.get("endpoint_match") and (bound or not binding)
                else "CLOSED_OR_NEEDS_LOCAL_CREDENTIAL",
                "expires_at": approval.get("expires_at"), "total_usd": approval.get("total_usd"),
                "per_assessment_usd": approval.get("per_assessment_usd"), "committed_usd": str(committed),
                "credential_binding": "MATCH" if bound else "NOT_BOUND" if not binding else "CHANGED",
                "roles": outcomes, "production_paid_calls_enabled": False}
    except (OSError, ValueError, TypeError, KeyError):
        return {"status": "UNAVAILABLE", "production_paid_calls_enabled": False}


def current_test_approval(*, directory: Path | None = None, now: datetime | None = None) -> tuple[dict, Path] | None:
    """Select one active, owner-approved isolated budget without reviving an expired file."""
    folder = directory or REPO_ROOT / "config/review_acceptances"
    current = now or datetime.now(UTC)
    config = load_model_router_config()
    eligible = []
    for path in folder.glob("options_ai_test_o_setup_*.json"):
        try:
            approval = json.loads(path.read_text(encoding="utf-8"))
            expiry = datetime.fromisoformat(approval["expires_at"].replace("Z", "+00:00"))
            approved = datetime.fromisoformat(approval["approved_at"].replace("Z", "+00:00"))
            if (expiry.tzinfo is None or approved.tzinfo is None or not approved <= current < expiry
                    or approval.get("gate") != "O-SETUP" or approval.get("status") != "APPROVED"
                    or approval.get("approved_by") != "OWNER" or approval.get("purpose") != "ISOLATED_TEST_ONLY"
                    or approval.get("endpoint") != "https://api.openai.com/v1"
                    or approval.get("total_usd") != 2 or approval.get("per_assessment_usd") != 1
                    or approval.get("production_paid_enabled") is not False
                    or any(approval.get("roles", {}).get(role) != config["roles"][role]["requested_model_id"]
                           for role in ("SOL", "ASTRA"))):
                continue
            eligible.append((approved, path.name, approval, path))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if not eligible:
        return None
    _, _, approval, path = max(eligible, key=lambda item: (item[0], item[1]))
    return approval, path


__all__ = [
    "CONFIG_PATH",
    "ROUTER_VERSION",
    "load_model_router_config",
    "model_router_status",
    "probe_role_access",
    "route_research_task",
]
