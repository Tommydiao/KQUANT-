"""Same-checkpoint direction accounting, not a qualification or a backfill."""
from collections import Counter
from datetime import timedelta
import math
import sqlite3
import json

from . import options_one_minute as common
from . import options_opening_trend as trend
from .bounded_sqlite import read_connection
from .market_clock import is_trading_day, session_bounds_utc


def factor_grade(row):
    value=row.get('factor_evidence')
    if not isinstance(value,dict) or not value:
        return 'NONE'
    checks=value.get('checks')
    fields=('day_open','momentum','close_position','price','momentum_threshold','close_position_threshold')
    shape=(all(common.finite(value.get(name)) and not isinstance(value.get(name),bool) for name in fields)
           and value.get('day_open',0)>0 and value.get('price',0)>0
           and 'prior_boundary' in value and (value['prior_boundary'] is None or common.finite(value['prior_boundary']))
           and isinstance(value.get('reference'),dict) and isinstance(checks,dict)
           and all(type(checks.get(name)) is bool for name in ('momentum','close_position','prior_breakout')))
    if (shape and value.get('state')=='PARTIAL_PRICE_COMPONENTS'
            and 'previous_close' in value and value['previous_close'] is None and checks.get('daily_direction') is None):
        return 'PARTIAL_PRICE_COMPONENTS'
    if (shape and 'state' not in value and common.finite(value.get('previous_close'))
            and not isinstance(value['previous_close'],bool) and value['previous_close']>0
            and type(checks.get('daily_direction')) is bool
            and isinstance(value.get('auxiliary'),dict) and value['auxiliary'].get('role')=='AUXILIARY_ONLY'):
        return 'FULL'
    return 'NONE'


def complete_s0_factor(row):
    return factor_grade(row)=='FULL' and row.get('state') in {'NO_TRIGGER','NUMERIC_PASS','EXPIRED','WAIT_PULLBACK'}


def complete_numeric_factor(row, *, momentum):
    if momentum:
        return complete_s0_factor(row)
    value=row.get('factor_evidence')
    return (isinstance(value,dict) and row.get('state') in
            {'NO_TRIGGER','NUMERIC_PASS','EXPIRED','WAIT_PULLBACK'}
            and all(common.finite(value.get(name)) for name in
                    ('opening_high','opening_low','opening_width','day_open','previous_close','vwap','price'))
            and isinstance(value.get('trend_bar'),dict) and isinstance(value.get('reference'),dict))


