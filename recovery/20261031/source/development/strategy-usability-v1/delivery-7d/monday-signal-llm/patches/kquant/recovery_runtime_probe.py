"""Bounded, read-only observations of activated databases, outside the launcher."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
from math import isfinite
import ntpath
from pathlib import Path
import re
import sqlite3
import stat
import sys
from time import monotonic

SOURCE_INDEX_EXTENSION = "OPENING_SOURCE_INDEX_V1"
SOURCE_INDEX_SCHEMA = ("index", "trend_input_source", "two_hour_jobs",
    "CREATE INDEX trend_input_source ON two_hour_jobs(session,symbol,queued_at)")
MINUTE_STATUS_EXTENSION = "MINUTE_STATUS_METADATA_INDEX_V1"
MINUTE_STATUS_SCHEMA = ("index", "one_minute_status_metadata", "one_minute_evaluations",
    "CREATE INDEX one_minute_status_metadata ON one_minute_evaluations(session,symbol,right_name,created_at,bar_end,state)")
CURRENT_INDEX_SCHEMA = ('index','trend_current_time','evaluations',
    'CREATE INDEX trend_current_time ON evaluations(policy_hash,session,julianday(evaluated_at))')
INDEX_EXTENSIONS = {
    ("opening_research", SOURCE_INDEX_EXTENSION): SOURCE_INDEX_SCHEMA,
    ("minute", MINUTE_STATUS_EXTENSION): MINUTE_STATUS_SCHEMA,
    ('opening_research','OPENING_SOURCE_AND_CURRENT_INDEX_V1'): (SOURCE_INDEX_SCHEMA,CURRENT_INDEX_SCHEMA),
}

COPILOT_BUDGET_BASE_SQL="""CREATE TABLE llm_budget_reservations (
  reservation_id TEXT PRIMARY KEY,
  scan_id TEXT NOT NULL UNIQUE,
  budget_date TEXT NOT NULL,
  timezone TEXT NOT NULL,
  reserved_usd TEXT NOT NULL,
  actual_cost_usd TEXT,
  state TEXT NOT NULL,
  request_sent INTEGER NOT NULL,
  provider_request_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)"""

def copilot_ai_schema(schema):
    additions=(('approval_id',"TEXT NOT NULL DEFAULT ''"),('role',"TEXT NOT NULL DEFAULT 'ASTRA'"),
        ('candidate_id',"TEXT NOT NULL DEFAULT ''"),('purpose',"TEXT NOT NULL DEFAULT 'research'"),
        ('notification_key',"TEXT NOT NULL DEFAULT ''"))
    queue_sql="""CREATE TABLE llm_work_queue (
  work_id TEXT PRIMARY KEY,
  role TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  notification_key TEXT NOT NULL DEFAULT '',
  priority INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL,
  deferred_reason TEXT,
  enqueued_at TEXT NOT NULL,
  leased_at TEXT,
  completed_at TEXT,
  updated_at TEXT NOT NULL
)"""
    with closing(sqlite3.connect(':memory:')) as expected:
        expected.execute(COPILOT_BUDGET_BASE_SQL)
        accepted={COPILOT_BUDGET_BASE_SQL}
        for name,definition in additions:
            expected.execute(f'ALTER TABLE llm_budget_reservations ADD COLUMN {name} {definition}')
            accepted.add(expected.execute("SELECT sql FROM sqlite_master WHERE name='llm_budget_reservations'").fetchone()[0])
    names={
        'llm_work_queue':('table','llm_work_queue','llm_work_queue',queue_sql),
        'idx_llm_work_queue_state':('index','idx_llm_work_queue_state','llm_work_queue',
            'CREATE INDEX idx_llm_work_queue_state ON llm_work_queue(state,priority DESC,enqueued_at)')}
    baseline=[]
    found=False
    for raw in schema:
        row=tuple(raw)
        if row[1] in names:
            if row!=names[row[1]]:
                raise ValueError('DECLARED_AI_QUEUE_DEFINITION_CHANGED')
            continue
        if row[1]=='llm_budget_reservations':
            if row[:3]!=('table','llm_budget_reservations','llm_budget_reservations') or row[3] not in accepted:
                raise ValueError('DECLARED_AI_BUDGET_COLUMNS_CHANGED')
            row=(*row[:3],COPILOT_BUDGET_BASE_SQL)
            found=True
        baseline.append(row)
    if not found:
        raise ValueError('ORIGINAL_AI_BUDGET_TABLE_REQUIRED')
    return baseline


def schema_observation(schema, request):
    digest = lambda rows: sha256(json.dumps(rows, ensure_ascii=True).encode("ascii")).hexdigest()
    result = {"schema_sha256": digest(schema)}
    extension = request.get("schema_extension")
    if extension=='COPILOT_AI_BUDGET_QUEUE_V1' and request.get('role')=='signal_copilot':
        baseline=copilot_ai_schema(schema)
        return {**result,'baseline_schema_sha256':digest(baseline),
            'schema_extension':{'contract':extension,'present':baseline!=schema}}
    if extension is not None:
        if not isinstance(extension, str):
            raise ValueError("UNSUPPORTED_SCHEMA_EXTENSION")
        expected = INDEX_EXTENSIONS.get((request.get("role"), extension))
        if expected is None:
            raise ValueError("UNSUPPORTED_SCHEMA_EXTENSION")
        definitions=expected if isinstance(expected[0],tuple) else (expected,)
        matches=[]
        for definition in definitions:
            found=[row for row in schema if row[1]==definition[1]]
            if found and (len(found)!=1 or tuple(found[0])!=definition):
                raise ValueError('DECLARED_INDEX_DEFINITION_CHANGED')
            matches.extend(found)
        names={definition[1] for definition in definitions}
        baseline = [row for row in schema if row[1] not in names]
        result.update(baseline_schema_sha256=digest(baseline),
            schema_extension={"contract": extension, "present": bool(matches)})
    return result


def local_file(value: str, roots: list[str], *, require_file: bool = True) -> Path:
    drive, tail = ntpath.splitdrive(value)
    if drive.upper() not in {"C:", "D:", "E:"} or not ntpath.isabs(value) or ":" in tail:
        raise ValueError("FORBIDDEN_OR_RELATIVE_PATH")
    path = Path(ntpath.normpath(value))
    if not any(path.is_relative_to(Path(root)) for root in roots):
        raise ValueError("OUTSIDE_APPROVED_LOCAL_ROOTS")
    for item in reversed([path, *path.parents]):
        try:
            info = item.lstat()
        except FileNotFoundError:
            if require_file:
                raise
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("REPARSE_PATH")
    if require_file and not path.is_file():
        raise ValueError("MISSING_DATABASE_NO_AUTOCREATE")
    return path


def file_identity(path: Path) -> dict:
    info = path.stat()
    if not info.st_ino:
        raise ValueError("DATABASE_FILE_ID_UNAVAILABLE")
    return {"device": info.st_dev, "inode": info.st_ino}


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("INVALID_WATERMARK_IDENTIFIER")
    return '"' + value + '"'


def initialization_metadata_compatible(db, request, mark, roots, deadline, tracker=None):
    """Two version keys are replaced by initialization; ledger prefixes stay strict."""
    baseline = request.get("metadata_baseline")
    if (request.get("role") != "signal_copilot" or mark["table"] != "copilot_meta"
            or mark["column"] != "rowid" or mark.get("minimum") is None or not baseline):
        return False
    path = local_file(baseline["path"], roots)
    if file_identity(path) != baseline.get("file_identity"):
        return False
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)) as original:
        if tracker is not None:
            tracker["metadata_baseline_opens"] = tracker.get("metadata_baseline_opens", 0) + 1
        original.execute("PRAGMA query_only=ON")
        original.set_progress_handler(lambda: int(monotonic() >= deadline), 100)
        rows = original.execute("SELECT * FROM copilot_meta WHERE rowid<=? ORDER BY rowid LIMIT 3",
                                (mark["minimum"],)).fetchall()
    if len(rows) != 2 or {r[0] for r in rows} != {"schema_version", "engine_version"}:
        return False
    digest = sha256()
    for row in rows:
        digest.update(json.dumps(row, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n")
    if len(rows) != mark.get("prefix_rows") or digest.hexdigest() != mark.get("prefix_sha256"):
        return False
    active = db.execute("SELECT key,value_json FROM copilot_meta WHERE key IN (?,?) ORDER BY key",
                        ("schema_version", "engine_version")).fetchall()
    return dict(active) == {r[0]: r[1] for r in rows} and file_identity(path) == baseline["file_identity"]


def observe_database(request: dict, roots: list[str], deadline: float, tracker: dict | None = None,
                     *, capture_baseline: bool = False) -> dict:
    path = local_file(request["path"], roots)
    for suffix in ("-wal", "-shm", "-journal"):
        local_file(str(path) + suffix, roots, require_file=False)
    identity = file_identity(path)
    if monotonic() >= deadline:
        raise TimeoutError("RUNTIME_DATABASE_PROBE_TIMEOUT")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)) as db:
        if tracker is not None:
            tracker["database_opens"] += 1
        db.set_progress_handler(lambda: int(monotonic() >= deadline), 100)
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if request.get("epoch_boundary") is not None:
            rows = db.execute("SELECT id,payload_json FROM data_epoch_boundary LIMIT 2").fetchall()
            if len(rows) != 1 or rows[0][0] != 1:
                raise ValueError("NEW_EPOCH_BOUNDARY_MISSING")
            actual = json.loads(rows[0][1])
            if (not isinstance(actual, dict) or not actual.get("created_at")
                    or any(actual.get(key) != value for key, value in request["epoch_boundary"].items())):
                raise ValueError("NEW_EPOCH_DATABASE_BOUNDARY_CHANGED")
        schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        watermarks = []
        for mark in request.get("watermarks", []):
            table, column = identifier(mark["table"]), identifier(mark["column"])
            row = db.execute(f"SELECT MAX({column}) FROM {table}").fetchone()
            value = row[0]
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError("NONINTEGER_BUSINESS_WATERMARK")
            baseline = value if capture_baseline else mark["minimum"]
            if baseline is not None and (not isinstance(baseline, int) or isinstance(baseline, bool)):
                raise ValueError("INVALID_BUSINESS_WATERMARK_BASELINE")
            # The retained baseline prefix must remain intact as new events append.
            prefix = sha256()
            count = 0
            if baseline is not None:
                for item in db.execute(f"SELECT * FROM {table} WHERE {column}<=? ORDER BY {column}", (baseline,)):
                    encoded = json.dumps(item, ensure_ascii=True, separators=(",", ":"),
                                         default=lambda item: {"bytes_hex": item.hex()} if isinstance(item, bytes) else str(item))
                    prefix.update(encoded.encode("ascii") + b"\n")
                    count += 1
            observed_mark = {"table": mark["table"], "column": mark["column"],
                               "minimum": baseline, "current": value,
                               "prefix_rows": count, "prefix_sha256": prefix.hexdigest()}
            if not capture_baseline and request.get("metadata_baseline") and mark["table"] == "copilot_meta":
                observed_mark["initialization_metadata_compatible"] = initialization_metadata_compatible(
                    db, request, mark, roots, deadline, tracker)
            watermarks.append(observed_mark)
        db.rollback()
    if identity != file_identity(path):
        raise ValueError("DATABASE_REPLACED_DURING_PROBE")
    if monotonic() >= deadline:
        raise TimeoutError("RUNTIME_DATABASE_PROBE_TIMEOUT")
    return {"role": request["role"], "path": str(path), "file_identity": identity,
            **schema_observation(schema, request),
            "watermarks": watermarks}


def check_snapshot(stamp: dict, roots: list[str]) -> Path:
    snapshot = local_file(stamp["path"], roots)
    info = snapshot.stat()
    if (info.st_size != stamp["bytes"] or info.st_mtime_ns != stamp["mtime_ns"]
            or file_identity(snapshot) != stamp["file_identity"]):
        raise ValueError("VALIDATED_SNAPSHOT_CHANGED")
    actual = {str(snapshot) + suffix for suffix in ("-wal", "-shm")
              if local_file(str(snapshot) + suffix, roots, require_file=False).exists()}
    if actual != {r["path"] for r in stamp["wal_shm"]}:
        raise ValueError("VALIDATED_SNAPSHOT_COMPANIONS_CHANGED")
    for row in stamp["wal_shm"]:
        file = local_file(row["path"], roots).stat()
        if file.st_size != row["bytes"] or file.st_mtime_ns != row["mtime_ns"]:
            raise ValueError("VALIDATED_SNAPSHOT_COMPANIONS_CHANGED")
    return snapshot


def observe_activation(row: dict, roots: list[str], deadline: float, tracker: dict) -> dict:
    snapshot = check_snapshot(row["snapshot"], roots)
    baseline = observe_database({"role": row["role"], "path": str(snapshot),
        "watermarks": row["watermarks"]}, roots, deadline, tracker, capture_baseline=True)
    current = observe_database({"role": row["role"], "path": row["path"],
        "watermarks": baseline["watermarks"]}, roots, deadline, tracker)
    if current["file_identity"] == row["original_identity"]:
        raise ValueError("ACTIVE_DATABASE_LINKED_TO_RECOVERY_ORIGINAL")
    if current["schema_sha256"] != baseline["schema_sha256"]:
        raise ValueError("ACTIVATION_SCHEMA_MISMATCH")
    if current["watermarks"] != baseline["watermarks"]:
        raise ValueError("ACTIVATION_BUSINESS_BASELINE_MISMATCH")
    check_snapshot(row["snapshot"], roots)
    return {**current, "baseline_snapshot": str(snapshot),
            "baseline_file_identity": baseline["file_identity"]}


def main() -> int:
    try:
        request = json.loads(sys.stdin.buffer.read(256 * 1024 + 1))
        seconds = float(request["budget_seconds"])
        if not isfinite(seconds) or seconds <= 0 or seconds > 5 or len(request["databases"]) > 5:
            raise ValueError("INVALID_PROBE_BUDGET")
        deadline = monotonic() + seconds
        observations = []
        tracker = {"database_opens": 0}
        for row in request["databases"]:
            try:
                if request.get("action") == "activation":
                    if row.get("epoch_boundary") is not None:
                        observations.append(observe_database(row, request["roots"], deadline, tracker,
                                                             capture_baseline=True))
                    else:
                        observations.append(observe_activation(row, request["roots"], deadline, tracker))
                else:
                    observations.append(observe_database(row, request["roots"], deadline, tracker))
            except (OSError, ValueError, sqlite3.Error, TimeoutError) as exc:
                print(json.dumps({"ok": False, "role": row.get("role"),
                                  **tracker,
                                  "code": str(exc) if isinstance(exc, (ValueError, TimeoutError)) else type(exc).__name__}))
                return 2
        print(json.dumps({"ok": True, "observations": observations, **tracker}, ensure_ascii=True))
        return 0
    except (KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "code": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
