"""Freeze-gated candidate archive and isolated restore verification.

This tool never discovers files to include. Explicit source files are whitelisted
by a hashed freeze manifest; the four prepared snapshots and immutable minute
page closure are added from their exact receipts. It does not load credentials,
instantiate the mutable minute PageStore, start services, or write acceptance.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
FREEZE_SCHEMA = "KQUANT_CANDIDATE_ARCHIVE_FREEZE_V1"
ARCHIVE_SCHEMA = "KQUANT_CANDIDATE_ARCHIVE_MANIFEST_V1"
MINUTE_SCHEMA = "KQUANT_ISOLATED_MINUTE_REBUILD_V1"
ROLES = {"main", "full_watch", "opening_research", "signal_copilot"}
SCOPE = {"artifact_scope": "CANDIDATE_ONLY", "old_business_continuity": "UNKNOWN",
         "old_position_continuity": "UNKNOWN", "owner_acceptance_written": False,
         "production_started": False, "execution_enabled": False,
         "qualified_signal_authorized": False, "complete_restoration_claimed": False,
         "can_launch": False, "cloud_roundtrip_verified": False}
FORBIDDEN_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                   ".mypy_cache", ".ruff_cache", ".cache", "cache", "caches", "wheels",
                   "credentials", "secrets", "dpapi", "browser-profile", "pytest-temp"}
# This reviewed, frozen module is ordinary source code, not a credential store.
# Its exception cannot admit changed .py bytes or any local DPAPI/env material.
PINNED_SOURCE_EXCEPTIONS = {
    "development/workspace/kquant/options_llm_credentials.py":
        "0aa4feac597dae0aa697d07bc0a2a8e31f10787ca2b58956b4e1c98959771302",
}
TEXT_LIMIT = 64 * 1024 * 1024
MAX_FILES = 100_000
MAX_TOTAL = 100 * 1024**3


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def stamp():
    return datetime.now(UTC).isoformat()


def relative(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("UNSAFE_RELATIVE_PATH")
    parts = PurePosixPath(value).parts
    if value.startswith("/") or "/".join(parts) != value or any(
            p in {"", ".", ".."} or p.endswith((".", " ")) or any(ord(c) < 32 for c in p)
            or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p) for p in parts):
        raise ValueError("UNSAFE_RELATIVE_PATH")
    return value


def safe(root, rel, *, existing=True):
    path = root / relative(rel)
    for part in [root, *path.parents, path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("REPARSE_OR_LINK_PATH")
    if existing and not path.is_file():
        raise ValueError("WHITELIST_FILE_MISSING")
    return path


def is_secret_or_dependency(rel):
    folded = relative(rel).casefold()
    if folded in PINNED_SOURCE_EXCEPTIONS or folded.removeprefix("source/") in PINNED_SOURCE_EXCEPTIONS:
        return False
    parts = folded.split("/")
    return any(p in FORBIDDEN_PARTS or p.startswith(".env")
               or re.search(r"(?:^|[._-])(credentials?|secrets?|private[-_]?keys?|token[-_]?store|access[-_]?token|refresh[-_]?token)(?:[._-]|$)", p)
               for p in parts)


def explicit_source_allowed(rel):
    folded = rel.casefold()
    if is_secret_or_dependency(rel) or rel.endswith(("-wal", "-shm", "-journal", ".tmp", ".preparing")):
        raise ValueError("SECRET_DEPENDENCY_OR_MUTABLE_FILE_EXCLUDED")
    # Historical raw data, active stores and minute pages have dedicated paths.
    if folded.startswith(("recovered-data/", "inspection-data/", "validated-snapshots/", "minute-rebuild/")):
        raise ValueError("SOURCE_REQUIRES_DEDICATED_RECEIPT")
    if folded.startswith("development/workspace/work/"):
        raise ValueError("ACTIVE_STORE_EXCLUDED")
    if PurePosixPath(rel).suffix.lower() not in {
            ".py", ".ps1", ".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".sql", ".csv",
            ".ts", ".tsx", ".js", ".jsx", ".cjs", ".css", ".html", ".webmanifest", ".svg", ".png", ".jpg", ".ico",
            ".woff2", ".map", ".xml", ".log", ".lock"}:
        raise ValueError("UNWHITELISTED_BINARY_OR_DATABASE")
    if not (rel.startswith(("development/workspace/", "development/handoff/", "evidence/"))
            or "/" not in rel):
        raise ValueError("SOURCE_NOT_IN_PROJECT_WHITELIST_ROOT")


def facts(path):
    before = path.stat()
    result = hashlib.sha256()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        while block := stream.read(1024 * 1024):
            result.update(block)
        ended = os.fstat(stream.fileno())
    after = path.stat()
    key = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if len({key(before), key(opened), key(ended), key(after)}) != 1:
        raise ValueError("SOURCE_CHANGED_DURING_CAPTURE")
    return {"bytes": after.st_size, "sha256": result.hexdigest(), "mtime_ns": after.st_mtime_ns,
            "file_identity": {"device": after.st_dev, "inode": after.st_ino}}


def bounded_bytes(path):
    with path.open("rb") as stream:
        raw = stream.read(TEXT_LIMIT + 1)
    if len(raw) > TEXT_LIMIT:
        raise ValueError("JSON_CAPTURE_TOO_LARGE")
    return raw


def ref_source(ref):
    if not isinstance(ref, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256", ""))):
        raise ValueError("INVALID_HASHED_FILE_REFERENCE")
    if not isinstance(ref.get("bytes"), int) or isinstance(ref["bytes"], bool) or ref["bytes"] < 0:
        raise ValueError("INVALID_HASHED_FILE_SIZE")
    source = relative(ref.get("source"))
    if is_secret_or_dependency(source):
        raise ValueError("SECRET_DEPENDENCY_EXCLUDED_BEFORE_OPEN")
    return source


def verify_pinned_source(source, sha256):
    expected = PINNED_SOURCE_EXCEPTIONS.get(source.casefold())
    if expected is not None and sha256 != expected:
        raise ValueError("PINNED_CREDENTIAL_LOADER_SOURCE_CHANGED")


def file_ref(root, ref, *, kind, archive):
    source = ref_source(ref)
    path = safe(root, source)
    observed = facts(path)
    verify_pinned_source(source, observed["sha256"])
    if any(observed[k] != ref[k] for k in ("bytes", "sha256")):
        raise ValueError("FROZEN_SOURCE_HASH_OR_SIZE_MISMATCH")
    return {"source": source, "archive": relative(archive), "kind": kind, **observed}


def read_ref_json(root, ref, *, kind, archive):
    # Capture atomic-index bytes once. The same immutable bytes are parsed and
    # written to the ZIP; the source is separately rechecked after packaging.
    source = ref_source(ref)
    path = safe(root, source)
    before = path.stat()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(TEXT_LIMIT + 1)
        ended = os.fstat(stream.fileno())
    after = path.stat()
    key = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if len({key(before), key(opened), key(ended), key(after)}) != 1:
        raise ValueError("FROZEN_JSON_CHANGED_DURING_CAPTURE")
    if len(raw) > TEXT_LIMIT:
        raise ValueError("JSON_CAPTURE_TOO_LARGE")
    if hashlib.sha256(raw).hexdigest() != ref["sha256"] or len(raw) != ref["bytes"]:
        raise ValueError("FROZEN_JSON_CHANGED_DURING_CAPTURE")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("JSON_OBJECT_REQUIRED")
    record = {"source": source, "archive": relative(archive), "kind": kind,
              "bytes": len(raw), "sha256": ref["sha256"], "mtime_ns": after.st_mtime_ns,
              "file_identity": {"device": after.st_dev, "inode": after.st_ino}}
    return record, value, raw


def closure(index, read_page):
    if index.get("schema") != MINUTE_SCHEMA or not isinstance(index.get("tasks"), dict):
        raise ValueError("INVALID_MINUTE_INDEX")
    metadata = index.get("page_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("INVALID_MINUTE_PAGE_METADATA")
    page_tasks = {}
    states = Counter()
    for task_id, task_record in index["tasks"].items():
        if not re.fullmatch(r"[0-9a-f]{64}", task_id) or not isinstance(task_record, dict):
            raise ValueError("INVALID_MINUTE_TASK")
        pages = task_record.get("pages")
        if not isinstance(pages, list) or len(pages) != len(set(pages)):
            raise ValueError("INVALID_MINUTE_TASK_PAGE_SET")
        states[str(task_record.get("coverage", {}).get("state", "UNOBSERVED"))] += 1
        for page_sha in pages:
            if not isinstance(page_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", page_sha):
                raise ValueError("INVALID_MINUTE_PAGE_HASH")
            if page_sha in page_tasks:
                raise ValueError("MINUTE_PAGE_REFERENCED_BY_MULTIPLE_TASKS")
            page_tasks[page_sha] = task_id
    if set(metadata) != set(page_tasks):
        raise ValueError("MINUTE_METADATA_PAGE_CLOSURE_MISMATCH")
    if len(page_tasks) > MAX_FILES:
        raise ValueError("MINUTE_PAGE_COUNT_LIMIT")
    rows, errors = 0, 0
    for page_sha, task_id in sorted(page_tasks.items()):
        raw = read_page(page_sha)
        if hashlib.sha256(raw).hexdigest() != page_sha:
            raise ValueError("IMMUTABLE_MINUTE_PAGE_CHANGED")
        page = json.loads(raw)
        task = dict(page.get("task", {}))
        observed_id = task.pop("task_id", None)
        if (page.get("schema") != MINUTE_SCHEMA or observed_id != task_id
                or hashlib.sha256(canonical(task)).hexdigest() != task_id
                or page.get("record_kind") != "HISTORICAL_REDOWNLOAD_NOT_OLD_BUSINESS_RECOVERY"
                or page.get("old_business_continuity") != "UNKNOWN"
                or page.get("production_admission_verified") is not False):
            raise ValueError("IMMUTABLE_MINUTE_PAGE_SCOPE_OR_TASK_INVALID")
        expected_meta = {"provider_symbol": task.get("provider_symbol"), "requested_at": page.get("requested_at"),
                         "provider_scope_sha256": page.get("provider_scope_sha256"),
                         "request_success": page.get("error") is None}
        if metadata[page_sha] != expected_meta or not isinstance(page.get("rows"), list):
            raise ValueError("MINUTE_PAGE_METADATA_BINDING_INVALID")
        rows += len(page["rows"])
        errors += int(page.get("error") is not None)
    for kind in ("quota_blocks", "access_blocks"):
        blocks = index.get(kind, [])
        if not isinstance(blocks, list):
            raise ValueError("INVALID_MINUTE_BLOCK_LIST")
        for block in blocks:
            if not isinstance(block, dict) or block.get("page_sha256") not in page_tasks:
                raise ValueError("MINUTE_BLOCK_PAGE_OUTSIDE_CLOSURE")
    return {"task_count": len(index["tasks"]), "page_count": len(page_tasks), "raw_row_count": rows,
            "error_page_count": errors, "cache_claimed_task_states": dict(sorted(states.items())),
            "coverage_claims_independently_qualified": False, "all_minutes_complete_claimed": False,
            "page_sha256s": sorted(page_tasks)}


def snapshot_ref(root, record):
    snapshot = record.get("validated_snapshot", {})
    absolute = Path(snapshot.get("path", ""))
    try:
        source = absolute.relative_to(root).as_posix()
    except ValueError:
        raise ValueError("SNAPSHOT_OUTSIDE_LOCAL_PROJECT") from None
    if not source.startswith("validated-snapshots/"):
        raise ValueError("VALIDATED_SNAPSHOT_REQUIRED")
    path = safe(root, source)
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("SNAPSHOT_COMPANIONS_FORBIDDEN")
    ref = {"source": source, "bytes": snapshot.get("bytes"), "sha256": snapshot.get("sha256")}
    payload = file_ref(root, ref, kind="validated_preserved_snapshot", archive=f"preserved-stores/{record['role']}.sqlite3")
    if payload["file_identity"] != snapshot.get("file_identity") or payload["mtime_ns"] != snapshot.get("mtime_ns"):
        raise ValueError("VALIDATED_SNAPSHOT_IDENTITY_OR_STATS_CHANGED")
    return payload


def capture(root, freeze_rel):
    if is_secret_or_dependency(freeze_rel):
        raise ValueError("SECRET_FREEZE_PATH")
    freeze_path = safe(root, freeze_rel)
    freeze_raw = bounded_bytes(freeze_path)
    freeze = json.loads(freeze_raw)
    if (not isinstance(freeze, dict) or freeze.get("schema") != FREEZE_SCHEMA
            or freeze.get("source_frozen") is not True or freeze.get("minute_series_final") is not True):
        raise ValueError("EXPLICIT_SOURCE_AND_MINUTE_FREEZE_REQUIRED")
    candidate = freeze.get("candidate_id", "")
    if not isinstance(candidate, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", candidate):
        raise ValueError("INVALID_CANDIDATE_ID")
    files, captured = [], {}
    prep_file, prep, prep_raw = read_ref_json(root, freeze.get("preparation_receipt"),
          kind="preparation_receipt", archive="evidence/local-preparation-receipt.json")
    if (prep.get("schema") != "KQUANT_LOCAL_RUNTIME_PREPARATION_V1"
            or prep.get("status") != "FOUR_PRESERVED_CANDIDATES_PREPARED_MINUTE_SCOPE_NOT_ACCEPTED"
            or prep.get("all_original_main_wal_shm_unchanged") is not True
            or prep.get("original_database_opens") != 0
            or prep.get("owner_acceptance_written") is not False
            or prep.get("production_started") is not False):
        raise ValueError("ACTUAL_UNACCEPTED_PREPARATION_RECEIPT_REQUIRED")
    files.append(prep_file)
    captured[prep_file["archive"]] = prep_raw
    stores = prep.get("databases", [])
    if len(stores) != 4 or {r.get("role") for r in stores} != ROLES:
        raise ValueError("EXACT_FOUR_PRESERVED_STORES_REQUIRED")
    store_manifest = []
    for record in sorted(stores, key=lambda r: r["role"]):
        if (record.get("recovery_state") != "COMPLETE_VERIFIED"
                or record.get("snapshot_quick_check") != ["ok"]
                or record.get("snapshot_integrity_check") != ["ok"]
                or record.get("cross_store_continuity_confirmed") is not False):
            raise ValueError("VALIDATED_PRESERVED_STORE_RECEIPT_REQUIRED")
        payload = snapshot_ref(root, record)
        files.append(payload)
        store_manifest.append({"role": record["role"], "archive": payload["archive"],
            "sha256": payload["sha256"], "schema_sha256": record["schema_sha256"],
            "tables": record["tables"], "selected_watermark_observations": record["selected_watermark_observations"],
            "continuity_scope": "selected small business baseline only", "old_business_continuity": "UNKNOWN"})
    minute = freeze.get("minute_cache", {})
    index_file, index, index_raw = read_ref_json(root, minute.get("index"),
          kind="atomic_minute_index_capture", archive="minute-cache/coverage-index.json")
    if not index_file["source"].startswith("minute-rebuild/") or PurePosixPath(index_file["source"]).name != "coverage-index.json":
        raise ValueError("MINUTE_INDEX_PATH_REQUIRED")
    final_file, final, final_raw = read_ref_json(root, minute.get("series_final_receipt"),
          kind="minute_series_final_receipt", archive="minute-cache/series-final.json")
    if (not final.get("series_stop_reason") or final.get("production_started") is not False
            or final.get("old_business_continuity") != "UNKNOWN"):
        raise ValueError("ACTUAL_STOPPED_UNACCEPTED_MINUTE_SERIES_REQUIRED")
    files.extend((index_file, final_file))
    captured.update({index_file["archive"]: index_raw, final_file["archive"]: final_raw})
    page_dir = PurePosixPath(index_file["source"]).parent / "pages"
    def read_page(page_sha):
        rel = (page_dir / (page_sha + ".json")).as_posix()
        path = safe(root, rel)
        observed = facts(path)
        if observed["sha256"] != page_sha:
            raise ValueError("IMMUTABLE_MINUTE_PAGE_CHANGED")
        files.append({"source": rel, "archive": "minute-cache/pages/" + page_sha + ".json",
                      "kind": "immutable_minute_page", **observed})
        raw = bounded_bytes(path)
        if len(raw) != observed["bytes"]:
            raise ValueError("IMMUTABLE_MINUTE_PAGE_SIZE_CHANGED")
        return raw
    minute_summary = closure(index, read_page)
    extras = freeze.get("files")
    if not isinstance(extras, list):
        raise ValueError("EXPLICIT_FILE_WHITELIST_REQUIRED")
    for ref in extras:
        explicit_source_allowed(relative(ref.get("source")))
        archive = relative(ref.get("archive"))
        if is_secret_or_dependency(archive):
            raise ValueError("SECRET_DEPENDENCY_ARCHIVE_PATH")
        files.append(file_ref(root, ref, kind="explicit_frozen_project_file", archive=archive))
    files.append({"source": relative(freeze_rel), "archive": "candidate-freeze.json", "kind": "freeze_manifest",
                  **facts(freeze_path)})
    if files[-1]["sha256"] != hashlib.sha256(freeze_raw).hexdigest():
        raise ValueError("FREEZE_CHANGED_DURING_CAPTURE")
    captured["candidate-freeze.json"] = freeze_raw
    names = [r["archive"].casefold() for r in files]
    sources = [r["source"].casefold() for r in files]
    if len(names) != len(set(names)) or len(sources) != len(set(sources)) or "archive-manifest.json" in names:
        raise ValueError("DUPLICATE_OR_RESERVED_ARCHIVE_MEMBER")
    if any(str(parent).casefold() in names for name in names for parent in PurePosixPath(name).parents
           if str(parent) != "."):
        raise ValueError("ARCHIVE_FILE_AND_DIRECTORY_COLLISION")
    total = sum(r["bytes"] for r in files)
    if len(files) > MAX_FILES or total > MAX_TOTAL:
        raise ValueError("ARCHIVE_SCOPE_SIZE_LIMIT")
    manifest = {"schema": ARCHIVE_SCHEMA, "candidate_id": candidate, "captured_at": stamp(), **SCOPE,
                "freeze_sha256": hashlib.sha256(freeze_raw).hexdigest(), "files": files,
                "payload_bytes": total, "stores": store_manifest, "minute_cache": minute_summary,
                "minute_series_stop_reason": final["series_stop_reason"],
                "external_baselines": freeze.get("external_baselines", []),
                "pinned_sdk_requirement": freeze.get("pinned_sdk_requirement"),
                "original_database_opens": 0, "source_sqlite_opens": 0}
    return manifest, captured


def q(name):
    return '"' + name.replace('"', '""') + '"'


def verify_store(path, expected):
    before = facts(path)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=2)) as db:
        db.execute("PRAGMA query_only=ON")
        quick = [r[0] for r in db.execute("PRAGMA quick_check")]
        integrity = [r[0] for r in db.execute("PRAGMA integrity_check")]
        schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        schema_sha = hashlib.sha256(json.dumps(schema, ensure_ascii=True).encode("ascii")).hexdigest()
        tables = []
        for name, sql in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            columns = [{"name": r[1], "type": r[2], "not_null": bool(r[3]), "pk_rank": r[5]}
                       for r in db.execute(f"PRAGMA table_info({q(name)})")]
            tables.append({"table": name, "rows": db.execute(f"SELECT COUNT(*) FROM {q(name)}").fetchone()[0],
                           "columns": columns, "sql": sql})
        marks = []
        for mark in expected["selected_watermark_observations"]:
            if mark.get("column") != "rowid":
                raise ValueError("EXPECTED_INTEGER_ROWID_WATERMARK_REQUIRED")
            value = db.execute(f"SELECT MAX(rowid) FROM {q(mark['table'])}").fetchone()[0]
            rows = db.execute(f"SELECT COUNT(*) FROM {q(mark['table'])}").fetchone()[0]
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError("RESTORED_WATERMARK_NOT_INTEGER")
            if value != mark["minimum"] or rows != mark["rows"]:
                raise ValueError("RESTORED_SELECTED_WATERMARK_MISMATCH")
            marks.append({"table": mark["table"], "column": "rowid", "minimum": value, "rows": rows})
        journal = db.execute("PRAGMA journal_mode").fetchone()[0]
    if (quick != ["ok"] or integrity != ["ok"] or journal.lower() != "delete"
            or schema_sha != expected["schema_sha256"] or tables != expected["tables"]):
        raise ValueError("RESTORED_SNAPSHOT_SCHEMA_ROWS_OR_INTEGRITY_MISMATCH")
    if facts(path) != before or before["sha256"] != expected["sha256"]:
        raise ValueError("RESTORED_SNAPSHOT_BYTES_CHANGED")
    return {"role": expected["role"], "quick_check": quick, "integrity_check": integrity,
            "schema_sha256": schema_sha, "table_count": len(tables), "tables": tables,
            "selected_watermarks": marks, "journal_mode": journal, "bytes_unchanged": True, **before}


def verify_restore(archive, destination, *, expected_manifest_sha256):
    # Manual extraction prevents zip traversal, overwrite, link and duplicate cases.
    safe(destination.parent, destination.name, existing=False)
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        names = [relative(i.filename) for i in infos]
        if len(names) > MAX_FILES + 1 or len({n.casefold() for n in names}) != len(names):
            raise ValueError("UNSAFE_OR_DUPLICATE_ZIP_MEMBER")
        if any(i.is_dir() or i.flag_bits & 1 or stat.S_ISLNK(i.external_attr >> 16) for i in infos):
            raise ValueError("ZIP_DIRECTORY_ENCRYPTION_OR_LINK_FORBIDDEN")
        if z.getinfo("archive-manifest.json").file_size > TEXT_LIMIT:
            raise ValueError("RESTORE_MANIFEST_TOO_LARGE")
        raw = z.read("archive-manifest.json")
        if len(raw) > TEXT_LIMIT or hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
            raise ValueError("RESTORE_MANIFEST_HASH_MISMATCH")
        manifest = json.loads(raw)
        if manifest.get("schema") != ARCHIVE_SCHEMA or any(manifest.get(k) != v for k, v in SCOPE.items()):
            raise ValueError("RESTORE_CANDIDATE_SCOPE_INVALID")
        expected = {relative(r["archive"]): r for r in manifest["files"]}
        if len(expected) != len(manifest["files"]) or set(names) != {*expected, "archive-manifest.json"}:
            raise ValueError("ZIP_MANIFEST_PAYLOAD_SET_MISMATCH")
        if sum(i.file_size for i in infos) > MAX_TOTAL:
            raise ValueError("RESTORE_SIZE_LIMIT")
        for info in infos:
            if info.filename == "archive-manifest.json":
                continue
            row = expected[info.filename]
            if (not isinstance(row.get("bytes"), int) or isinstance(row["bytes"], bool)
                    or row["bytes"] != info.file_size or row["bytes"] < 0
                    or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", "")))):
                raise ValueError("RESTORE_MEMBER_MANIFEST_SIZE_OR_HASH_INVALID")
        destination.mkdir(parents=True, exist_ok=False)
        for info in infos:
            path = safe(destination, info.filename, existing=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            result, size = hashlib.sha256(), 0
            with z.open(info) as src, path.open("xb") as dst:
                while block := src.read(1024 * 1024):
                    size += len(block)
                    if size > (TEXT_LIMIT if info.filename == "archive-manifest.json" else expected[info.filename]["bytes"]):
                        raise ValueError("RESTORE_FILE_SIZE_LIMIT")
                    result.update(block)
                    dst.write(block)
                dst.flush()
                os.fsync(dst.fileno())
            if info.filename != "archive-manifest.json":
                record = expected[info.filename]
                if size != record["bytes"] or result.hexdigest() != record["sha256"]:
                    raise ValueError("RESTORED_FILE_HASH_OR_SIZE_MISMATCH")
    stores = manifest["stores"]
    if len(stores) != 4 or {r["role"] for r in stores} != ROLES:
        raise ValueError("RESTORE_FOUR_STORE_SCOPE_REQUIRED")
    store_results = [verify_store(safe(destination, r["archive"]), r) for r in stores]
    index = json.loads(bounded_bytes(safe(destination, "minute-cache/coverage-index.json")))
    minute = closure(index, lambda h: bounded_bytes(safe(destination, "minute-cache/pages/" + h + ".json")))
    if minute != manifest["minute_cache"]:
        raise ValueError("RESTORED_MINUTE_CLOSURE_MISMATCH")
    return {"status": "ISOLATED_RESTORE_VERIFIED_CANDIDATE_ONLY", **SCOPE,
            "files_verified": len(expected), "restored_database_opens": 4,
            "stores": store_results, "minute_cache": minute, "manifest_sha256": expected_manifest_sha256}


def write_json_new(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def package(root, freeze_rel, output_rel="evidence/candidate-packaging"):
    root = Path(root).absolute()
    manifest, captured = capture(root, relative(freeze_rel))
    output = safe(root, output_rel, existing=False)
    output.mkdir(parents=True, exist_ok=True)
    required = manifest["payload_bytes"] * 2 + 1024**3
    if shutil.disk_usage(output).free < required:
        raise ValueError("INSUFFICIENT_ARCHIVE_AND_RESTORE_SPACE")
    run = output / (manifest["candidate_id"] + "-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-pid" + str(os.getpid()))
    run.mkdir(exist_ok=False)
    archive = run / (manifest["candidate_id"] + ".zip")
    receipt = {"schema": "KQUANT_CANDIDATE_ARCHIVE_RECEIPT_V1", "status": "STARTED", "started_at": stamp(),
               "pid": os.getpid(), "executable": sys.executable, "script_sha256": facts(Path(__file__))["sha256"],
               "candidate_id": manifest["candidate_id"], "archive_path": str(archive), **SCOPE,
               "original_database_opens": 0, "source_sqlite_opens": 0, "provider_requests": 0}
    write_json_new(run / "started.json", receipt)
    try:
        raw_manifest = canonical(manifest) + b"\n"
        manifest_sha = hashlib.sha256(raw_manifest).hexdigest()
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            z.writestr("archive-manifest.json", raw_manifest)
            for record in manifest["files"]:
                path = safe(root, record["source"])
                if record["archive"] in captured:
                    raw = captured[record["archive"]]
                    z.writestr(record["archive"], raw)
                else:
                    hashed, size = hashlib.sha256(), 0
                    with path.open("rb") as src, z.open(record["archive"], "w", force_zip64=True) as dst:
                        while block := src.read(1024 * 1024):
                            hashed.update(block)
                            size += len(block)
                            dst.write(block)
                    if hashed.hexdigest() != record["sha256"] or size != record["bytes"]:
                        raise ValueError("SOURCE_CHANGED_DURING_ZIP_STREAM")
        after = {record["source"]: facts(safe(root, record["source"])) for record in manifest["files"]}
        if any(after[r["source"]] != {k: r[k] for k in ("bytes", "sha256", "mtime_ns", "file_identity")} for r in manifest["files"]):
            raise ValueError("FROZEN_SOURCE_CHANGED_DURING_ARCHIVE")
        write_json_new(run / "archive-manifest.json", manifest)
        write_json_new(run / "source-inventory-after.json", after)
        restore = verify_restore(archive, run / "isolated-restore", expected_manifest_sha256=manifest_sha)
        write_json_new(run / "isolated-restore-verification.json", restore)
        receipt.update(status="ARCHIVED_AND_ISOLATED_RESTORE_VERIFIED_CANDIDATE_ONLY",
                       archive=facts(archive), manifest_sha256=manifest_sha,
                       all_frozen_sources_unchanged=True, payload_files=len(manifest["files"]),
                       isolated_restore_verified=True, restore_verification_path=str(run / "isolated-restore-verification.json"))
    except Exception as exc:
        receipt.update(status="FAILED_RETAIN_PARTIAL_ARCHIVE_FOR_REVIEW", error_type=type(exc).__name__, error=str(exc),
                       isolated_restore_verified=False)
        raise
    finally:
        receipt["finished_at"] = stamp()
        write_json_new(run / "receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", required=True, help="Explicit frozen whitelist, relative to this project root")
    parser.add_argument("--output", default="evidence/candidate-packaging", help="Fresh runs parent, relative to project root")
    args = parser.parse_args()
    receipt = package(ROOT, args.freeze, args.output)
    print(json.dumps({"status": receipt["status"], "archive_path": receipt["archive_path"],
                      "candidate_id": receipt["candidate_id"], "owner_acceptance_written": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
