"""Explicit new-minute-epoch checks, separate from complete recovery claims."""
from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from time import monotonic

from cloud_archive_inventory import checked_path


PRESERVED_ROLES = {"main", "full_watch", "opening_research", "signal_copilot"}
MISSING_RECORDS = {"minute_bars", "pending_tasks", "evaluations", "event_records", "manual_position_revisions"}


def declaration_hash(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def check(declaration: dict, acceptance: dict | None, *, roots: list[Path],
          allow_test_only: bool = False) -> dict:
    result = {"ok": False, "database_creation_allowed": False, "can_launch": False,
              "qualified_signal_authorized": False, "business_writes": 0,
              "fault_drive_reads": 0, "old_position_continuity": "UNKNOWN",
              "old_business_continuity": "UNKNOWN", "errors": []}
    try:
        if declaration.get("schema") != "KQUANT_NEW_MINUTE_EPOCH_V1":
            raise ValueError("UNSUPPORTED_EPOCH_DECLARATION")
        runtime = checked_path(declaration["runtime_root"], roots)
        target = checked_path(declaration["minute_path"], roots)
        session = date.fromisoformat(declaration["session"])
        epoch_id = declaration["epoch_id"]
        if not isinstance(epoch_id, str) or not epoch_id or len(epoch_id) > 100:
            raise ValueError("INVALID_EPOCH_ID")
        schema_hash = declaration.get("schema_sha256", "")
        if (not isinstance(schema_hash, str) or len(schema_hash) != 64
                or any(char not in "0123456789abcdef" for char in schema_hash)):
            raise ValueError("EXACT_SCHEMA_HASH_REQUIRED")
        expected = runtime / "work" / ("options_one_minute-epoch-" + session.strftime("%Y%m%d")) / "one_minute.sqlite3"
        if target != expected:
            raise ValueError("EXACT_NEW_EPOCH_PATH_REQUIRED")
        if (set(declaration.get("preserved_roles", [])) != PRESERVED_ROLES
                or set(declaration.get("unresolved_old_records", [])) != MISSING_RECORDS
                or declaration.get("old_position_continuity") != "UNKNOWN"
                or declaration.get("complete_restoration_claimed") is not False):
            raise ValueError("OLD_BUSINESS_BOUNDARY_REQUIRED")
        if declaration.get("execution_enabled") is not False or declaration.get("qualified_signal_authorized") is not False:
            raise ValueError("EPOCH_CANNOT_AUTHORIZE_EXECUTION_OR_SIGNALS")
        if declaration.get("test_only") and not allow_test_only:
            raise ValueError("TEST_ONLY_EPOCH_NOT_PRODUCTION")
        if not acceptance:
            raise ValueError("EXACT_DATA_SCOPE_ACCEPTANCE_REQUIRED")
        if acceptance.get("test_only") and not allow_test_only:
            raise ValueError("TEST_ONLY_ACCEPTANCE_NOT_PRODUCTION")
        if (acceptance.get("gate") != "O-SETUP" or acceptance.get("status") != "APPROVED"
                or acceptance.get("approved_by") != "OWNER"
                or acceptance.get("decision") != "NEW_MINUTE_EPOCH"
                or acceptance.get("declaration_sha256") != declaration_hash(declaration)
                or acceptance.get("runtime_root") != str(runtime)
                or acceptance.get("minute_path") != str(target)
                or acceptance.get("epoch_id") != epoch_id
                or acceptance.get("session") != session.isoformat()
                or acceptance.get("old_position_continuity") != "UNKNOWN"
                or not acceptance.get("accepted_at") or not acceptance.get("human_decision_evidence")):
            raise ValueError("EXACT_DATA_SCOPE_ACCEPTANCE_MISMATCH")
        stamp = datetime.fromisoformat(acceptance["accepted_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("ACCEPTANCE_TIMEZONE_REQUIRED")
        if target.exists():
            raise ValueError("NEW_EPOCH_TARGET_ALREADY_EXISTS_NO_OVERWRITE")
        for suffix in ("-wal", "-shm", "-journal"):
            companion = checked_path(str(target) + suffix, roots)
            if companion.exists():
                raise ValueError("NEW_EPOCH_COMPANION_ALREADY_EXISTS")
        result.update(ok=True, database_creation_allowed=True, epoch_id=epoch_id,
                      session=session.isoformat(), minute_path=str(target),
                      declaration_sha256=declaration_hash(declaration))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["errors"].append({"code": str(exc) if isinstance(exc, ValueError) else type(exc).__name__})
    return result


def initialize(declaration: dict, acceptance: dict | None, *, roots: list[Path],
               schema: str, allow_test_only: bool = False, budget_seconds: float = 5) -> dict:
    """Create a new store only; never copy, open or rewrite the missing old store."""
    result = check(declaration, acceptance, roots=roots, allow_test_only=allow_test_only)
    if not result["ok"]:
        return result
    if sha256(schema.encode("utf-8")).hexdigest() != declaration["schema_sha256"]:
        return {**result, "ok": False, "database_creation_allowed": False,
                "errors": [{"code": "EXACT_NEW_EPOCH_SCHEMA_MISMATCH"}]}
    if not 0 < budget_seconds <= 5:
        return {**result, "ok": False, "database_creation_allowed": False,
                "errors": [{"code": "INVALID_INITIALIZATION_BUDGET"}]}
    deadline = monotonic() + budget_seconds
    target = Path(result["minute_path"])
    temporary = target.with_name(target.name + ".preparing")
    try:
        checked_path(temporary, roots)
        if temporary.exists():
            raise ValueError("EXISTING_PREPARATION_REQUIRES_REVIEW")
        target.parent.mkdir(parents=True, exist_ok=True)
        checked_path(temporary, roots)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        connection = sqlite3.connect(temporary, timeout=min(1, budget_seconds))
        try:
            connection.set_progress_handler(lambda: int(monotonic() >= deadline), 100)
            connection.set_authorizer(lambda operation, *unused:
                sqlite3.SQLITE_DENY if operation in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}
                else sqlite3.SQLITE_OK)
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(schema)
            connection.execute("CREATE TABLE data_epoch_boundary (id INTEGER PRIMARY KEY CHECK(id=1), payload_json TEXT NOT NULL)")
            metadata = {"schema": declaration["schema"], "epoch_id": declaration["epoch_id"],
                        "session": declaration["session"], "created_at": datetime.now(UTC).isoformat(),
                        "declaration_sha256": result["declaration_sha256"],
                        "data_scope_acceptance_sha256": declaration_hash(acceptance),
                        "record_kind": "NEW_DATA_NOT_OLD_RECOVERY", "old_position_continuity": "UNKNOWN",
                        "unresolved_old_records": sorted(MISSING_RECORDS), "complete_restoration_claimed": False}
            connection.execute("INSERT INTO data_epoch_boundary VALUES (1,?)", (json.dumps(metadata, sort_keys=True),))
            connection.commit()
            integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
            if integrity != ["ok"]:
                raise ValueError("NEW_EPOCH_INTEGRITY_FAILED")
        finally:
            connection.close()
        if monotonic() >= deadline:
            raise TimeoutError("EPOCH_INITIALIZATION_BUDGET_EXHAUSTED")
        checked_path(target, roots)
        checked_path(temporary, roots)
        # On Windows rename refuses an existing target, including a concurrent creator.
        temporary.rename(target)
        result.update(database_created=True, business_writes=1,
                      integrity=integrity, record_kind="NEW_DATA_NOT_OLD_RECOVERY",
                      file_identity={"device": target.stat().st_dev, "inode": target.stat().st_ino})
    except (OSError, ValueError, sqlite3.Error, TimeoutError) as exc:
        result.update(ok=False, database_created=False, database_creation_allowed=False)
        result["errors"].append({"code": str(exc) if isinstance(exc, (ValueError, TimeoutError)) else type(exc).__name__})
        result["preparation_requires_review"] = True
    return result
