"""Small version-isolated research evidence, not a trading or Paper ledger."""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from itertools import groupby
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from dataclasses import dataclass

from . import options_one_minute as common
from . import options_opening_trend as trend
from .options_data_paths import connect_store, resolve_stores

STORE = resolve_stores(common.ROOT)["opening_research"]


def initialize(path: Path = STORE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_store(path, timeout=1)) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=FULL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS evaluations (
          evaluation_id TEXT PRIMARY KEY, policy_hash TEXT NOT NULL, session TEXT NOT NULL,
          symbol TEXT NOT NULL, right_name TEXT NOT NULL, evaluated_at TEXT NOT NULL,
          state TEXT NOT NULL, payload_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS trend_latest ON evaluations(policy_hash,session,symbol,right_name,evaluated_at);
        CREATE INDEX IF NOT EXISTS trend_current_time ON evaluations(policy_hash,session,julianday(evaluated_at));
        CREATE TABLE IF NOT EXISTS revisions (
          revision_id INTEGER PRIMARY KEY, evaluation_id TEXT NOT NULL,
          checked_at TEXT NOT NULL, state TEXT NOT NULL, payload_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS trend_revision_latest ON revisions(evaluation_id,revision_id);
        CREATE TABLE IF NOT EXISTS qualification_jobs (
          evaluation_id TEXT PRIMARY KEY, deadline_at TEXT NOT NULL, state TEXT NOT NULL,
          next_at TEXT NOT NULL, lease_until TEXT, lease_token TEXT,
          attempts INTEGER NOT NULL DEFAULT 0, progress_json TEXT NOT NULL,
          updated_at TEXT NOT NULL, last_error TEXT);
        CREATE INDEX IF NOT EXISTS trend_job_due ON qualification_jobs(state,next_at,deadline_at);
        CREATE TABLE IF NOT EXISTS qualified_claims (
          event_id TEXT PRIMARY KEY, evaluation_id TEXT UNIQUE NOT NULL,
          published_at TEXT NOT NULL, payload_json TEXT NOT NULL, linked_at TEXT);
        CREATE TABLE IF NOT EXISTS publication_offsets (
          event_id TEXT PRIMARY KEY, revision_id INTEGER NOT NULL);
        """)


def persist(rows: list[dict], path: Path = STORE) -> None:
    with closing(connect_store(path, timeout=1)) as c, c:
        persist_in_transaction(c, rows)


@dataclass(frozen=True)
class PreparedEvaluations:
    rows: tuple
    values: tuple


def prepare_evaluations(rows):
    """Serialize the captured result before acquiring the shared writer lock."""
    if isinstance(rows, PreparedEvaluations):
        return rows
    rows = [item for row in rows for item in ([row, row["strategy_comparison"]["s1"]]
        if row.get("strategy_comparison") else [row])]
    from .options_intraday_comparison import compact_comparison
    values = tuple((r["evaluation_id"], r["policy_hash"], r["session"], r["symbol"], r["right"],
        r["evaluated_at"], r["state"], common.canonical({**r,
            "strategy_comparison": compact_comparison(r["strategy_comparison"])}
            if r.get("strategy_comparison") else r)) for r in rows)
    # The immutable JSON also fixes the fields used by transaction checks.
    return PreparedEvaluations(tuple(json.loads(value[-1]) for value in values), values)


def persist_in_transaction(c, rows):
    """Share the checkpoint CAS transaction instead of publishing stale work."""
    prepared = prepare_evaluations(rows)
    rows = prepared.rows
    bindings = {value["fact_hash"]: value for row in rows
                for value in [row.get("reference_evidence", {}).get("session_price_binding", {})]
                if value.get("kind") == "SESSION_PRICE_BINDING_V1"}
    if bindings:
        from .options_price_facts import persist_prepared_in_transaction
        for value in bindings.values():
            persist_prepared_in_transaction(c, value)
    for row in rows:
        fingerprint = row.get("runtime_inputs", {}).get("input_fingerprint")
        if not fingerprint or not row.get("calculation_bar_end"):
            continue
        old = c.execute("""SELECT evaluation_id FROM evaluations
            WHERE policy_hash=? AND session=? AND symbol=? AND right_name=? AND state='NUMERIC_PASS'
            AND json_extract(payload_json,'$.calculation_bar_end')=?
            AND COALESCE(json_extract(payload_json,'$.runtime_inputs.input_fingerprint'),'')!=?
            LIMIT 101""", (row["policy_hash"], row["session"], row["symbol"], row["right"],
                row["calculation_bar_end"], fingerprint)).fetchall()
        if len(old) > 100:
            raise ValueError("INPUT_REVISION_BOUND_EXCEEDED")
        for evaluation_id, in old:
            append_revision_in_transaction(c, evaluation_id, {"checked_at": row["computed_at"],
                "state": "WITHDRAWN", "reasons": ["CANONICAL_INPUT_GENERATION_CHANGED"],
                "superseded_by_evaluation": row["evaluation_id"], "input_fingerprint": fingerprint})
            c.execute("UPDATE qualification_jobs SET state='WITHDRAWN',lease_until=NULL,lease_token=NULL WHERE evaluation_id=?",
                      (evaluation_id,))
    c.executemany("INSERT OR IGNORE INTO evaluations VALUES (?,?,?,?,?,?,?,?)", prepared.values)
    c.executemany("""INSERT OR IGNORE INTO qualification_jobs
          (evaluation_id,deadline_at,state,next_at,progress_json,updated_at) VALUES (?,?,'READY',?,'{}',?)""",
          [(r["evaluation_id"], r["deadline_at"], r["evaluated_at"], r["evaluated_at"])
           for r in rows if r["state"] == "NUMERIC_PASS" and r.get("deadline_at")
           and not (r.get("research_only") and r.get("reference_collection_owner") == "S0")
           and not c.execute("SELECT 1 FROM qualified_claims WHERE event_id=?", (r["event_id"],)).fetchone()])


def detail(evaluation_id: str, path: Path = STORE) -> dict | None:
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.2)) as c:
        row = c.execute("SELECT payload_json FROM evaluations WHERE evaluation_id=?", (evaluation_id,)).fetchone()
        if not row:
            return None
        result = json.loads(row[0])
        current = c.execute("SELECT revision_id,payload_json FROM revisions WHERE evaluation_id=? ORDER BY revision_id DESC LIMIT 1",
                            (evaluation_id,)).fetchone()
        if current:
            result["current_eligibility"] = {**json.loads(current[1]), "revision": current[0]}
        comparison = result.get("strategy_comparison")
        if comparison:
            child_payload = c.execute("SELECT payload_json FROM evaluations WHERE evaluation_id=?",
                (comparison["s1"]["evaluation_id"],)).fetchone()
            if child_payload:
                comparison["s1"] = json.loads(child_payload[0])
            current_child = c.execute("SELECT revision_id,payload_json FROM revisions WHERE evaluation_id=? ORDER BY revision_id DESC LIMIT 1",
                (comparison["s1"]["evaluation_id"],)).fetchone()
            revision = ({**json.loads(current_child[1]), "revision": current_child[0]} if current_child else {})
            attach_research_reference(result, revision)
        claimed = c.execute("SELECT payload_json FROM qualified_claims WHERE evaluation_id=?", (evaluation_id,)).fetchone()
        if claimed:
            result["published_candidate"] = json.loads(claimed[0])
            result["contract_id"] = result["published_candidate"]["contract_id"]
        from .options_research_availability import attach
        attach(c, [result])
        from .options_research_ai_store import attach as attach_ai
        attach_ai([result])
        return result


def append_revision(evaluation_id: str, revision: dict, path: Path = STORE) -> dict:
    """Serialize lifecycle updates without changing the original judgment."""
    with closing(connect_store(path, timeout=1)) as c, c:
        c.execute("BEGIN IMMEDIATE")
        return append_revision_in_transaction(c, evaluation_id, revision)


def append_revision_in_transaction(c, evaluation_id, revision):
    """Caller owns the write transaction, including any lease/outbox settlement."""
    stamp = common.timestamp(revision["checked_at"])
    row = c.execute("SELECT payload_json FROM evaluations WHERE evaluation_id=?", (evaluation_id,)).fetchone()
    if not row:
        raise ValueError("UNKNOWN_EVALUATION")
    original = json.loads(row[0])
    if original.get("policy_id") == "STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1" and revision.get("state") == "QUALIFIED":
        raise ValueError("S1_QUALIFIED_PUBLICATION_FORBIDDEN")
    if original["state"] != "NUMERIC_PASS" or not original.get("deadline_at"):
        raise ValueError("NO_CONFIRMED_SETUP")
    previous = c.execute("SELECT revision_id,payload_json FROM revisions WHERE evaluation_id=? ORDER BY revision_id DESC LIMIT 1",
                         (evaluation_id,)).fetchone()
    old = json.loads(previous[1]) if previous else None
    if old and (stamp <= common.timestamp(old["checked_at"]) or old["state"] in {"WITHDRAWN", "EXPIRED"}):
        return {**old, "revision": previous[0]}
    value = dict(revision)
    if value["state"] not in {"PENDING", "QUALIFIED", "WITHDRAWN", "EXPIRED"}:
        raise ValueError("INVALID_ELIGIBILITY_STATE")
    value.update(evaluation_id=evaluation_id, event_id=original["event_id"],
                 deadline_at=original["deadline_at"], policy_hash=original["policy_hash"],
                 scope_hash=original["scope_hash"])
    locked = bool(old and (old.get("contract_locked") or old["state"] == "QUALIFIED"))
    value["contract_locked"] = locked or value["state"] == "QUALIFIED"
    if locked and old.get("contract_id") and value.get("contract_id") != old["contract_id"]:
        value.update(state="WITHDRAWN", contract_id=old["contract_id"], reasons=["SELECTED_CONTRACT_CHANGED"])
    deadline = common.timestamp(original["deadline_at"])
    if stamp >= deadline:
        value.update(state="EXPIRED", reasons=["ORIGINAL_DEADLINE_EXCEEDED"])
    if value["state"] == "QUALIFIED":
        until = common.timestamp(value["valid_until"])
        if not stamp < until <= deadline or not value.get("contract_id"):
            raise ValueError("INVALID_QUALIFICATION_EVIDENCE_BOUND")
    else:
        value["valid_until"] = stamp.isoformat()
    if value["state"] == "QUALIFIED" and value.get("approval", {}).get("qualified_signal_pipeline_enabled"):
        from .options_opening_trend_approval import status as approval_status
        from .options_opening_momentum import policy_for
        approval = approval_status(policy_for(original), original["scope_hash"])
        if (not approval["qualified_signal_pipeline_enabled"]
                or approval["selected_expiry_group"] != value["approval"].get("selected_expiry_group")):
            value.update(state="WITHDRAWN", reasons=["POLICY_OR_SCOPE_CHANGED"], valid_until=stamp.isoformat())
        else:
            existing = c.execute("SELECT evaluation_id FROM qualified_claims WHERE event_id=?", (original["event_id"],)).fetchone()
            if existing and existing[0] != evaluation_id:
                value.update(state="WITHDRAWN", reasons=["FIRST_QUALIFIED_ALREADY_CLAIMED"], valid_until=stamp.isoformat())
            elif not existing:
                candidate = {**original, "state": "QUALIFIED_SIGNAL", "qualified_signal": True,
                    "contract_id": value["contract_id"], "contract_qualification": value["contract_qualification"],
                    "event_coverage": value["event_coverage"], "initial_eligibility": value,
                    "published_at": stamp.isoformat(), "approval": approval}
                c.execute("INSERT INTO qualified_claims VALUES (?,?,?,?,NULL)",
                    (original["event_id"], evaluation_id, stamp.isoformat(), common.canonical(candidate)))
    cursor = c.execute("INSERT INTO revisions(evaluation_id,checked_at,state,payload_json) VALUES (?,?,?,?)",
                       (evaluation_id, stamp.isoformat(), value["state"], common.canonical(value)))
    return {**value, "revision": cursor.lastrowid}


def attach_research_reference(row, child_revision):
    comparison = row.get("strategy_comparison")
    if not comparison:
        return
    revision = row.get("current_eligibility", {}) if comparison["s1"].get("reference_collection_owner") == "S0" else child_revision
    comparison["reference_eligibility"] = revision
    comparison["reference_contract"] = revision.get("reference_contract")
    if revision.get("option_cost"):
        comparison["option_cost"] = revision["option_cost"]
    elif revision.get("reference_contract") and revision.get("checked_at"):
        from .options_intraday_reference import cost_from_contract
        comparison["option_cost"] = cost_from_contract(revision["reference_contract"], now=common.timestamp(revision["checked_at"]))


def current_cards(*, path=STORE, session, scope_hash, now, policy):
    """Independent live-card query: no history projection, SDK, or per-row reads."""
    from .bounded_sqlite import read_connection
    from .options_opening_trend_summary import DETAIL_FIELDS, compact_record
    from .options_opening_trend_approval import status as approval_status
    now = common.timestamp(now)
    approval = approval_status(policy, scope_hash)
    paths = tuple("$." + name for name in sorted(DETAIL_FIELDS))
    query_started=monotonic()
    # A live original deadline implies evaluation within this policy window.
    # Reject old rows on their small timestamp column before parsing evidence JSON.
    with read_connection(path, seconds=.3) as db:
        rows = db.execute(f"""SELECT json_remove(e.payload_json,{','.join('?' for _ in paths)}),
            r.revision_id,r.payload_json,q.payload_json,child.revision_id,child.payload_json
            FROM evaluations e
            LEFT JOIN revisions r ON r.revision_id=(SELECT MAX(revision_id) FROM revisions WHERE evaluation_id=e.evaluation_id)
            LEFT JOIN qualified_claims q ON q.evaluation_id=e.evaluation_id
            LEFT JOIN revisions child ON child.revision_id=(SELECT MAX(revision_id) FROM revisions
                WHERE evaluation_id=json_extract(e.payload_json,'$.strategy_comparison.s1.evaluation_id'))
            WHERE e.policy_hash=? AND e.session=?
            AND julianday(e.evaluated_at)>=julianday(?) AND julianday(e.evaluated_at)<=julianday(?) AND (
                (e.state='NUMERIC_PASS' AND json_extract(e.payload_json,'$.deadline_at')>?) OR
                (json_extract(e.payload_json,'$.strategy_comparison.s1.state')='NUMERIC_PASS'
                 AND json_extract(e.payload_json,'$.strategy_comparison.s1.deadline_at')>?)) LIMIT 223""",
            (*paths, policy["policy_hash"], session,
             (now - timedelta(seconds=policy["signal_deadline_seconds"])).isoformat(),
           now.isoformat(),
             now.isoformat(), now.isoformat())).fetchall()
        watermark={"evaluation_rowid":db.execute('SELECT max(rowid) FROM evaluations').fetchone()[0],
            "revision_id":db.execute('SELECT max(revision_id) FROM revisions').fetchone()[0]}
    sql_seconds=monotonic()-query_started
    if len(rows) > 222:
        raise ValueError("LIVE_CARD_BOUND_EXCEEDED")
    result = {"session": session, "scope_hash": scope_hash, "approvals": approval,
        "candidates": [], "evaluations": [], "as_of": now.isoformat(), "read_only": True}
    projection_started=monotonic()
    for raw, revision_id, revision_raw, claimed, child_id, child_raw in rows:
        row = json.loads(raw)
        if row.get("scope_hash") != scope_hash:
            continue
        if revision_raw:
            row["current_eligibility"] = {**json.loads(revision_raw), "revision": revision_id}
        attach_research_reference(row, {**json.loads(child_raw), "revision": child_id} if child_raw else {})
        current = row.get("current_eligibility", {})
        result["evaluations"].append(row)
        if (claimed and approval["qualified_signal_pipeline_enabled"] and current.get("state") == "QUALIFIED"
                and now < common.timestamp(current["valid_until"])):
            candidate = {**row, "contract_id": json.loads(claimed)["contract_id"]}
            result["candidates"].append(compact_record(candidate))
    # Research observations are not the actionable-candidate channel. Keep its
    # transport bounded; full results remain available via history and detail.
    observations = result["evaluations"]
    result["evaluations_total"] = len(observations)
    result["research_summary"] = {"s1_numeric_pass": sum(
        row.get("strategy_comparison", {}).get("s1", {}).get("state") == "NUMERIC_PASS" for row in observations)}
    observations.sort(key=lambda row: (
        row.get("strategy_comparison", {}).get("cohort") != "S1_INTRADAY_ONLY_DATA",
        row["symbol"], row["right"], row["evaluated_at"]))
    result["evaluations"] = [compact_record(row) for row in observations[:8]]
    while result["evaluations"] and len(common.canonical(result["evaluations"]).encode("utf-8")) > 32768:
        result["evaluations"].pop()
    result["evaluations_deferred"] = len(result["evaluations"]) < result["evaluations_total"]
    result['current_projection']={"source_watermark":watermark,"as_of":now.isoformat(),
        "window_seconds":policy['signal_deadline_seconds'],"original_deadlines_preserved":True,
        "input_generations":sorted({str(r.get('runtime_inputs',{}).get('input_generation')) for r in observations}),
        "sql_seconds":sql_seconds,"json_projection_seconds":monotonic()-projection_started,
        "sql_returned_rows":len(rows),"lock_wait_seconds":None}
    from .options_research_ai_store import attach as attach_ai
    ai_started=monotonic()
    attach_ai(result['evaluations'])
    result['current_projection']['ai_summary_seconds']=monotonic()-ai_started
    return result


def status(*, session: str | None = None, path: Path = STORE, now: datetime | None = None, scope_hash=None, compact=False, policy=None) -> dict:
    now = common.timestamp(now or datetime.now(UTC))
    session = session or now.astimezone(common.NY).date().isoformat()
    p = policy or trend.load_policy()
    from .options_opening_trend_approval import status as approval_status
    approval = approval_status(p, scope_hash)
    result = dict(policy=p, session=session, initialized=path.is_file(), mode="SHADOW_RESEARCH",
                  approvals=approval, candidates=[], evaluations=[],
                  blockers=approval["reasons"],
                  paper_enabled=False, real_orders_enabled=False)
    if not path.is_file():
        result["state"] = "NOT_STARTED"
        return result
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.2)) as c:
        budget = monotonic() + .5
        c.set_progress_handler(lambda: int(monotonic() > budget), 1000)
        # Order small identifiers first; don't scan every large JSON document for scope.
        identifiers = c.execute("""SELECT rowid,symbol,right_name,evaluated_at FROM evaluations
            WHERE policy_hash=? AND session=?
            ORDER BY symbol,right_name,evaluated_at DESC LIMIT 12001""",
            (p["policy_hash"], session)).fetchall()
        if len(identifiers) > 12000:
            raise RuntimeError("STATUS_RECORD_BOUND_EXCEEDED")
        items = []
        from .options_opening_trend_summary import DETAIL_FIELDS, compact_status
        removed_paths = tuple("$." + key for key in sorted(DETAIL_FIELDS)) if compact else ()
        document = ("json_remove(payload_json," + ",".join("?" for _ in removed_paths) + ")"
                    if compact else "payload_json")
        # Fetch one time cohort per direction in a batch. Older scope cohorts are
        # retried in batches only when the newest cohort belongs to a prior scope.
        directions = [list(rows) for _, rows in groupby(identifiers, key=lambda r: (r[1], r[2]))]
        while directions and len(items) < 222:
            cohorts, rest = [], []
            for rows in directions:
                stamp = rows[0][3]
                cohorts.append([row for row in rows if row[3] == stamp])
                rest.append([row for row in rows if row[3] != stamp])
            ids = [row[0] for cohort in cohorts for row in cohort]
            loaded = {}
            for offset in range(0, len(ids), 400):
                batch = ids[offset:offset + 400]
                sql = f"SELECT rowid,{document} FROM evaluations WHERE rowid IN ({','.join('?' for _ in batch)})"
                loaded.update((rowid, json.loads(raw)) for rowid, raw in c.execute(sql, (*removed_paths, *batch)))
            retry = []
            for cohort, older in zip(cohorts, rest):
                valid = [loaded[row[0]] for row in cohort if scope_hash is None or loaded[row[0]].get("scope_hash") == scope_hash]
                if valid:
                    items.append(max(valid, key=lambda row: row["evaluation_id"]))
                elif older:
                    retry.append(older)
            directions = retry
        revisions = {}
        ids = [identity for item in items for identity in ([item["evaluation_id"], item["strategy_comparison"]["s1"]["evaluation_id"]]
            if item.get("strategy_comparison") else [item["evaluation_id"]])]
        if ids:
            sql = f"""SELECT revision_id,evaluation_id,payload_json FROM revisions
                WHERE revision_id IN (SELECT MAX(revision_id) FROM revisions
                WHERE evaluation_id IN ({','.join('?' for _ in ids)}) GROUP BY evaluation_id)"""
            revisions = {identity: {**json.loads(raw), "revision": revision}
                         for revision, identity, raw in c.execute(sql, ids)}
        if approval["qualified_signal_pipeline_enabled"]:
            for raw, current_raw in c.execute(f"""SELECT {document},
                    (SELECT payload_json FROM revisions WHERE evaluation_id=qualified_claims.evaluation_id
                     ORDER BY revision_id DESC LIMIT 1)
                    FROM qualified_claims WHERE published_at>=? ORDER BY published_at LIMIT 222""",
                                    (*removed_paths, session + "T00:00:00")):
                candidate = json.loads(raw)
                if candidate["policy_hash"] != p["policy_hash"] or candidate["scope_hash"] != scope_hash or candidate["session"] != session:
                    continue
                current = json.loads(current_raw) if current_raw else {}
                if (current.get("state") == "QUALIFIED" and now < common.timestamp(current["valid_until"])
                        and now < common.timestamp(candidate["deadline_at"])):
                    candidate["current_eligibility"] = current
                    result["candidates"].append(candidate)
    for item in items:
        if item["evaluation_id"] in revisions:
            item["current_eligibility"] = revisions[item["evaluation_id"]]
        attach_research_reference(item, revisions.get(item.get("strategy_comparison", {}).get("s1", {}).get("evaluation_id"), {}))
        item["observation_expired"] = bool(item.get("deadline_at") and now >= common.timestamp(item["deadline_at"]))
        result["evaluations"].append(item)
    result["state"] = "SHADOW_RESEARCH" if items else "NO_CURRENT_SESSION_EVALUATIONS"
    result["last_evaluation_at"] = max((r["evaluated_at"] for r in result["evaluations"]), default=None)
    result["summary"] = {"evaluated_directions": len(items),
        "numeric_pass_directions": sum(r["state"] == "NUMERIC_PASS" for r in result["evaluations"]),
        "incomplete_directions": sum(r["state"] == "INCOMPLETE" for r in result["evaluations"])}
    from .options_research_ai_store import attach as attach_ai
    attach_ai(result['evaluations'][:8] if compact else result['evaluations'])
    return compact_status(result) if compact else result
