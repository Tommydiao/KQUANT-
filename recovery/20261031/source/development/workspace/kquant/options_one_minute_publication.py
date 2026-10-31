"""Atomic first-qualified claims and replayable links to existing signal storage."""
import json
import sqlite3
from pathlib import Path
from datetime import timedelta
from urllib.parse import urlencode

from . import options_one_minute as rules
from .options_one_minute_events import event_context
from .options_one_minute_qualification import select_contract, publication_blockers
from .options_signal_copilot import create_signal, DEFAULT_STORE_PATH


def claim_candidate(result, *, main_db, evidence_path, now, scope_hash):
    policy = rules.load_policy()
    if not rules.approval_status(policy, scope_hash)["qualified_signal_pipeline_enabled"]:
        return None
    if result.get("qualification_blockers") or not result.get("parent_evaluation_id"):
        return None
    event = event_context(main_db, result["symbol"], now=now, policy=policy, scope_hash=scope_hash)
    selection = select_contract(result, result.get("contract_qualification", {}).get("evidence", []), now=now, policy=policy)
    spot = result.get("underlying_qualification_quote", {})
    blockers = publication_blockers(result, now=now, policy=policy, scope_hash=scope_hash, event=event,
        selection=selection, spot=spot.get("last"), spot_received_at=spot.get("received_at"))
    if blockers:
        return None
    candidate = {**result, "state": "QUALIFIED_SIGNAL", "qualified_signal": True,
        "contract_id": selection["selected"]["contract_id"], "contract_qualification": selection,
        "qualification_event_coverage": event, "claimed_at": now.isoformat()}
    from .options_one_minute_eligibility import evaluate as evaluate_current
    initial = evaluate_current(candidate, now=now, policy=policy, scope_hash=scope_hash,
        event=event, contract=selection["selected"], spot=spot, approved=True)
    if initial["state"] != "QUALIFIED":
        return None
    candidate["initial_eligibility"] = initial
    with sqlite3.connect(evidence_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        changed = connection.execute("INSERT OR IGNORE INTO one_minute_candidates VALUES (?,?,?,?,?)",
            (candidate["event_id"], candidate["evaluation_id"], candidate["session"], now.isoformat(), rules.canonical(candidate))).rowcount
    return candidate if changed else None


def reconcile_signals(evidence_path, *, store_path=DEFAULT_STORE_PATH, event_id=None):
    """Recover signal links after a crash without re-claiming or extending validity."""
    with sqlite3.connect(f"file:{Path(evidence_path).resolve().as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT payload_json FROM one_minute_candidates WHERE (? IS NULL OR event_id=?) ORDER BY published_at", (event_id, event_id)).fetchall()
    linked = []
    for raw, in rows:
        row = json.loads(raw)
        signal = create_signal({
            "signal_id": "one-minute-" + row["event_id"], "source": "FROZEN_RULE", "state": "REVIEW_READY",
            "strategy_id": row["policy_id"], "strategy_hash": row["policy_hash"], "scope_hash": row["scope_hash"],
            "economic_opportunity_id": row["event_id"], "evaluation_id": row["evaluation_id"],
            "symbol": row["symbol"], "right": row["right"], "contract_id": row["contract_id"],
            "observed_at": row["bar_end"], "valid_until": row["deadline_at"],
            "evidence_refs": ["one_minute_evaluation:" + row["evaluation_id"]],
            "rule_evidence": row["factor_evidence"], "contract_qualification": row["contract_qualification"],
            "event_coverage": row["qualification_event_coverage"],
            "paper_enabled": False, "real_orders_enabled": False}, store_path=store_path)
        if row.get("initial_eligibility"):
            from .signal_eligibility import append_revision
            append_revision(store_path, "one-minute-" + row["event_id"], row["initial_eligibility"])
        linked.append(signal)
    return linked


def queue_notification(candidate, *, main_db, now, scope_hash):
    from .stock_store import connect
    policy = rules.load_policy()
    if not rules.approval_status(policy, scope_hash)["qualified_signal_pipeline_enabled"]:
        return "PENDING_APPROVAL"
    if candidate["policy_hash"] != policy["policy_hash"] or candidate["scope_hash"] != scope_hash:
        return "CONFIG_CHANGED"
    selected = candidate.get("contract_qualification", {}).get("selected") or {}
    try:
        evidence_until = min(rules.timestamp(candidate["deadline_at"]),
            rules.timestamp(candidate["underlying_qualification_quote"]["received_at"]) + timedelta(seconds=3),
            rules.timestamp(selected["snapshot"]["bbo_received_at"]) + timedelta(seconds=3))
    except (KeyError, TypeError, ValueError):
        return "QUOTE_TIME_MISSING"
    if now >= evidence_until:
        return "REFERENCE_EVIDENCE_EXPIRED"
    alert_id = "one-minute-" + candidate["event_id"]
    payload = {"type": "options_one_minute_research", "severity": "INFO", "qualified": True,
        "event_id": candidate["event_id"], "signal_id": alert_id, "symbol": candidate["symbol"],
        "right": candidate["right"], "contract_id": candidate["contract_id"], "session": candidate["session"],
        "policy_hash": candidate["policy_hash"], "scope_hash": scope_hash,
        "bar_end": candidate["bar_end"], "deadline_at": candidate["deadline_at"],
        "eligibility_valid_until": evidence_until.isoformat(),
        "title": "KQUANT research signal", "body": candidate["symbol"] + " " + candidate["right"],
        "url": "/?" + urlencode({"workspace": "options", "view": "signals", "symbol": candidate["symbol"],
                                  "evaluation": candidate["evaluation_id"]}),
        "paper_enabled": False, "real_orders_enabled": False}
    stamp = now.isoformat()
    with connect(main_db) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT 1 FROM option_delivery_outbox WHERE alert_id=?", (alert_id,)).fetchone():
            return "ALREADY_QUEUED"
        connection.execute("""INSERT OR IGNORE INTO alert_events
            (alert_id,instruction_id,dedupe_key,symbol,severity,event_type,title,message,payload_json,
             delivery_status,acknowledged_at,created_at,updated_at)
            VALUES (?,NULL,?,?,'INFO','options_one_minute_research',?,?,?,'web_queued',NULL,?,?)""",
            (alert_id, alert_id, candidate["symbol"], payload["title"], payload["body"], rules.canonical(payload), stamp, stamp))
        connection.execute("INSERT OR IGNORE INTO option_delivery_outbox VALUES (?,'queued',?,?,?,'{}')",
            (alert_id, rules.canonical(payload), stamp, stamp))
    return "QUEUED_DEVICE_UNVERIFIED"


def reserve_notification(alert_id, *, main_db, now):
    """Reserve at dispatch, not enqueue; uncertain sends retain their daily slot."""
    from .stock_store import connect
    limit = rules.load_policy()["entry_notifications_per_session"]
    with connect(main_db) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM option_delivery_outbox WHERE alert_id=?", (alert_id,)).fetchone()
        if row is None:
            return "NOT_FOUND"
        payload = json.loads(row["payload_json"])
        if payload.get("type") != "options_one_minute_research":
            return "NOT_MINUTE_ENTRY"
        if row["status"] == "sending":
            if (now - rules.timestamp(row["updated_at"])).total_seconds() > 30:
                connection.execute("UPDATE option_delivery_outbox SET status='delivery_unknown',result_json=?,updated_at=? WHERE alert_id=?",
                    (rules.canonical({"reason": "interrupted_send_requires_reconciliation", "device_display_verified": False}), now.isoformat(), alert_id))
                return "DELIVERY_UNKNOWN"
            return "DELIVERY_IN_FLIGHT"
        if row["status"] not in {"queued", "deferred"}:
            return "ALREADY_HANDLED"
        sent = connection.execute("SELECT 1 FROM alert_delivery_attempts WHERE alert_id=? AND status='sent' LIMIT 1", (alert_id,)).fetchone()
        if sent:
            connection.execute("UPDATE option_delivery_outbox SET status='sent',updated_at=? WHERE alert_id=?", (now.isoformat(), alert_id))
            return "ALREADY_SENT"
        count = connection.execute("""SELECT COUNT(*) FROM option_delivery_outbox o
            WHERE json_extract(o.payload_json,'$.type')='options_one_minute_research'
              AND json_extract(o.payload_json,'$.session')=?
              AND (o.status IN ('sending','sent','partial','delivery_unknown') OR EXISTS
                (SELECT 1 FROM alert_delivery_attempts a WHERE a.alert_id=o.alert_id AND a.status='sent'))""",
            (payload["session"],)).fetchone()[0]
        if count >= limit:
            connection.execute("UPDATE option_delivery_outbox SET status='deferred',result_json=?,updated_at=? WHERE alert_id=?",
                (rules.canonical({"reason": "minute_entry_session_limit", "sent_or_reserved": count, "limit": limit}), now.isoformat(), alert_id))
            return "SESSION_NOTIFICATION_LIMIT"
        connection.execute("UPDATE option_delivery_outbox SET status='sending',result_json=?,updated_at=? WHERE alert_id=?",
            (rules.canonical({"reserved_at": now.isoformat(), "device_display_verified": False}), now.isoformat(), alert_id))
        return "RESERVED"


def notification_authorized(payload, *, main_db, now):
    from .options_one_minute_data import universe
    try:
        policy = rules.load_policy()
        scope_hash = universe(main_db)["scope_hash"]
        return (payload.get("qualified") is True
                and payload.get("policy_hash") == policy["policy_hash"]
                and payload.get("scope_hash") == scope_hash
                and rules.approval_status(policy, scope_hash)["qualified_signal_pipeline_enabled"]
                and now < rules.timestamp(payload["deadline_at"])
                and now < rules.timestamp(payload["eligibility_valid_until"])
                and event_context(main_db, payload["symbol"], now=now, policy=policy,
                                  scope_hash=scope_hash).get("trade_eligible") is True)
    except (KeyError, TypeError, ValueError, OSError, sqlite3.Error):
        return False
