"""New strategy's event horizon, without transferring old policy approvals."""
from pathlib import Path

from . import options_one_minute as common
from . import options_opening_trend as trend
from .market_clock import is_trading_day, session_bounds_utc

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / "config/options_opening_trend_event_coverage_v2.json"
APPROVAL = ROOT / "config/review_acceptances/options_opening_trend_event_o_setup_v2.json"


def policy_paths(policy):
    if policy["policy_id"] == "STRAT-OPENING-MOMENTUM-5M-V1":
        return (ROOT / "config/options_opening_momentum_event_coverage_v1.json",
                ROOT / "config/review_acceptances/options_opening_momentum_event_o_setup_v1.json")
    return PROPOSAL, APPROVAL


def review_context(*, now, policy, scope_hash):
    from .option_event_coverage_v3 import _approval
    now = common.timestamp(now)
    day = now.astimezone(common.NY).date()
    proposal, approval = policy_paths(policy)
    accepted = _approval(policy["policy_hash"], scope_hash, approval,
                         proposal_path=proposal, event_policy_id=policy["event_policy_id"])
    base = {"research_strategy": "opening_momentum" if policy["policy_id"] == "STRAT-OPENING-MOMENTUM-5M-V1" else "opening_trend", "policy_id": policy["policy_id"],
            "policy_hash": policy["policy_hash"], "scope_hash": scope_hash, "session": day.isoformat(),
            "as_of": now.isoformat(), "coverage_start": now.isoformat(),
            "event_binding_accepted": accepted is not None}
    if not is_trading_day(day):
        return {**base, "state": "NON_TRADING_DAY", "can_submit": False}
    opening, closing = session_bounds_utc(day)
    # Before entry, cover the maximum allowed same-day horizon, not four hours
    # from the earlier review time. Individual positions may have a shorter end.
    end = common.timestamp(trend.exit_times(opening, closing, policy=policy)["planned_exit_at"])
    return {**base, "state": "OPEN" if now < end else "RISK_WINDOW_CLOSED",
            "can_submit": now < end and accepted is not None,
            "coverage_end": end.isoformat(), "valid_until": closing.isoformat()}


def import_review(db_path, payload, *, reviewer, now, policy, scope_hash):
    from .option_event_coverage_v3 import import_v3_review
    now = common.timestamp(now)
    context = review_context(now=now, policy=policy, scope_hash=scope_hash)
    if payload.get("policy_hash") != policy["policy_hash"] or payload.get("scope_hash") != scope_hash:
        raise ValueError("REVIEW_POLICY_OR_SCOPE_CHANGED")
    if payload.get("session") != context["session"]:
        raise ValueError("REVIEW_SESSION_CHANGED")
    if context["state"] != "OPEN":
        raise ValueError("TREND_REVIEW_WINDOW_CLOSED")
    start, end = common.timestamp(payload["coverage_start"]), common.timestamp(payload["coverage_end"])
    valid_until = common.timestamp(payload["valid_until"])
    if (start.astimezone(common.NY).date().isoformat() != context["session"]
            or end > common.timestamp(context["coverage_end"])
            or valid_until > common.timestamp(context["valid_until"])):
        raise ValueError("REVIEW_MUST_USE_TREND_SAME_DAY_HORIZON")
    proposal, approval = policy_paths(policy)
    return import_v3_review(db_path, payload, reviewer=reviewer, now=now,
        policy_hash=policy["policy_hash"], scope_hash=scope_hash,
        approval_path=approval, proposal_path=proposal, event_policy_id=policy["event_policy_id"],
        minimum_horizon=common.timestamp(context["coverage_end"]))


def event_context(db_path, symbol, *, now, policy, scope_hash, entered=None, reader=None):
    combine_automatic = reader is None
    if reader is None:
        from .option_event_coverage_v3 import v3_event_context
        reader = v3_event_context
    now = common.timestamp(now)
    day = now.astimezone(common.NY).date()
    if not is_trading_day(day):
        return {"trade_eligible": False, "status": "NON_TRADING_DAY", "as_of": now.isoformat(),
                "known_risk_state": "NOT_EVALUATED"}
    opening, closing = session_bounds_utc(day)
    end = common.timestamp(trend.exit_times(opening, closing, entered or now, policy)["planned_exit_at"])
    if not opening <= now < end:
        return {"trade_eligible": False, "status": "OUTSIDE_PLANNED_RISK_WINDOW",
                "as_of": now.isoformat(), "coverage_until": end.isoformat()}
    proposal, approval = policy_paths(policy)
    human = reader(db_path, symbol, now.isoformat(), until=end.isoformat(),
                  policy_hash=policy["policy_hash"], scope_hash=scope_hash,
                  approval_path=approval, proposal_path=proposal,
                  event_policy_id=policy["event_policy_id"])
    if not combine_automatic:
        return human
    return combine_sources(db_path, symbol, now=now, end=end, policy=policy, scope_hash=scope_hash, human=human)


def combine_sources(db_path, symbol, *, now, end, policy, scope_hash, human):
    from .option_event_coverage_v3 import _approval
    from .options_opening_trend_event_auto import automatic_context, combined_context
    proposal, approval_path = policy_paths(policy)
    approval = _approval(policy["policy_hash"], scope_hash, approval_path,
                         proposal_path=proposal, event_policy_id=policy["event_policy_id"])
    automatic = automatic_context(db_path, symbol, now=now, horizon=end,
                                  policy_hash=policy["policy_hash"], scope_hash=scope_hash, approval=approval)
    from .options_opening_trend_event_decision import decide
    result = combined_context(human, automatic)
    result["event_decision"] = decide(result, now=now, horizon=end)
    return result


def automatic_diagnostics(db_path, symbol, *, now, policy, scope_hash):
    """A pre-open evidence read, never an authorization or an SDK request."""
    from .option_event_coverage_v3 import _approval
    from .options_opening_trend_event_auto import automatic_context
    context = review_context(now=now, policy=policy, scope_hash=scope_hash)
    if context["state"] != "OPEN":
        return {"status": context["state"], "trade_eligible": False, "human_review_writes": 0,
                "category_states": {name: {"state": "NOT_EVALUATED", "reasons": [context["state"]]}
                                    for name in ("earnings", "dividends", "corporate", "macro")}}
    proposal, approval_path = policy_paths(policy)
    approval = _approval(policy["policy_hash"], scope_hash, approval_path,
                         proposal_path=proposal, event_policy_id=policy["event_policy_id"])
    return automatic_context(db_path, symbol, now=now, horizon=common.timestamp(context["coverage_end"]),
                              policy_hash=policy["policy_hash"], scope_hash=scope_hash, approval=approval)
