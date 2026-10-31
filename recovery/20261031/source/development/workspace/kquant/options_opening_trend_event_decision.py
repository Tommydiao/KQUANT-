"""Separate incomplete coverage from concrete risk; never manufacture CLEAR."""
from copy import deepcopy
from datetime import timedelta

from . import options_one_minute as common

POLICY_ID = "EVENT-RISK-OPENING-TREND-GRADED-V2"
MAJOR_TYPES = frozenset({"EARNINGS", "FOMC_RATE_DECISION", "FOMC_PRESS_CONFERENCE",
                         "US_CPI", "US_EMPLOYMENT_REPORT"})


def _events(context):
    if not isinstance(context, dict):
        return
    for key in ("blocking_events", "unresolved_events", "events"):
        for row in context.get(key, []) or []:
            if isinstance(row, dict):
                yield {**row, "explicit_blocker": key == "blocking_events"
                       or row.get("disposition") == "KNOWN_BLOCKER"}
    for category, state in (context.get("category_states") or {}).items():
        if isinstance(state, dict):
            for row in state.get("events", []) or []:
                if isinstance(row, dict):
                    yield {"category": category, **row,
                           "explicit_blocker": row.get("disposition") == "KNOWN_BLOCKER"}
    for key in ("automatic_coverage", "human_coverage"):
        yield from _events(context.get(key))


def decide(context, *, now, horizon, previous=None):
    now, horizon = common.timestamp(now), common.timestamp(horizon)
    context = context if isinstance(context, dict) else {}
    blocked, review, background, refs, seen = [], [], [], [], set()
    # A failed refresh cannot erase a previously observed risk. Only its known
    # end passing removes it; unresolved timing stays unresolved.
    prior = previous if isinstance(previous, dict) else {}
    candidates = [*_events(context), *deepcopy(prior.get("blocking_events", [])),
                  *deepcopy(prior.get("review_events", []))]
    for event in candidates:
        key = common.digest({k: event.get(k) for k in
                             ("id", "category", "name", "start_at", "end_at", "raw_datetime", "source_hash")})
        if key in seen:
            continue
        seen.add(key)
        source = event.get("source_hash") or event.get("source_url")
        if source:
            refs.append(source)
        major = event.get("event_type") in MAJOR_TYPES or event.get("category") == "earnings"
        concrete_macro = event.get("category") == "macro" and bool(event.get("name"))
        explicit = event.get("explicit_blocker") or event.get("disposition") == "KNOWN_BLOCKER"
        try:
            start = common.timestamp(event["start_at"])
            end = common.timestamp(event.get("end_at") or event["start_at"])
            if end < start:
                raise ValueError("EVENT_TIME_ORDER_INVALID")
            overlaps = end >= now and start <= horizon
        except (KeyError, TypeError, ValueError, AttributeError):
            if major or concrete_macro or explicit:
                review.append({**event, "decision_reason": "IMPORTANT_EVENT_TIME_UNVERIFIED"})
            else:
                background.append(event)
            continue
        if not overlaps:
            background.append(event)
        elif not source or event.get("applicability") == "UNKNOWN":
            if major or concrete_macro or explicit:
                review.append({**event, "decision_reason": "IMPORTANT_EVENT_SOURCE_OR_ASSET_UNVERIFIED"})
            else:
                background.append(event)
        elif explicit or major:
            blocked.append({**event, "explicit_blocker": True})
        elif concrete_macro:
            # Generic macro descriptions are not classified by keyword guessing.
            review.append({**event, "decision_reason": "IMPORTANT_MACRO_TYPE_UNVERIFIED"})
        else:
            background.append(event)
    fresh = False
    try:
        age = (now - common.timestamp(context["as_of"])).total_seconds()
        fresh = (0 <= age < 900 and now < common.timestamp(context["valid_until"]))
    except (KeyError, ValueError, TypeError, AttributeError):
        pass
    covered = fresh and context.get("trade_eligible") is True
    warnings = [] if covered else ["EVENT_COVERAGE_INCOMPLETE_OR_STALE"]
    if background:
        warnings.append("EVENT_BACKGROUND_INFORMATION")
    state = "BLOCK" if blocked else "REVIEW" if review else "PASS" if covered else "WARN"
    result = {"policy_id": POLICY_ID, "decision": state, "entry_allowed": state in {"PASS", "WARN"},
              "coverage_status": "VERIFIED_AS_OF" if covered else "INCOMPLETE_OR_STALE",
              "known_risk_state": "KNOWN_BLOCKER" if blocked else "UNRESOLVED" if review
                  else "NO_KNOWN_BLOCKER_IN_REVIEWED_SOURCES" if covered else "UNKNOWN",
              "warnings": warnings, "blocking_events": blocked, "review_events": review,
              "background_events": background, "source_refs": sorted(set(refs)),
              "checked_at": now.isoformat(), "coverage_as_of": context.get("as_of"),
              "coverage_until": horizon.isoformat(), "valid_until": (now + timedelta(seconds=60)).isoformat(),
              "review_method": "AUTOMATED_GRADED_RISK_DECISION", "human_review_writes": 0}
    result["evidence_id"] = common.digest(result)
    return result
