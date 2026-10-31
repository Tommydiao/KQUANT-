"""Leased, deadline-bound continuation tasks in the existing research evidence DB."""
import json
import sqlite3
from contextlib import closing
from datetime import timedelta
from uuid import uuid4

from . import options_one_minute as common

EXPIRY_BATCH_BOUND = 8


def claim(path, *, now, lease_seconds=30, exclude=()):
    stamp = now.isoformat()
    excluded = tuple(dict.fromkeys(exclude))
    exclusion = " AND evaluation_id NOT IN (" + ",".join("?" for _ in excluded) + ")" if excluded else ""
    with closing(sqlite3.connect(path, timeout=.2)) as c, c:
        # Empty polls must not acquire the writer lock used by bar calculations.
        work = c.execute("""SELECT 1 FROM qualification_jobs
          WHERE state IN ('READY','LEASED') AND (
            deadline_at<=? OR (state='LEASED' AND lease_until<=?)
            OR (state='READY' AND next_at<=?""" + exclusion + ")) LIMIT 1",
            (stamp, stamp, stamp, *excluded)).fetchone()
        if not work:
            return None
        c.execute("BEGIN IMMEDIATE")
        expired = c.execute("SELECT evaluation_id FROM qualification_jobs WHERE deadline_at<=? "
                            "AND state IN ('READY','LEASED') ORDER BY deadline_at,evaluation_id LIMIT ?",
                            (stamp, EXPIRY_BATCH_BOUND)).fetchall()
        from .options_opening_trend_store import append_revision_in_transaction
        for (evaluation_id,) in expired:
            append_revision_in_transaction(c, evaluation_id, {"state": "EXPIRED", "checked_at": stamp,
                                            "reasons": ["ORIGINAL_DEADLINE_EXCEEDED"]})
            c.execute("""UPDATE qualification_jobs SET state='EXPIRED',lease_token=NULL,lease_until=NULL,updated_at=?
                         WHERE evaluation_id=?""", (stamp, evaluation_id))
        c.execute("""UPDATE qualification_jobs SET state='READY',lease_token=NULL,lease_until=NULL
                     WHERE state='LEASED' AND lease_until<=? AND deadline_at>?""", (stamp, stamp))
        exclusion = " AND j.evaluation_id NOT IN (" + ",".join("?" for _ in excluded) + ")" if excluded else ""
        row = c.execute("""SELECT j.evaluation_id,j.deadline_at,j.progress_json,e.payload_json
          FROM qualification_jobs j JOIN evaluations e USING(evaluation_id)
          WHERE j.state='READY' AND j.next_at<=? AND j.deadline_at>?
          """ + exclusion + " ORDER BY j.deadline_at,j.attempts,j.next_at,j.evaluation_id LIMIT 1",
          (stamp, stamp, *excluded)).fetchone()
        if not row:
            return None
        token = uuid4().hex
        until = min(now + timedelta(seconds=lease_seconds), common.timestamp(row[1]))
        c.execute("""UPDATE qualification_jobs SET state='LEASED',lease_token=?,lease_until=?,
                     attempts=attempts+1,updated_at=? WHERE evaluation_id=?""",
                  (token, until.isoformat(), stamp, row[0]))
        return {"evaluation": json.loads(row[3]), "progress": json.loads(row[2]), "lease_token": token}


def settle(path, job, *, now, progress, finished=False, retry_seconds=0, error=None, revision=None,
           return_revision=False):
    stamp = now.isoformat()
    with closing(sqlite3.connect(path, timeout=.2)) as c, c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT deadline_at,lease_token,state,lease_until FROM qualification_jobs WHERE evaluation_id=?",
                        (job["evaluation"]["evaluation_id"],)).fetchone()
        if not row or row[1] != job["lease_token"] or row[2] != "LEASED":
            return {"committed": False, "revision": None} if return_revision else False
        expired = now >= common.timestamp(row[0])
        if not expired and now >= common.timestamp(row[3]):
            return {"committed": False, "revision": None} if return_revision else False
        committed = None
        if expired and revision is None:
            revision = {"state": "EXPIRED", "checked_at": stamp, "reasons": ["ORIGINAL_DEADLINE_EXCEEDED"]}
        if revision is not None:
            from .options_opening_trend_store import append_revision_in_transaction
            value = dict(revision)
            value["computed_at"] = value["checked_at"]
            value["checked_at"] = stamp
            if value["state"] == "QUALIFIED" and now >= common.timestamp(value["valid_until"]):
                value.update(state="PENDING", reasons=["EVIDENCE_EXPIRED_BEFORE_COMMIT"])
            if expired:
                value.update(state="EXPIRED", checked_at=stamp, reasons=["ORIGINAL_DEADLINE_EXCEEDED"])
            committed = append_revision_in_transaction(c, job["evaluation"]["evaluation_id"], value)
            finished = finished or committed["state"] in {"EXPIRED", "WITHDRAWN"}
            if progress.get("selected_contract_id") and committed["state"] != "QUALIFIED":
                claimed = c.execute("SELECT 1 FROM qualified_claims WHERE evaluation_id=?",
                                    (job["evaluation"]["evaluation_id"],)).fetchone()
                if not claimed:
                    progress = {k: v for k, v in progress.items() if k not in {
                        "selected_contract_id", "selected_group", "selected_source_binding"}}
                    progress["phase"] = "REFRESH_EVENT"
        state = "EXPIRED" if expired else "DONE" if finished else "READY"
        c.execute("""UPDATE qualification_jobs SET state=?,next_at=?,lease_until=NULL,lease_token=NULL,
                     progress_json=?,updated_at=?,last_error=? WHERE evaluation_id=?""",
                  (state, (now + timedelta(seconds=retry_seconds)).isoformat(), common.canonical(progress),
                   stamp, error, job["evaluation"]["evaluation_id"]))
        return {"committed": True, "revision": committed} if return_revision else True
