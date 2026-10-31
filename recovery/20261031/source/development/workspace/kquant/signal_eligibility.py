"""Append-only current eligibility evidence in the existing Copilot store."""
import json
import sqlite3
from datetime import datetime


SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_eligibility_revisions (
  signal_id TEXT NOT NULL REFERENCES signals(signal_id),
  revision INTEGER NOT NULL,
  checked_at TEXT NOT NULL,
  state TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(signal_id, revision)
);
"""
TERMINAL = {"REVOKED", "EXPIRED"}
STATES = TERMINAL | {"QUALIFIED", "WAITING_EVIDENCE"}


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("ELIGIBILITY_TIMEZONE_REQUIRED")
    return result


def append_revision(path, signal_id, payload):
    """Serialize revision races; never mutate the original signal or resurrect it."""
    checked = timestamp(payload["checked_at"])
    if payload["state"] not in STATES:
        raise ValueError("ELIGIBILITY_STATE_INVALID")
    with sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=rw", uri=True, timeout=2) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        source = db.execute("SELECT payload_json FROM signals WHERE signal_id=?", (signal_id,)).fetchone()
        if source is None:
            raise ValueError("SIGNAL_NOT_FOUND")
        original = json.loads(source[0])
        previous = db.execute(
            "SELECT revision,payload_json FROM signal_eligibility_revisions WHERE signal_id=? ORDER BY revision DESC LIMIT 1",
            (signal_id,),
        ).fetchone()
        if previous:
            old = json.loads(previous[1])
            if old["state"] in TERMINAL or checked <= timestamp(old["checked_at"]):
                return old
        if payload.get("contract_id") != original.get("contract_id"):
            raise ValueError("ELIGIBILITY_CONTRACT_CHANGED")
        deadline = timestamp(original["valid_until"])
        record = {**payload, "signal_id": signal_id, "revision": previous[0] + 1 if previous else 1}
        if checked >= deadline:
            record.update(state="EXPIRED", reason="ORIGINAL_DEADLINE_EXCEEDED", valid_until=original["valid_until"])
        elif record["state"] == "QUALIFIED":
            until = timestamp(record["valid_until"])
            if not checked < until <= deadline:
                raise ValueError("ELIGIBILITY_VALIDITY_INVALID")
        db.execute("INSERT INTO signal_eligibility_revisions VALUES (?,?,?,?,?)", (
            signal_id, record["revision"], checked.isoformat(), record["state"],
            json.dumps(record, sort_keys=True, separators=(",", ":")),
        ))
        return record


def latest_revision(path, signal_id):
    """Read only: an absent migration or store cannot create an empty database."""
    if not path.is_file():
        return None
    with sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=0.25) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_eligibility_revisions'").fetchone():
            return None
        row = db.execute(
            "SELECT payload_json FROM signal_eligibility_revisions WHERE signal_id=? ORDER BY revision DESC LIMIT 1",
            (signal_id,),
        ).fetchone()
        return json.loads(row[0]) if row else None


def attach_current(candidates, path):
    """Read current evidence outside the slower historical snapshot cache."""
    if not candidates or not path.is_file():
        return [{**row, "current_eligibility": None} for row in candidates]
    from .bounded_sqlite import read_connection
    with read_connection(path, seconds=0.25) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_eligibility_revisions'").fetchone():
            return [{**row, "current_eligibility": None} for row in candidates]
        result = []
        for candidate in candidates[:222]:
            row = db.execute("SELECT payload_json FROM signal_eligibility_revisions WHERE signal_id=? ORDER BY revision DESC LIMIT 1",
                             ("one-minute-" + candidate["event_id"],)).fetchone()
            result.append({**candidate, "current_eligibility": json.loads(row[0]) if row else None})
        return result


def revision_history(path, signal_id):
    from .bounded_sqlite import read_connection
    if not path.is_file():
        return []
    with read_connection(path, seconds=0.25) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='signal_eligibility_revisions'").fetchone():
            return []
        return [json.loads(row[0]) for row in db.execute(
            "SELECT payload_json FROM signal_eligibility_revisions WHERE signal_id=? ORDER BY revision DESC LIMIT 100",
            (signal_id,))]
