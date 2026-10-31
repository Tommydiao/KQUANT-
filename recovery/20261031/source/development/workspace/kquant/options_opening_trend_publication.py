"""Recover immutable research signal links in the existing Copilot signal store."""
import json
import sqlite3
from contextlib import closing


def reconcile(path, *, now, signal_store=None):
    from .options_signal_copilot import create_signal, DEFAULT_STORE_PATH
    linked = []
    with closing(sqlite3.connect(path, timeout=.2)) as c:
        rows = c.execute("""SELECT q.event_id,q.payload_json,r.revision_id,r.payload_json
          FROM qualified_claims q
          JOIN revisions r ON r.revision_id=(SELECT MAX(revision_id) FROM revisions WHERE evaluation_id=q.evaluation_id)
          LEFT JOIN publication_offsets o ON o.event_id=q.event_id
          WHERE q.linked_at IS NULL OR r.revision_id>COALESCE(o.revision_id,0)
          ORDER BY q.published_at LIMIT 20""").fetchall()
    for event_id, raw, revision_id, revision_raw in rows:
        row = json.loads(raw)
        create_signal({"signal_id": "opening-trend-" + event_id, "source": "FROZEN_RULE", "state": "REVIEW_READY",
            "strategy_id": row["policy_id"], "strategy_hash": row["policy_hash"], "scope_hash": row["scope_hash"],
            "economic_opportunity_id": event_id, "evaluation_id": row["evaluation_id"], "symbol": row["symbol"],
            "right": row["right"], "contract_id": row["contract_id"], "observed_at": row["confirmation_at"],
            "valid_until": row["deadline_at"], "evidence_refs": ["opening_trend_evaluation:" + row["evaluation_id"]],
            "rule_evidence": row["factor_evidence"], "contract_qualification": row["contract_qualification"],
            "event_coverage": row["event_coverage"], "paper_enabled": False, "real_orders_enabled": False},
            store_path=signal_store or DEFAULT_STORE_PATH)
        from .signal_eligibility import append_revision
        current = json.loads(revision_raw)
        current["state"] = {"PENDING": "WAITING_EVIDENCE", "WITHDRAWN": "REVOKED"}.get(current["state"], current["state"])
        append_revision(signal_store or DEFAULT_STORE_PATH, "opening-trend-" + event_id, current)
        with closing(sqlite3.connect(path, timeout=.2)) as c, c:
            c.execute("UPDATE qualified_claims SET linked_at=? WHERE event_id=? AND linked_at IS NULL", (now.isoformat(), event_id))
            c.execute("""INSERT INTO publication_offsets VALUES (?,?)
              ON CONFLICT(event_id) DO UPDATE SET revision_id=MAX(revision_id,excluded.revision_id)""", (event_id, revision_id))
        linked.append(event_id)
    return linked
