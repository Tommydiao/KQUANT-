"""Read-only, separately approved same-day event evidence for the minute strategy."""
from datetime import timedelta

from . import options_one_minute as rules
from .market_clock import session_bounds_utc, is_trading_day
from .option_event_coverage_v3 import import_v3_review


def review_context(*, now, policy, scope_hash):
    day = now.astimezone(rules.NY).date()
    base = {"research_strategy": "one_minute", "policy_id": policy["policy_id"],
            "policy_hash": policy["policy_hash"], "scope_hash": scope_hash,
            "session": day.isoformat(), "as_of": now.isoformat(), "coverage_start": now.isoformat(),
            "approval": rules.approval_status(policy, scope_hash)}
    if not is_trading_day(day):
        return {**base, "state": "NON_TRADING_DAY", "can_submit": False}
    _, close = session_bounds_utc(day)
    end = close - timedelta(minutes=policy["planned_exit_minutes_before_close"])
    return {**base, "state": "OPEN" if now < end else "RISK_WINDOW_CLOSED",
            "can_submit": now < end and base["approval"]["event"]["exact_binding_accepted"],
            "coverage_end": end.isoformat(), "valid_until": close.isoformat()}


def import_review(db_path, payload, *, reviewer, now, policy, scope_hash):
    context = review_context(now=now, policy=policy, scope_hash=scope_hash)
    if payload.get("policy_hash") != policy["policy_hash"] or payload.get("scope_hash") != scope_hash:
        raise ValueError("REVIEW_POLICY_OR_SCOPE_CHANGED")
    if context["state"] != "OPEN":
        raise ValueError("SAME_DAY_REVIEW_WINDOW_CLOSED")
    start, end = rules.timestamp(payload["coverage_start"]), rules.timestamp(payload["coverage_end"])
    valid_until = rules.timestamp(payload["valid_until"])
    if (start.astimezone(rules.NY).date() != now.astimezone(rules.NY).date()
            or end > rules.timestamp(context["coverage_end"])
            or valid_until > rules.timestamp(context["valid_until"])):
        raise ValueError("REVIEW_MUST_USE_SAME_DAY_HORIZON")
    return import_v3_review(db_path, payload, reviewer=reviewer, now=now,
        policy_hash=policy["policy_hash"], scope_hash=scope_hash,
        approval_path=rules.EVENT_APPROVAL, proposal_path=rules.EVENT_PROPOSAL,
        event_policy_id="EVENT-COVERAGE-ONE-MINUTE-SAME-DAY-V1",
        minimum_horizon=rules.timestamp(context["coverage_end"]))
from .option_event_coverage_v3 import v3_event_context


def event_context(db_path, symbol, *, now, policy, scope_hash):
    opening, closing = session_bounds_utc(now.astimezone(rules.NY).date())
    end = closing - timedelta(minutes=30)
    if not opening <= now < end:
        return {"status": "OUTSIDE_SAME_DAY_RISK_WINDOW", "trade_eligible": False,
                "as_of": now.isoformat(), "coverage_until": end.isoformat(),
                "known_risk_state": "NOT_EVALUATED", "missing_categories": [],
                "blocking_events": []}
    return v3_event_context(
        db_path, symbol, now.isoformat(), until=end.isoformat(),
        policy_hash=policy["policy_hash"], scope_hash=scope_hash,
        approval_path=rules.EVENT_APPROVAL, proposal_path=rules.EVENT_PROPOSAL,
        event_policy_id="EVENT-COVERAGE-ONE-MINUTE-SAME-DAY-V1")
