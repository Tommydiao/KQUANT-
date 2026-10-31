"""S1 reference-only continuations on the existing qualification lane and lease."""
from datetime import date

from . import options_one_minute as common
from . import options_intraday_comparison as model
from . import options_opening_trend_pipeline as pipeline
from .options_opening_trend_contracts import compare, reference_from_inspections
from .options_research_diagnostics import option_cost


def cost_from_contract(contract, *, now):
    native = contract.get("snapshot", {})
    return option_cost(dict(bid=contract.get("bid"), ask=contract.get("ask"),
        delta=contract.get("delta"), multiplier=contract.get("multiplier"), currency=contract.get("quote_currency"),
        multiplier_verified=contract.get("multiplier_status") == "VERIFIED_NATIVE_FIELD",
        price_unit_verified=bool(contract.get("multiplier_evidence")),
        currency_verified=native.get("currency_status") == "VERIFIED_STATIC_RESPONSE_FIELD",
        bbo_received_at=native.get("bbo_received_at"), greeks_received_at=native.get("calc_received_at"),
        source_freshness=native.get("bbo_source_freshness", "UNVERIFIED")), now=now)


def research_step(job, services, *, clock):
    original, progress, now = job["evaluation"], dict(job["progress"]), clock()
    policy = model.load_policy()
    def stop(reason, state="WITHDRAWN"):
        return progress, True, dict(state=state, checked_at=clock().isoformat(), reasons=[reason],
                                    research_only=True, qualified_signal=False)
    if now >= common.timestamp(original["deadline_at"]):
        return stop("ORIGINAL_DEADLINE_EXCEEDED", "EXPIRED")
    if original["policy_hash"] != policy["policy_hash"]:
        return stop("POLICY_OR_SCOPE_CHANGED")
    phase = progress.get("phase", "EVENT")
    if phase == "REFRESH_RESEARCH":
        contract_id = progress["research_contract_id"]
        row = pipeline.collect_contract(services, contract_id, progress)
        if row.get("contract_id") != contract_id:
            return stop("SELECTED_CONTRACT_CHANGED")
        progress.update(contracts=[row], phase="REVIEW")
        return progress, False, None
    if phase == "REFRESH_EVENT" and progress.get("research_contract_id"):
        from .options_opening_trend_event_decision import decide
        previous = progress.get("event", {}).get("event_decision")
        event = services.event(original, now, policy)
        if previous is not None or event.get("event_decision") is not None:
            event["event_decision"] = decide(event, now=clock(),
                horizon=common.timestamp(original["planned_exit_at"]), previous=previous)
        progress.update(event=event, phase="REFRESH_RESEARCH")
        return progress, False, None
    if phase != "REVIEW":
        return pipeline.step(job, services, clock=clock, policy=policy, _research_stage=True)
    spot = services.spot(original["symbol"])
    current = services.current_trend(original, clock())
    now = clock()
    if now >= common.timestamp(original["deadline_at"]):
        return stop("ORIGINAL_DEADLINE_EXCEEDED", "EXPIRED")
    if services.scope_hash() != original["scope_hash"]:
        return stop("POLICY_OR_SCOPE_CHANGED")
    direction = 1 if original["right"] == "CALL" else -1
    try:
        age = (now - common.timestamp(spot["received_at"])).total_seconds()
        fresh = 0 <= age <= 3 and common.finite(spot.get("last"))
    except (KeyError, ValueError, TypeError):
        fresh = False
    if fresh and (direction * (spot["last"] - original["structure_line"]) <= 0
                  or not original["entry_range"][0] <= spot["last"] <= original["entry_range"][1]):
        return stop("STRUCTURE_OR_FIXED_ENTRY_RANGE_INVALIDATED")
    if current.get("state") == "TREND_CONFLICT":
        return stop("CURRENT_DAILY_TREND_CONFLICT")
    event = progress.get("event", {})
    decision = event.get("event_decision", {})
    if decision.get("decision") == "BLOCK":
        return stop("EVENT_KNOWN_MAJOR_RISK")
    comparisons = compare(original, progress.get("contracts", []), now=now, policy=policy)
    group = comparisons["groups"]["extended"]
    locked = progress.get("research_contract_id")
    reference = next((row for row in progress.get("contracts", []) if row.get("contract_id") == locked), None) if locked else (
        group.get("selected") or reference_from_inspections(original, progress.get("contracts", []), policy=policy))
    reasons = ["S1_RESEARCH_NOT_QUALIFIED_ENTRY"]
    if not fresh:
        reasons.append("UNDERLYING_QUOTE_UNAVAILABLE_OR_STALE")
    if current.get("state") != "VALID":
        reasons.append("CURRENT_INTRADAY_INPUT_UNVERIFIED")
    if decision.get("decision") not in {"PASS", "WARN"}:
        reasons.append("EVENT_REVIEW_OR_DATA_UNAVAILABLE")
    if reference:
        progress["research_contract_id"] = reference["contract_id"]
        reference = {**reference, "reference_only": True,
            "dte": (date.fromisoformat(reference["expiry_date"]) - date.fromisoformat(original["session"])).days}
    else:
        reasons.append(progress.get("collection_reason", "REFERENCE_CONTRACT_UNAVAILABLE"))
    progress["phase"] = "REFRESH_EVENT"
    return progress, False, dict(state="PENDING", checked_at=now.isoformat(), reasons=reasons,
        reference_contract=reference, reference_contract_status="UNVERIFIED_REFERENCE",
        contract_id=reference.get("contract_id") if reference else None,
        option_cost=cost_from_contract(reference, now=now) if reference else {"state": "REFERENCE_CONTRACT_UNAVAILABLE"},
        expiry_comparison=comparisons, event_decision=decision, current_trend=current,
        research_only=True, qualified_signal=False,
        approval={"qualified_signal_pipeline_enabled": False})
