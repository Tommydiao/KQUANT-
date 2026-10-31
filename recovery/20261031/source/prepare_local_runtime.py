"""Prepare reversible local candidates from read-only inspection copies only.

Original DB/WAL/SHM files are byte-hashed, never opened with SQLite. No market
connection, credential load, production start, minute-store creation or approval.
"""
from __future__ import annotations

import ast
from contextlib import closing
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "development/workspace"
ORIGINAL = ROOT / "recovered-data"
INSPECTION = ROOT / "inspection-data"
ROLES = {
    "main": "work/kquant_us.sqlite3",
    "full_watch": "work/options_full_watch/full_watch.sqlite3",
    "opening_research": "work/options_one_minute/opening_trend_research.sqlite3",
    "signal_copilot": "work/options_signal_copilot/signal_copilot.sqlite3",
}
MARKS = {
    "main": ["audit_events", "option_runtime_tasks", "option_runtime_events", "stock_watchlist_members"],
    "full_watch": ["full_watch_runs", "full_watch_quota_queue"],
    "opening_research": ["revisions", "qualification_jobs", "publication_offsets"],
    "signal_copilot": ["copilot_meta", "signals", "paper_events"],
}
MISSING_RECORDS = ["evaluations", "event_records", "manual_position_revisions", "minute_bars", "pending_tasks"]


def stamp():
    return datetime.now(UTC).isoformat()


def safe(path: Path):
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(ROOT):
        raise ValueError("OUTSIDE_THIS_LOCAL_CANDIDATE")
    for part in reversed([path, *path.parents]):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("REPARSE_OR_LINK_PATH")
    return path


def digest(path: Path):
    path = safe(path)
    before = path.stat()
    result = sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("FILE_CHANGED_DURING_BYTE_HASH")
    return {"path": str(path), "bytes": after.st_size, "mtime_ns": after.st_mtime_ns,
            "sha256": result.hexdigest(), "file_identity": {"device": after.st_dev, "inode": after.st_ino}}


def write_new(path: Path, value):
    path = safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def q(name: str):
    return '"' + name.replace('"', '""') + '"'


def inspect(db):
    schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    tables = []
    for name, sql in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' "
                                "AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        columns = [{"name": r[1], "type": r[2], "not_null": bool(r[3]), "pk_rank": r[5]}
                   for r in db.execute(f"PRAGMA table_info({q(name)})")]
        row_count = db.execute(f"SELECT COUNT(*) FROM {q(name)}").fetchone()[0]
        tables.append({"table": name, "rows": row_count, "columns": columns, "sql": sql})
    return {"schema_sha256": sha256(json.dumps(schema, ensure_ascii=True).encode("ascii")).hexdigest(),
            "schema": schema, "tables": tables}