def reconcile(registered, records, *, now, policy, scope_hash, observer_started_at=None):
    now = common.timestamp(now)
    day = now.astimezone(common.NY).date()
    base = {"session": day.isoformat(), "checked_at": now.isoformat(), "policy_hash": policy["policy_hash"],
            "checkpoint_minutes": sorted(set(policy.get("checkpoint_minutes") or
                policy["breakout_end_minutes"] + [policy["last_confirmation_minutes"]])),
            "scope_hash": scope_hash, "registered_directions": len(registered) * 2,
            "qualification_stages_checked_at": now.isoformat(),
            "checkpoints": [], "read_only": True, "qualified_signal_acceptance": False}
    observer = common.timestamp(observer_started_at) if observer_started_at else None
    base["observer_started_at"] = observer.isoformat() if observer else None
    base["coverage_boundary_state"] = "RECORDED" if observer else "LEGACY_BOUNDARY_UNRECORDED"
    if not is_trading_day(day):
        return {**base, "state": "NON_TRADING_DAY"}
    if not registered or not scope_hash:
        return {**base, "state": "SCOPE_UNAVAILABLE"}
    opening, closing = session_bounds_utc(day)
    cutoff = min(opening + timedelta(minutes=policy["entry_window_minutes"]), closing)
    expected = [opening + timedelta(minutes=m) for m in sorted(set(
        policy["breakout_end_minutes"] + [policy["last_confirmation_minutes"]]))]
    grouped, ignored = {}, Counter()
    momentum='checkpoint_minutes' in policy
    symbols = {r["symbol"] for r in registered}
    for row in records:
        if (row.get("policy_hash") != policy["policy_hash"] or row.get("scope_hash") != scope_hash
                or row.get("session") != day.isoformat()):
            ignored["other_version_scope_or_session"] += 1
            continue
        if row.get("symbol") not in symbols:
            ignored["unregistered_symbol"] += 1
            continue
        if row.get("state") in {"WAIT_TREND", "ENTRY_WINDOW_CLOSED"}:
            ignored["non_checkpoint_record"] += 1
            continue
        try:
            stamp = common.timestamp(row["evaluated_at"])
            end = common.timestamp(row["calculation_bar_end"])
            if row.get("computed_at") and common.timestamp(row["computed_at"]) > now:
                ignored["future_computation"] += 1
                continue
        except (ValueError, TypeError, KeyError, AttributeError):
            ignored["invalid_checkpoint_or_time"] += 1
            continue
        if stamp > now or end not in expected or row.get("right") not in {"CALL", "PUT"}:
            ignored["future_or_non_checkpoint"] += 1
            continue
        key = row["symbol"], row["right"], end
        grouped.setdefault(key, []).append(row)
    latencies, time_conflicts = [], 0
    for end in expected:
        if end > now:
            continue
        deadline = min(end + timedelta(seconds=policy["signal_deadline_seconds"]), cutoff)
        items, counts = [], Counter()
        for instrument in sorted(registered, key=lambda r: r["symbol"]):
            symbol = instrument["symbol"]
            for right in ("CALL", "PUT"):
                item = {"symbol": symbol, "right": right, "policy_id": policy["policy_id"], "bar_end": end.isoformat()}
                rows = sorted(grouped.get((symbol, right, end), []),
                              key=lambda r: (common.timestamp(r["evaluated_at"]), r["evaluation_id"]))
                if observer and end < observer:
                    item.update(state="PRE_DEPLOYMENT", reasons=["CHECKPOINT_PRECEDES_RECORDED_OBSERVER_BOUNDARY"])
                    counts["pre_deployment_directions"] += 1
                elif instrument.get("identity_status") != "verified":
                    item.update(state="IDENTITY_UNRESOLVED", reasons=["REGISTERED_IDENTITY_NOT_VERIFIED"])
                    counts["identity_excluded_directions"] += 1
                elif not rows:
                    item.update(state="MISSING_EVALUATION" if now >= deadline else "PENDING_EVALUATION",
                                reasons=["NO_PERSISTED_CHECKPOINT_EVALUATION"])
                    counts["missing_directions" if now >= deadline else "pending_directions"] += 1
                else:
                    first, latest = rows[0], rows[-1]
                    numeric = next((r for r in rows if complete_numeric_factor(r,momentum=momentum)), None)
                    item.update(evaluation_id=latest["evaluation_id"], state=latest["state"],
                                reasons=latest.get("reasons", []), evaluated_at=latest["evaluated_at"],
                                first_evaluation_id=first["evaluation_id"], first_state=first["state"],
                                first_evaluated_at=first["evaluated_at"], evaluation_records=len(rows),
                                first_numeric_evaluation_id=numeric["evaluation_id"] if numeric else None)
                    counts["evaluated_directions"] += 1
                    counts['factor_'+factor_grade(latest)] += 1
                    counts["numeric_directions" if numeric else "explicitly_incomplete_directions"] += 1
                    if any(complete_numeric_factor(r,momentum=momentum) and r["state"] in {"NUMERIC_PASS", "EXPIRED"} for r in rows):
                        counts["setup_triggered_directions"] += 1
                    if common.timestamp(first["evaluated_at"]) >= deadline:
                        counts["late_first_directions"] += 1
                    if numeric and numeric.get("input_received_at") and numeric.get("computed_at"):
                        delta = (common.timestamp(numeric["computed_at"]) - common.timestamp(numeric["input_received_at"])).total_seconds()
                        if math.isfinite(delta) and delta >= 0:
                            latencies.append(delta)
                        else:
                            time_conflicts += 1
                items.append(item)
        values = {key: counts[key] for key in ("identity_excluded_directions", "missing_directions", "pending_directions",
                  "evaluated_directions", "numeric_directions", "explicitly_incomplete_directions", "late_first_directions", "pre_deployment_directions")}
        values['factor_grades']={name:counts['factor_'+name] for name in ('NONE','PARTIAL_PRICE_COMPONENTS','FULL')}
        base["checkpoints"].append({"bar_end": end.isoformat(), "original_deadline": deadline.isoformat(),
            "deadline_elapsed": now >= deadline, "registered_directions": len(items), **values, "items": items,
            "pipeline_stages": {
                "registered": {"state": "COUNTED", "directions": len(items)},
                "input_complete": {"state": "COUNTED" if counts["evaluated_directions"] else "NOT_RUN",
                                   "directions": counts["numeric_directions"] if counts["evaluated_directions"] else None},
                "numeric_complete": {"state": "COUNTED" if counts["evaluated_directions"] else "NOT_RUN",
                                     "directions": counts["numeric_directions"] if counts["evaluated_directions"] else None},
                "setup_triggered": {"state": "COUNTED" if counts["numeric_directions"] else "NOT_RUN",
                                    "directions": counts["setup_triggered_directions"] if counts["numeric_directions"] else None},
                **{key: {"state": "NOT_RUN", "directions": None} for key in
                   ("event_passed", "contract_passed", "actionable")}}})
    ordered = sorted(latencies)
    index = .95 * (len(ordered) - 1) if ordered else 0
    low = math.floor(index)
    p95 = ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (index - low) if len(ordered) >= 20 else None
    base["latency"] = {"scope": "COMPLETE_NUMERIC_INPUT_RECEIPT_TO_COMPUTATION", "sample_count": len(ordered),
                       "p95_seconds": p95, "time_conflict_samples": time_conflicts,
                       "state": "ESTIMATE_ONLY" if p95 is not None else "INSUFFICIENT_SAMPLES"}
    base["ignored_records"] = dict(ignored)
    points = base["checkpoints"]
    base["state"] = ("WAIT_FIRST_CHECKPOINT" if not points else "SYSTEM_GAPS" if any(p["missing_directions"] for p in points)
        else "PARTIAL_OBSERVATION" if any(p["pre_deployment_directions"] for p in points)
        else "NO_COMPLETE_NUMERIC_EVIDENCE" if not sum(p["numeric_directions"] for p in points)
        else "WINDOW_ACCOUNTED_NOT_SIGNAL_ACCEPTANCE" if now >= cutoff else "PARTIAL_WINDOW")
    return base


