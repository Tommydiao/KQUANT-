from __future__ import annotations

import json
import os
import math
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests

from .options_signal_copilot import (
    DEFAULT_STORE_PATH,
    get_ai_assessment,
    load_copilot_config,
    store_ai_assessment,
    content_hash,
)
from .options_signal_tools import TOOL_SCHEMAS, call_tool
from .options_api_budget import api_budget_status, mark_api_request_sent, reserve_api_budget, settle_api_budget
from .options_llm_credentials import api_key, credential_source


REPO_ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_PATH = REPO_ROOT / "work" / "options_signal_copilot" / "astra_capability.json"
ASSESSMENT_REQUIRED_KEYS = {
    "snapshot_id",
    "profile_id",
    "right",
    "judgement",
    "hypothesis",
    "contract_refs",
    "support_refs",
    "opposing_refs",
    "tool_run_ids",
    "missing_inputs",
    "invalidation_refs",
    "proposed_valid_until",
    "review_priority",
}


def _key() -> str:
    return api_key()


def _saved_capability(path: Path = CAPABILITY_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _save_capability(payload: dict[str, Any], path: Path = CAPABILITY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sanitized = {
        key: value
        for key, value in payload.items()
        if key not in {"api_key", "authorization", "request_headers", "response_headers"}
    }
    sanitized["credentials_exposed"] = False
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def astra_status() -> dict[str, Any]:
    config = load_copilot_config()
    runtime = config["llm_runtime"]
    capability = _saved_capability()
    budget = api_budget_status(store_path=DEFAULT_STORE_PATH)
    return {
        "requested_model": runtime["requested_model"],
        "actual_model_id": capability.get("actual_model_id") if capability else runtime.get("actual_model_id"),
        "api_key_configured": bool(_key()),
        "model_access_status": capability.get("status") if capability else runtime.get("model_access_status", "NOT_CHECKED"),
        "latest_capability_check": capability,
        "daily_budget_usd": runtime.get("daily_budget_usd"),
        "paid_calls_enabled": bool(runtime.get("paid_calls_enabled")),
        "approval_status": runtime.get("approval_status"),
        "silent_model_fallback": False,
        "tool_count": len(TOOL_SCHEMAS),
        "budget_ledger": {
            "status": budget["status"],
            "day_count": len(budget.get("days", [])),
            "reservation_count": len(budget.get("reservations", [])),
            "active_or_unknown_reservations": sum(row.get("state") in {"RESERVED", "USAGE_UNKNOWN"} for row in budget.get("reservations", [])),
        },
    }


def astra_auth_diagnostic() -> dict[str, Any]:
    capability = _saved_capability() or {}
    http_status = capability.get("http_status")
    return {
        "endpoint": "https://api.openai.com/v1",
        "endpoint_host": "api.openai.com",
        "credential_source": credential_source(),
        "credential_present": bool(_key()),
        "credential_value_recorded": False,
        "last_http_status": http_status,
        "last_error_type": capability.get("error_type"),
        "diagnosis": "AUTHENTICATION_REJECTED" if http_status == 401 else ("NO_CREDENTIAL" if not _key() else "NOT_PROVEN"),
        "model_nonexistence_proven": False,
        "paid_inference_used": bool(capability.get("paid_inference_used", False)),
        "silent_fallback_used": False,
    }


def probe_model_access(model_id: str = "gpt-6-astra", *, timeout: int = 20) -> dict[str, Any]:
    api_key = _key()
    if not api_key:
        result = {"status": "MISSING_KEY", "model_id": model_id, "actual_model_id": None, "paid_inference_used": False}
        _save_capability(result)
        return result
    try:
        response = requests.get(
            f"https://api.openai.com/v1/models/{quote(model_id, safe='')}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        body = response.json() if response.content else {}
        result = {
            "status": "ACCESSIBLE" if response.ok and body.get("id") == model_id else "NOT_ACCESSIBLE",
            "http_status": response.status_code,
            "model_id": body.get("id") if response.ok else model_id,
            "actual_model_id": body.get("id") if response.ok else None,
            "object": body.get("object") if response.ok else None,
            "error_type": (body.get("error") or {}).get("type") if isinstance(body, dict) else None,
            "paid_inference_used": False,
            "credentials_exposed": False,
        }
        _save_capability(result)
        return result
    except Exception as exc:
        result = {
            "status": "PROBE_FAILED",
            "model_id": model_id,
            "actual_model_id": None,
            "error_type": type(exc).__name__,
            "paid_inference_used": False,
            "credentials_exposed": False,
        }
        _save_capability(result)
        return result


def _extract_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    chunks: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []) if isinstance(item, dict) else []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "".join(chunks)


def _function_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in response.get("output", []) if isinstance(item, dict) and item.get("type") == "function_call"]


def _validate_assessment(payload: dict[str, Any]) -> None:
    if set(payload) != ASSESSMENT_REQUIRED_KEYS:
        raise ValueError("ASTRA_ASSESSMENT_SCHEMA_MISMATCH")
    if payload["judgement"] not in {"RESEARCH_CANDIDATE", "WAIT", "CONFLICTED", "ABSTAIN"}:
        raise ValueError("ASTRA_JUDGEMENT_NOT_ALLOWED")
    if payload["review_priority"] not in {"NORMAL", "ATTENTION", "UNKNOWN"}:
        raise ValueError("ASTRA_REVIEW_PRIORITY_NOT_ALLOWED")


class AstraResearchClient:
    def __init__(
        self,
        *,
        db_path: Path,
        store_path: Path = DEFAULT_STORE_PATH,
        budget_store_path: Path | None = None,
        transport: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.db_path = db_path
        self.store_path = store_path
        self.budget_store_path = budget_store_path or store_path
        self.real_transport = transport is None
        self.transport = transport or self._http_transport

    @staticmethod
    def _http_transport(payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
        response.raise_for_status()
        body = response.json()
        body["provider_request_id"] = response.headers.get("x-request-id")
        return body

    def runtime_configuration(self, signal: dict[str, Any]) -> dict[str, Any]:
        return load_copilot_config()["llm_runtime"]

    def assess(self, signal: dict[str, Any]) -> dict[str, Any]:
        runtime = self.runtime_configuration(signal)
        model = str(runtime["requested_model"])
        material_hash = content_hash({"signal_material": signal["material_state_hash"], "execution_config": runtime})
        cached = get_ai_assessment(str(signal["signal_id"]), material_hash, model, store_path=self.store_path)
        if cached and (cached.get("state") == "COMPLETED" or (cached.get("payload") or {}).get("paid_call_attempted")):
            return cached
        if not runtime.get("paid_calls_enabled") or runtime.get("daily_budget_usd") is None or runtime.get("approval_status") != "APPROVED":
            return store_ai_assessment(
                signal_id=str(signal["signal_id"]),
                material_state_hash=material_hash,
                model_id=model,
                state="BUDGET_BLOCKED",
                payload={"reason": "API_BUDGET_CONFIRMED_REQUIRED", "paid_call_attempted": False, "fallback_used": False},
                store_path=self.store_path,
            )
        if runtime.get("actual_model_id") != model:
            return store_ai_assessment(
                signal_id=str(signal["signal_id"]),
                material_state_hash=material_hash,
                model_id=model,
                state="FAILED",
                payload={"reason": "ACTUAL_MODEL_ID_NOT_VERIFIED", "paid_call_attempted": False, "fallback_used": False},
                store_path=self.store_path,
            )
        price = runtime.get("price_schedule")
        output_limit = int(runtime.get("max_total_output_tokens_per_assessment") or 8000)
        input_limit = int(runtime.get("maximum_input_tokens_per_request") or 16000)
        rounds = int(runtime.get("max_tool_rounds") or 4) + 1
        if price:
            input_rate, output_rate = float(price["input_usd_per_million"]), float(price["output_usd_per_million"])
            budget = float(runtime.get("maximum_single_full_scan_usd") or 0)
            remaining_cost = budget - input_limit * rounds * input_rate / 1_000_000
            output_limit = min(output_limit, math.floor(remaining_cost * 1_000_000 / output_rate)) if output_rate > 0 else 0
            if input_rate < 0 or output_limit < 512:
                return store_ai_assessment(signal_id=str(signal["signal_id"]), material_state_hash=material_hash, model_id=model,
                    state="BUDGET_BLOCKED", payload={"reason": "WORST_CASE_TOKEN_COST_EXCEEDS_CAP", "paid_call_attempted": False}, store_path=self.store_path)
        if not _key():
            return store_ai_assessment(
                signal_id=str(signal["signal_id"]),
                material_state_hash=material_hash,
                model_id=model,
                state="FAILED",
                payload={"reason": "OPENAI_API_KEY_MISSING", "paid_call_attempted": False, "fallback_used": False},
                store_path=self.store_path,
            )

        budget_timezone = runtime.get("budget_timezone")
        maximum_scan_cost = runtime.get("maximum_single_full_scan_usd")
        if not budget_timezone or maximum_scan_cost is None:
            return store_ai_assessment(
                signal_id=str(signal["signal_id"]),
                material_state_hash=material_hash,
                model_id=model,
                state="BUDGET_BLOCKED",
                payload={"reason": "ATOMIC_BUDGET_POLICY_INCOMPLETE", "paid_call_attempted": False, "fallback_used": False},
                store_path=self.store_path,
            )
        role = runtime.get("model_role", "ASTRA")
        scan_id = f"{role.lower()}:{signal['signal_id']}:{material_hash}:{model}"
        reservation = reserve_api_budget(
            scan_id=scan_id,
            worst_case_usd=maximum_scan_cost,
            daily_limit_usd=runtime["daily_budget_usd"],
            timezone=str(budget_timezone),
            approved=runtime.get("approval_status") == "APPROVED",
            role=role,
            candidate_id=str(signal["signal_id"]),
            max_parallel=int(runtime.get("max_parallel") or 2),
            role_day_limit=runtime.get("role_day_limit"),
            role_candidate_limit=runtime.get("role_candidate_limit"),
            approval_id=runtime.get("test_approval_id", ""),
            approval_total_usd=runtime.get("test_approval_total_usd"),
            store_path=self.budget_store_path,
        )
        if not reservation.get("paid_call_allowed"):
            return store_ai_assessment(
                signal_id=str(signal["signal_id"]),
                material_state_hash=material_hash,
                model_id=model,
                state="BUDGET_BLOCKED",
                payload={"reason": reservation["status"], "budget": reservation, "paid_call_attempted": False, "fallback_used": False},
                store_path=self.store_path,
            )

        tool_runs: list[str] = []
        request: dict[str, Any] = {
            "model": model,
            **({"service_tier": "default"} if runtime.get("test_approval_id") else {}),
            **({"tool_choice": "required"} if runtime.get("test_approval_id") else {}),
            "reasoning": {"effort": "high"},
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are a read-only options research copilot. Use only supplied tools. "
                        "Never create probabilities, alter policies, write a ledger, size a real trade, or submit an order. "
                        "Unknown evidence must remain unknown. Return only the registered JSON assessment."
                    ),
                },
                {"role": "user", "content": json.dumps(signal, ensure_ascii=False)},
            ],
            "tools": TOOL_SCHEMAS,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "kquant_options_research_assessment",
                    "schema": json.loads((REPO_ROOT / "config" / "options_llm_assessment.schema.json").read_text(encoding="utf-8")),
                    "strict": True,
                }
            },
            "max_output_tokens": output_limit,
        }
        request_sent = False
        provider_request_ids: list[str] = []
        actual_model = None
        reported_costs: list[float] = []
        prior_token_bound = 0
        output_remaining = output_limit
        try:
            for _ in range(int(runtime.get("max_tool_rounds") or runtime.get("max_tool_rounds_proposal") or 4) + 1):
                if price and len(json.dumps(request, ensure_ascii=False).encode("utf-8")) + prior_token_bound + 1024 > input_limit:
                    raise ValueError("INPUT_TOKEN_BOUND_EXCEEDED")
                if output_remaining < 1:
                    raise ValueError("TOTAL_OUTPUT_TOKEN_LIMIT_REACHED")
                request["max_output_tokens"] = output_remaining
                mark_api_request_sent(reservation["reservation_id"], store_path=self.budget_store_path)
                request_sent = True
                response = self.transport(request)
                actual_model = response.get("model")
                if response.get("id"):
                    provider_request_ids.append(str(response.get("provider_request_id") or response["id"]))
                if actual_model != model:
                    raise ValueError("ACTUAL_RESPONSE_MODEL_MISMATCH")
                usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
                if price and (usage.get("input_tokens") is None or usage.get("output_tokens") is None):
                    raise ValueError("TOKEN_USAGE_UNKNOWN_NO_FURTHER_CALL")
                output_remaining -= int(usage.get("output_tokens") or 0)
                prior_token_bound = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
                if usage.get("total_cost_usd") is not None:
                    reported_costs.append(float(usage["total_cost_usd"]))
                elif price:
                    cached = int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0)
                    if cached and price.get("cached_input_usd_per_million") is None:
                        raise ValueError("CACHED_TOKEN_PRICE_UNKNOWN")
                    cached_rate = float(price.get("cached_input_usd_per_million", input_rate))
                    reported_costs.append(((int(usage["input_tokens"]) - cached) * input_rate + cached * cached_rate + int(usage["output_tokens"]) * output_rate) / 1_000_000)
                calls = _function_calls(response)
                if not calls:
                    assessment = json.loads(_extract_text(response))
                    _validate_assessment(assessment)
                    assessment["tool_run_ids"] = sorted(set(list(assessment["tool_run_ids"]) + tool_runs))
                    budget_result = settle_api_budget(
                        reservation["reservation_id"],
                        actual_cost_usd=sum(reported_costs) if reported_costs and len(reported_costs) == len(provider_request_ids) else None,
                        request_sent=request_sent,
                        provider_request_id=provider_request_ids[-1] if provider_request_ids else None,
                        store_path=self.budget_store_path,
                    )
                    return store_ai_assessment(
                        signal_id=str(signal["signal_id"]),
                        material_state_hash=material_hash,
                        model_id=model,
                        state="COMPLETED",
                        payload={"assessment": assessment, "response_id": response.get("id"), "fallback_used": False, "budget": budget_result,
                                 "requested_model": model, "actual_model": response.get("model"), "endpoint": "https://api.openai.com/v1", "config_version": runtime.get("config_version"), "model_role": role,
                                 "real_transport": self.real_transport, "provider_request_ids": provider_request_ids, "executed_tool_run_ids": tool_runs},
                        store_path=self.store_path,
                    )
                outputs = []
                if len(tool_runs) + len(calls) > int(runtime.get("max_tool_calls") or 12):
                    raise ValueError("TOOL_CALL_LIMIT_REACHED")
                for call in calls:
                    name = str(call.get("name") or "")
                    arguments = json.loads(str(call.get("arguments") or "{}"))
                    result = call_tool(name, arguments, db_path=self.db_path)
                    tool_runs.append(result["tool_run_id"])
                    outputs.append({"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(result, ensure_ascii=False)})
                request = {**request, "previous_response_id": response.get("id"), "input": outputs,
                           **({"tool_choice": "auto"} if runtime.get("test_approval_id") else {})}
            raise RuntimeError("ASTRA_TOOL_ROUND_LIMIT_REACHED")
        except Exception as exc:
            budget_result = settle_api_budget(
                reservation["reservation_id"],
                actual_cost_usd=None,
                request_sent=request_sent,
                provider_request_id=provider_request_ids[-1] if provider_request_ids else None,
                store_path=self.budget_store_path,
            )
            return store_ai_assessment(
                signal_id=str(signal["signal_id"]),
                material_state_hash=material_hash,
                model_id=model,
                state="FAILED",
                payload={"reason": type(exc).__name__, "http_status": getattr(getattr(exc, "response", None), "status_code", None),
                         "requested_model": model, "actual_model": actual_model, "endpoint": "https://api.openai.com/v1", "config_version": runtime.get("config_version"),
                         "paid_call_attempted": request_sent, "fallback_used": False, "tool_run_ids": tool_runs, "budget": budget_result},
                store_path=self.store_path,
            )


class RoutedResearchClient(AstraResearchClient):
    """Shared executor, explicit router model and global budget; no automatic invocation."""
    def __init__(self, *, escalation_reason=None, test_role=None, test_approval=None, **kwargs):
        super().__init__(**kwargs)
        self.escalation_reason = escalation_reason
        self.test_role = test_role
        self.test_approval = test_approval

    def runtime_configuration(self, signal):
        from .options_model_router import load_model_router_config, route_research_task
        config = load_model_router_config()
        route = route_research_task(task_kind="signal_review", candidate_id=str(signal["signal_id"]),
                                    escalation_reason=self.escalation_reason,
                                    hard_data_failure=bool(signal.get("hard_data_failure")))
        runtime = dict(load_copilot_config()["llm_runtime"])
        runtime.update(requested_model=route.get("requested_model_id") or config["roles"]["SOL"]["requested_model_id"],
                       actual_model_id=route.get("actual_model_id"), model_role=route.get("model_role") or "SOL",
                       paid_calls_enabled=bool(route.get("paid_call_allowed")),
                       approval_status="APPROVED" if route.get("paid_call_allowed") else "NOT_APPROVED",
                       daily_budget_usd=config.get("daily_global_budget_usd"),
                       maximum_single_full_scan_usd=config.get("per_scan_budget_usd"),
                       budget_timezone=config.get("budget_timezone"), config_version=config["router_version"],
                       max_tool_rounds=config["max_model_rounds_per_research"], max_tool_calls=config["max_tool_calls_per_research"])
        runtime["max_parallel"] = config["max_parallel_model_requests"]
        if runtime["model_role"] == "ASTRA":
            runtime["role_day_limit"] = config["max_astra_escalations_per_market_day"]
            runtime["role_candidate_limit"] = config["max_astra_escalations_per_candidate"]
        price = (config.get("verified_price_schedule") or {}).get(runtime["requested_model"])
        runtime["price_schedule"] = price
        runtime["maximum_input_tokens_per_request"] = 16000
        if self.test_approval is not None:
            from .options_model_router import authentication_configuration, current_capability
            approval = self.test_approval
            role = self.test_role
            model = approval.get("roles", {}).get(role)
            capability = current_capability(role, config) if role in {"SOL", "ASTRA"} else None
            from datetime import datetime, UTC
            from .options_model_router import authentication_configuration
            auth = authentication_configuration()
            expiry = datetime.fromisoformat(approval["expires_at"].replace("Z", "+00:00"))
            if (expiry.tzinfo is None or datetime.now(UTC) >= expiry
                    or signal.get("source") != "SYNTHETIC_TEST" or signal.get("test_only") is not True
                    or not signal.get("synthetic") or not self.real_transport
                    or approval.get("status") != "APPROVED" or approval.get("purpose") != "ISOLATED_TEST_ONLY"
                    or approval.get("endpoint") != "https://api.openai.com/v1"
                    or not auth["endpoint_match"] or approval.get("bound_configuration_hash") != auth["configuration_hash"]
                    or model != config["roles"][role]["requested_model_id"]
                    or not capability or capability.get("status") != "ACCESSIBLE"
                    or capability.get("actual_model_id") != model):
                runtime["paid_calls_enabled"] = False
                runtime["approval_status"] = "TEST_ONLY_ACCESS_NOT_VERIFIED"
                return runtime
            runtime.update(requested_model=model, actual_model_id=model, model_role=role,
                           paid_calls_enabled=True, approval_status="APPROVED",
                           daily_budget_usd=approval["total_usd"],
                           maximum_single_full_scan_usd=approval["per_assessment_usd"],
                           budget_timezone="Asia/Shanghai", max_parallel=1,
                           max_tool_rounds=2, max_tool_calls=4,
                           max_total_output_tokens_per_assessment=4096,
                           test_approval_id=approval["approval_id"],
                           test_approval_total_usd=approval["total_usd"])
            runtime["price_schedule"] = approval["price_schedule"][model]
            runtime["maximum_input_tokens_per_request"] = 12000
            return runtime
        if not price or not price.get("verified_at") or price.get("input_usd_per_million") is None or price.get("output_usd_per_million") is None:
            runtime["paid_calls_enabled"] = False
            runtime["approval_status"] = "PRICE_SCHEDULE_NOT_VERIFIED"
        return runtime


__all__ = ["AstraResearchClient", "RoutedResearchClient", "CAPABILITY_PATH", "astra_auth_diagnostic", "astra_status", "probe_model_access"]