def main():
    started = stamp()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-pid" + str(os.getpid())
    out = safe(ROOT / "evidence" / ("local-runtime-preparation-" + run_id))
    snapshots = safe(ROOT / "validated-snapshots" / run_id)
    out.mkdir(parents=True, exist_ok=False)
    snapshots.mkdir(parents=True, exist_ok=False)
    events = out / "events.jsonl"
    count = {"original_database_opens": 0, "inspection_database_opens": 0,
             "candidate_database_opens": 0, "provider_requests": 0,
             "owner_acceptance_written": False, "minute_database_created": False, "production_started": False}
    result = {"schema": "KQUANT_LOCAL_RUNTIME_PREPARATION_V1", "status": "STARTED",
              "started_at": started, "pid": os.getpid(), "runtime_root": str(RUNTIME),
              "executable": sys.executable, "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "old_business_continuity": "UNKNOWN", "old_position_continuity": "UNKNOWN",
              "complete_restoration_claimed": False, "can_launch": False, **count,
              "databases": [], "errors": []}
    write_new(out / "started.json", result)

    def event(kind, **values):
        payload = {"at": stamp(), "kind": kind, "pid": os.getpid(), **values}
        with events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=True) + "\n")
        print(json.dumps(payload, ensure_ascii=True), flush=True)

    deadline = monotonic() + 1800
    original_before = None
    try:
        manifest_path = ORIGINAL / "DATA_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        expected = {"business/" + relative for relative in ROLES.values()}
        allowed = {p + suffix for p in expected for suffix in ("", "-wal", "-shm")}
        if len(manifest) != 10 or any(row["path"] not in allowed for row in manifest):
            raise ValueError("EXACT_TRANSFERRED_FOUR_STORE_MANIFEST_REQUIRED")
        original_before = {}
        for row in manifest:
            facts = digest(ORIGINAL / row["path"])
            if facts["sha256"] != row["sha256"] or facts["bytes"] != row["bytes"]:
                raise ValueError("TRANSFERRED_ORIGINAL_BYTE_HASH_MISMATCH")
            original_before[row["path"]] = facts
        write_new(out / "original-byte-inventory-before.json", original_before)
        result["manifest_sha256"] = sha256(manifest_path.read_bytes()).hexdigest()
        event("ORIGINALS_BYTE_VERIFIED", files=len(original_before), original_database_opens=0)
        free = shutil.disk_usage(ROOT).free
        required = 3 * sum(row["bytes"] for row in manifest) + 1024 ** 3
        if free < required:
            raise ValueError("INSUFFICIENT_LOCAL_CANDIDATE_FREE_SPACE")
        result["disk_free_bytes_before"] = free
        # Check every output and companion before making the first candidate.
        for relative in ROLES.values():
            for base in (RUNTIME / relative, snapshots / relative):
                for suffix in ("", "-wal", "-shm", "-journal", ".preparing"):
                    if safe(Path(str(base) + suffix)).exists():
                        raise ValueError("EXISTING_CANDIDATE_NO_OVERWRITE")
        for role, relative in ROLES.items():
            if monotonic() >= deadline:
                raise TimeoutError("LOCAL_CANDIDATE_PREPARATION_BUDGET_EXHAUSTED")
            source = safe(INSPECTION / relative)
            original_key = "business/" + relative
            source_before = {}
            for suffix in ("", "-wal", "-shm"):
                path = Path(str(source) + suffix)
                key = original_key + suffix
                if path.exists() != (key in original_before):
                    raise ValueError("INSPECTION_COMPANION_SET_CHANGED")
                if path.exists():
                    facts = digest(path)
                    if suffix != "-shm" and (facts["sha256"] != original_before[key]["sha256"]
                                               or facts["bytes"] != original_before[key]["bytes"]):
                        raise ValueError("INSPECTION_MAIN_OR_WAL_DIFFERS_FROM_ORIGINAL")
                    source_before[suffix] = facts
            target, active = safe(snapshots / relative), safe(RUNTIME / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = safe(Path(str(target) + ".preparing"))
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            event("READ_ONLY_BACKUP_STARTED", role=role, source=str(source), snapshot=str(target))
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=2)) as src:
                count["inspection_database_opens"] += 1
                src.execute("PRAGMA query_only=ON")
                src.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
                src.execute("BEGIN")
                src.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
                source_quick = [r[0] for r in src.execute("PRAGMA quick_check")]
                source_integrity = [r[0] for r in src.execute("PRAGMA integrity_check")]
                if source_quick != ["ok"] or source_integrity != ["ok"]:
                    raise ValueError("INSPECTION_LOGICAL_INTEGRITY_FAILED")
                source_info = inspect(src)
                with closing(sqlite3.connect(temporary.as_uri() + "?mode=rw", uri=True, timeout=2)) as dst:
                    count["candidate_database_opens"] += 1
                    def backup_progress(status, remaining, total):
                        if monotonic() >= deadline:
                            raise TimeoutError("LOCAL_CANDIDATE_BACKUP_BUDGET_EXHAUSTED")
                    src.backup(dst, pages=256, progress=backup_progress, sleep=0.01)
                    dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    journal = dst.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
                    dst.execute("PRAGMA synchronous=FULL")
                    dst.commit()
                    quick = [r[0] for r in dst.execute("PRAGMA quick_check")]
                    integrity = [r[0] for r in dst.execute("PRAGMA integrity_check")]
                    info = inspect(dst)
                    if journal.lower() != "delete" or quick != ["ok"] or integrity != ["ok"]:
                        raise ValueError("VALIDATED_SNAPSHOT_INTEGRITY_OR_JOURNAL_FAILED")
                    if info != source_info:
                        raise ValueError("BACKUP_SCHEMA_OR_TABLE_COUNTS_CHANGED")
                src.rollback()
            for suffix in ("-wal", "-shm", "-journal"):
                if Path(str(temporary) + suffix).exists():
                    raise ValueError("VALIDATED_SNAPSHOT_COMPANION_REMAINS")
            temporary.rename(target)
            snapshot_facts = digest(target)
            active.parent.mkdir(parents=True, exist_ok=True)
            with target.open("rb") as source_bytes, active.open("xb") as active_bytes:
                shutil.copyfileobj(source_bytes, active_bytes, 1024 * 1024)
                active_bytes.flush()
                os.fsync(active_bytes.fileno())
            active_facts = digest(active)
            if active_facts["sha256"] != snapshot_facts["sha256"]:
                raise ValueError("ACTIVE_CANDIDATE_BYTE_HASH_MISMATCH")
            if active_facts["file_identity"] == snapshot_facts["file_identity"]:
                raise ValueError("ACTIVE_CANDIDATE_LINKED_TO_SNAPSHOT")
            watermarks = []
            with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
                count["candidate_database_opens"] += 1
                db.execute("PRAGMA query_only=ON")
                tables = {t["table"]: t for t in info["tables"]}
                for table in MARKS[role]:
                    if table not in tables:
                        raise ValueError("SELECTED_BUSINESS_BASELINE_TABLE_MISSING")
                    value = db.execute(f"SELECT MAX(rowid) FROM {q(table)}").fetchone()[0]
                    if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                        raise ValueError("BUSINESS_ROWID_NOT_INTEGER")
                    watermarks.append({"table": table, "column": "rowid", "minimum": value,
                                       "rows": tables[table]["rows"], "scope": "selected small business baseline only"})
            for suffix, before in source_before.items():
                if suffix != "-shm" and digest(Path(str(source) + suffix)) != before:
                    raise ValueError("INSPECTION_MAIN_OR_WAL_CHANGED_DURING_BACKUP")
            origin = original_before[original_key]
            companion_rows = [original_before[original_key + suffix] for suffix in ("-wal", "-shm")
                              if original_key + suffix in original_before]
            proof = {"schema": "KQUANT_RECOVERY_SNAPSHOT_VERIFICATION_V1", "test_only": False,
                     "role": role, "database_path": origin["path"], "bytes": origin["bytes"],
                     "mtime_ns": origin["mtime_ns"], "sha256": origin["sha256"],
                     "file_identity": origin["file_identity"], "wal_shm": companion_rows,
                     "verified_at": stamp(), "quick_check": source_quick, "integrity": source_integrity,
                     "verification_method": "Byte-matched main/WAL inspection copy, SQLite mode=ro, consistent backup; original unopened",
                     "original_database_opens": 0,
                     "validated_snapshot": {**snapshot_facts, "integrity": integrity, "quick_check": quick,
                                            "wal_shm": [], "journal_mode": "delete"}}
            proof_path = out / (role + "-recovery.json")
            write_new(proof_path, proof)
            record = {"role": role, "recovery_path": origin["path"], "path": str(active),
                      "recovery_state": "COMPLETE_VERIFIED",
                      "receipt": {"path": str(proof_path), "sha256": digest(proof_path)["sha256"]},
                      "watermarks": [{"table": m["table"], "column": m["column"]} for m in watermarks],
                      "selected_watermark_observations": watermarks,
                      "validated_snapshot": snapshot_facts, "active_candidate": active_facts,
                      "schema_sha256": info["schema_sha256"], "tables": info["tables"],
                      "source_quick_check": source_quick, "source_integrity_check": source_integrity,
                      "snapshot_quick_check": quick, "snapshot_integrity_check": integrity,
                      "active_sha256_matches_validated_snapshot": True,
                      "cross_store_continuity_confirmed": False}
            result["databases"].append(record)
            write_new(out / (role + "-candidate.json"), record)
            event("PRESERVED_STORE_CANDIDATE_VERIFIED", role=role, bytes=active_facts["bytes"],
                  schema_sha256=info["schema_sha256"], tables=len(info["tables"]))
        # Extract the literal schema without importing business modules or runtime paths.
        source_path = RUNTIME / "kquant/options_one_minute.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
        schema = next(ast.literal_eval(node.value) for node in tree.body
                      if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "SCHEMA" for target in node.targets))
        if not isinstance(schema, str):
            raise ValueError("MINUTE_SCHEMA_LITERAL_REQUIRED")
        session = "2026-10-07"
        minute = RUNTIME / "work/options_one_minute-epoch-20261007/one_minute.sqlite3"
        for suffix in ("", "-wal", "-shm", "-journal"):
            if safe(Path(str(minute) + suffix)).exists():
                raise ValueError("MINUTE_FILE_ALREADY_EXISTS_NO_CREATION_AUTHORIZATION")
        schema_path = out / "minute-schema.sql"
        with schema_path.open("x", encoding="utf-8", newline="") as stream:
            stream.write(schema)
        declaration = {"schema": "KQUANT_NEW_MINUTE_EPOCH_V1", "runtime_root": str(RUNTIME),
                       "minute_path": str(minute), "epoch_id": "minute-new-session-20261007-local-v1",
                       "session": session, "schema_sha256": sha256(schema.encode("utf-8")).hexdigest(),
                       "preserved_roles": sorted(ROLES), "unresolved_old_records": MISSING_RECORDS,
                       "old_position_continuity": "UNKNOWN", "complete_restoration_claimed": False,
                       "execution_enabled": False, "qualified_signal_authorized": False}
        declaration_path = out / "new-minute-epoch-declaration-proposed.json"
        write_new(declaration_path, declaration)
        result["new_minute_epoch_proposal"] = {"path": str(declaration_path), "sha256": digest(declaration_path)["sha256"],
             "schema_path": str(schema_path), "schema_sha256": digest(schema_path)["sha256"],
             "exact_data_scope_accepted": False, "database_created": False,
             "note": "First actual accepted session must be updated if this window is missed; this document is only a proposal."}
        result["status"] = "FOUR_PRESERVED_CANDIDATES_PREPARED_MINUTE_SCOPE_NOT_ACCEPTED"
    except Exception as exc:
        result["status"] = "FAILED_RETAIN_PARTIAL_CANDIDATES_FOR_REVIEW"
        result["errors"].append({"type": type(exc).__name__, "code": str(exc)})
        event("PREPARATION_FAILED", error_type=type(exc).__name__, code=str(exc))
    finally:
        result.update(count)
        if original_before is not None:
            try:
                original_after = {key: digest(Path(value["path"])) for key, value in original_before.items()}
                write_new(out / "original-byte-inventory-after.json", original_after)
                result["all_original_main_wal_shm_unchanged"] = original_after == original_before
                if original_after != original_before:
                    result["status"] = "FAILED_ORIGINAL_BYTE_SET_CHANGED"
                    result["errors"].append({"code": "ORIGINAL_BYTE_SET_CHANGED"})
            except Exception as exc:
                result["status"] = "FAILED_ORIGINAL_FINAL_RECHECK"
                result["errors"].append({"type": type(exc).__name__, "code": str(exc)})
        result["finished_at"] = stamp()
        result["receipt_path"] = str(out / "receipt.json")
        write_new(out / "receipt.json", result)
        event("PREPARATION_FINISHED", status=result["status"], receipt=result["receipt_path"], **count)
    return 0 if result["status"] == "FOUR_PRESERVED_CANDIDATES_PREPARED_MINUTE_SCOPE_NOT_ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
