"""Isolated same-day options research proposal. No live worker or execution authority."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import options_two_hour as rules
from .options_paper_engineering import select_contract
from .market_clock import session_bounds_utc

CONFIG = rules.ROOT / "config/options_intraday_research_v1.json"
STORE = rules.ROOT / "work/options_intraday/intraday.sqlite3"
EVENT_PROPOSAL = rules.ROOT / "config/options_intraday_event_coverage_v1.json"
EVENT_APPROVAL = rules.ROOT / "config/review_acceptances/options_intraday_event_o_setup_v1.json"
EVENT_POLICY_ID = "EVENT-COVERAGE-INTRADAY-HORIZON-V1"


def load_policy(path: Path = CONFIG) -> dict:
    policy = json.loads(path.read_text(encoding="utf-8"))
    base_path = rules.ROOT / "config" / policy["base_policy_file"]
    if hashlib.sha256(base_path.read_bytes()).hexdigest() != policy["base_policy_sha256"]:
        raise ValueError("BASE_POLICY_HASH_MISMATCH")
    if any(policy[key] for key in ("paper_enabled", "automatic_paper_enabled", "real_orders_enabled")):
        raise ValueError("RESEARCH_POLICY_CANNOT_ENABLE_EXECUTION")
    if policy["status"] != "PROPOSAL_ONLY_PENDING_O_SETUP":
        raise ValueError("INTRADAY_APPROVAL_NOT_BOUND")
    if policy["contract_selection"]["allowed_dtes"] != [0, 2, 3]:
        raise ValueError("INTRADAY_DTE_GROUPS_CHANGED")
    inherited = json.loads(base_path.read_text(encoding="utf-8"))
    policy["reference_contract_selection"] = {
        **inherited["contract_selection"], **policy["contract_selection"]
    }
    policy["policy_hash"] = rules.digest(policy)
    return policy


def session_times(schedule: dict, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    closing = rules.timestamp(schedule["regular_close_utc"])
    return {
        "entry_cutoff": rules.entry_cutoff(schedule, policy).isoformat(),
        "exit_reminder_at": (closing - timedelta(minutes=policy["exit_reminder_minutes_before_close"])).isoformat(),
        "planned_exit_by": (closing - timedelta(minutes=policy["planned_exit_minutes_before_close"])).isoformat(),
        "regular_close": closing.isoformat(),
    }


def event_horizon(schedule: dict, policy: dict | None = None) -> str:
    """Review only risk that can overlap the proposed same-day holding period."""
    return session_times(schedule, policy)["planned_exit_by"]


def event_context(db_path: Path, symbol: str, *, as_of: datetime, schedule: dict,
                  scope_hash: str, policy: dict | None = None) -> dict:
    from .option_event_coverage_v3 import v3_event_context
    policy = policy or load_policy()
    return v3_event_context(db_path, symbol, as_of.isoformat(),
        until=event_horizon(schedule, policy), policy_hash=policy["policy_hash"],
        scope_hash=scope_hash, approval_path=EVENT_APPROVAL,
        proposal_path=EVENT_PROPOSAL, event_policy_id=EVENT_POLICY_ID)


def required_slot_end(day, policy: dict | None = None) -> int:
    policy = policy or load_policy()
    opening, closing = session_bounds_utc(day)
    cutoff = rules.entry_cutoff({"regular_open_utc": opening.isoformat(),
                                 "regular_close_utc": closing.isoformat()}, policy)
    local = cutoff.astimezone(rules.NY)
    return local.hour * 60 + local.minute


def evaluate_pair(*, policy: dict | None = None, **kwargs) -> dict:
    """Evaluate exact inherited math, but never convert a proposal into an active signal."""
    policy = policy or load_policy()
    result = rules.evaluate_pair(policy=policy, **kwargs)
    result["rule_state"] = result["state"]
    if result["state"] == "RESEARCH_CANDIDATE":
        result["state"] = "PROPOSAL_ONLY_TRIGGER"
    result["policy_status"] = policy["status"]
    result["session_times"] = session_times(kwargs["schedule"], policy)
    result["paper_eligible"] = False
    result["real_orders_enabled"] = False
    return result


def select_reference_contracts(candidate: dict, contracts: list[dict], *, underlying_price: float,
                               policy: dict | None = None) -> dict:
    """Keep 0DTE and 2/3DTE separate; unknown sizes remain unqualified."""
    policy = policy or load_policy()
    base = policy["reference_contract_selection"]
    result = {}
    for name, allowed, target in (("SAME_DAY", [0], 0), ("TWO_THREE_DAY", [2, 3], 2)):
        selection = {**base, "allowed_dtes": allowed, "dte_min": min(allowed),
                     "dte_max": max(allowed), "dte_target": target}
        result[name] = select_contract(candidate, contracts, underlying_price=underlying_price,
            policy={"contract_selection": selection})
    return result


def exit_review(*, confirmed_entry_premium: float | None, current_bid: float | None,
                quote_received_at: datetime | None, has_recorded_position: bool,
                now: datetime, schedule: dict,
                policy: dict | None = None) -> dict:
    """A read-only review cue, never an order, fill, or automatic position close."""
    policy = policy or load_policy()
    times = session_times(schedule, policy)
    if not has_recorded_position:
        return {"state": "NO_RECORDED_POSITION", "reasons": [], "exit_confirmed": False,
                "policy_status": policy["status"]}
    now = rules.timestamp(now)
    if (not rules.finite(confirmed_entry_premium) or confirmed_entry_premium <= 0
            or not rules.finite(current_bid) or current_bid < 0 or quote_received_at is None
            or not timedelta(0) <= now - rules.timestamp(quote_received_at) <= timedelta(seconds=3)):
        return {"state": "PENDING_QUOTE_OR_ENTRY", "reasons": [], "exit_confirmed": False,
                "policy_status": policy["status"]}
    change = (current_bid - confirmed_entry_premium) / confirmed_entry_premium
    reasons = []
    if change <= -policy["research_exit_proposal"]["premium_loss_fraction"]:
        reasons.append("PREMIUM_LOSS_REVIEW")
    if change >= policy["research_exit_proposal"]["profit_review_fraction"]:
        reasons.append("PROFIT_REVIEW")
    if now >= rules.timestamp(times["exit_reminder_at"]):
        reasons.append("SAME_DAY_EXIT_REMINDER")
    if now >= rules.timestamp(times["planned_exit_by"]):
        reasons.append("PLANNED_EXIT_TIME_PASSED_UNCONFIRMED")
    return {"state": "REVIEW_REQUIRED" if reasons else "MONITORING", "reasons": reasons,
            "premium_change_fraction": change, "quote_basis": "CURRENT_BID_REFERENCE",
            "exit_confirmed": False, "session_times": times, "policy_status": policy["status"]}


def proposal_status(path: Path = STORE, *, now: datetime | None = None) -> dict:
    policy = load_policy()
    snapshot = rules.status(path, now=now, policy=policy)
    return {"status": "PROPOSAL_ONLY_PENDING_O_SETUP", "enabled": False,
            "policy": policy, "historical_readiness": snapshot.get("summary"),
            "store_status": snapshot["status"], "paper_enabled": False, "real_orders_enabled": False,
            "activation_gaps": ["O_SETUP_POLICY_HASH_NOT_ACCEPTED", "INTRADAY_EVENT_COVERAGE_NOT_APPROVED",
                                "AFTERNOON_HISTORY_NOT_PREWARMED", "CONTRACT_SIZE_UNVERIFIED",
                                "INTRADAY_WORKER_NOT_ATTACHED"],
            "as_of": (now or datetime.now(UTC)).isoformat()}