def qualification_stages(path, *, session, policy_hash, scope_hash, now):
    """Latest persistent qualification per checkpoint direction; never run the SDK."""
    try:
        with read_connection(path, seconds=.2) as db:
            rows = db.execute("""SELECT e.symbol,e.right_name,
                json_extract(e.payload_json,'$.scope_hash','$.calculation_bar_end','$.deadline_at'),
                json_extract(r.payload_json,'$.event_coverage.trade_eligible','$.event_coverage.status',
                    '$.contract_qualification.status','$.expiry_comparison.groups',
                    '$.state','$.checked_at','$.valid_until','$.underlying_quote.received_at',
                    '$.approval.qualified_signal_pipeline_enabled','$.contract_source_check.status',
                    '$.event_decision.decision'),r.revision_id,
                EXISTS(SELECT 1 FROM qualified_claims q WHERE q.evaluation_id=e.evaluation_id)
                FROM evaluations e JOIN revisions r ON r.revision_id=(SELECT MAX(revision_id)
                    FROM revisions WHERE evaluation_id=e.evaluation_id)
                WHERE e.policy_hash=? AND e.session=? AND e.state='NUMERIC_PASS' LIMIT 12001""",
                (policy_hash, session)).fetchall()
        if len(rows) > 12000:
            raise ValueError("QUALIFICATION_RECORD_BOUND_EXCEEDED")
        latest = {}
        for symbol, right, identity, evidence, revision, claimed in rows:
            scope, end, deadline = json.loads(identity)
            if scope != scope_hash:
                continue
            proof = json.loads(evidence)
            if not proof[5] or common.timestamp(proof[5]) > now:
                continue
            key = symbol, right, end
            if key not in latest or revision > latest[key][0]:
                latest[key] = revision, deadline, proof, claimed
        points = {}
        for (_, _, end), (_, deadline, proof, claimed) in latest.items():
            event_ok, event_status, contract_status, comparison, state, checked, valid_until, quote_at, approved, source_status, event_decision = proof
            counts = points.setdefault(end, Counter())
            if event_status is not None or event_ok is not None:
                counts["event_evaluated"] += 1
                counts["event_passed"] += event_decision == "PASS" if event_decision else event_ok is True or event_ok == 1
                counts["event_warned"] += event_decision == "WARN"
                counts["event_allowed"] += event_decision in {"PASS", "WARN"} if event_decision else event_ok is True or event_ok == 1
            if contract_status not in (None, "NOT_RUN") or comparison:
                counts["contract_evaluated"] += 1
                counts["contract_passed"] += contract_status == "PASS" and source_status == "PASS"
            counts["qualification_evaluated"] += 1
            fresh = bool(claimed and approved and (event_decision in {"PASS", "WARN"} if event_decision else event_ok == 1) and contract_status == "PASS" and source_status == "PASS"
                and state == "QUALIFIED" and valid_until and quote_at
                and common.timestamp(checked) <= now < common.timestamp(valid_until)
                and now < common.timestamp(deadline)
                and 0 <= (now-common.timestamp(quote_at)).total_seconds() <= 3)
            counts["actionable"] += fresh
        return {"state": "AVAILABLE", "checked_at": now.isoformat(), "checkpoints": {
            end: {key: {"state": "COUNTED" if counts[evaluated] else "NOT_RUN",
                        "directions": counts[key] if counts[evaluated] else None}
                  for key, evaluated in (("event_passed", "event_evaluated"), ("event_warned", "event_evaluated"),
                     ("event_allowed", "event_evaluated"),
                     ("contract_passed", "contract_evaluated"), ("actionable", "qualification_evaluated"))}
            for end, counts in points.items()}}
    except (sqlite3.Error, TimeoutError, ValueError, TypeError, KeyError):
        return {"state": "UNAVAILABLE", "checked_at": now.isoformat(), "checkpoints": {}}


def attach_qualification_stages(coverage, stages):
    for point in coverage.get("checkpoints", []):
        if stages["state"] == "UNAVAILABLE":
            point["pipeline_stages"].update({key: {"state": "UNAVAILABLE", "directions": None}
                for key in ("event_passed", "contract_passed", "actionable")})
        else:
            point["pipeline_stages"].update(stages["checkpoints"].get(point["bar_end"], {}))
    coverage["qualification_stages_checked_at"] = stages["checked_at"]
    return coverage


def audit(path, registered, *, now, scope_hash, policy=None, seconds=.4, observer_started_at=None):
    policy = policy or trend.load_policy()
    session = common.timestamp(now).astimezone(common.NY).date().isoformat()
    try:
        with read_connection(path, seconds=seconds) as db:
            rows = db.execute("""SELECT evaluation_id,policy_hash,session,symbol,right_name,evaluated_at,state,
                json_extract(payload_json,'$.scope_hash','$.calculation_bar_end','$.reasons',
                    '$.calculation_input_received_at','$.computed_at'),json_extract(payload_json,'$.factor_evidence')
                FROM evaluations WHERE policy_hash=? AND session=? LIMIT 12001""",
                (policy["policy_hash"], session)).fetchall()
        if len(rows) > 12000:
            raise ValueError("CHECKPOINT_RECORD_BOUND_EXCEEDED")
        names = ("evaluation_id", "policy_hash", "session", "symbol", "right", "evaluated_at", "state")
        evidence_names = ("scope_hash", "calculation_bar_end", "reasons", "input_received_at", "computed_at")
        records = []
        for values in rows:
            row = dict(zip(names, values[:7]))
            row.update(zip(evidence_names, json.loads(values[7])))
            row["reasons"] = row["reasons"] or []
            row['factor_evidence']=json.loads(values[8]) if values[8] else None
            records.append(row)
        result = reconcile(registered, records, now=now, policy=policy, scope_hash=scope_hash,
            observer_started_at=observer_started_at)
        return attach_qualification_stages(result, qualification_stages(path, session=session,
            policy_hash=policy["policy_hash"], scope_hash=scope_hash, now=common.timestamp(now)))
    except (sqlite3.Error, TimeoutError, ValueError, TypeError, KeyError) as exc:
        return {"state": "UNAVAILABLE", "session": session, "checked_at": common.timestamp(now).isoformat(),
                "error_type": type(exc).__name__, "registered_directions": len(registered) * 2,
                "checkpoints": [], "read_only": True, "qualified_signal_acceptance": False}
