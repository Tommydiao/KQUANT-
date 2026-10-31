"""Full offline audit of a stopped minute cache without opening its PageStore writer.

The existing writer.lock is locked without creating or changing it. Every raw
page is hashed and revalidated; index and page inventory hashes before/after
prove that the original source content remained unchanged. Receipts are written
only outside the source cache. No SDK, credentials, network or production use.
"""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import minute_rebuild as rebuild

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "evidence/minute-audits"
PREFIX = "KQUANT_OFFLINE_AUDIT="


class ReadOnlyPageStore(rebuild.PageStore):
    """Reuse the raw validators, bypassing all creation/recovery/write methods."""
    def __init__(self, directory, raw_index):
        self.directory = Path(directory)
        self.pages = self.directory / "pages"
        self.index_path = self.directory / "coverage-index.json"
        self._page_cache, self._validation_cache = OrderedDict(), OrderedDict()
        try:
            self.index = json.loads(raw_index)
            if self.index.get("schema") != rebuild.SCHEMA or not isinstance(self.index.get("tasks"), dict):
                raise ValueError()
            referenced = []
            for task_id, entry in self.index["tasks"].items():
                if not re.fullmatch(r"[0-9a-f]{64}", task_id) or not isinstance(entry.get("pages"), list):
                    raise ValueError()
                referenced.extend(entry["pages"])
            if len(referenced) != len(set(referenced)):
                raise rebuild.CacheIntegrityError("DUPLICATE_PAGE_INDEX_REFERENCE")
            if any(not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha) for sha in referenced):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise rebuild.CacheIntegrityError("COVERAGE_INDEX_INVALID") from None
        self.referenced_pages = set(referenced)

    def commit_index(self):
        raise RuntimeError("READ_ONLY_AUDIT_WRITE_REJECTED")

    def append(self, *args, **kwargs):
        raise RuntimeError("READ_ONLY_AUDIT_WRITE_REJECTED")


@contextmanager
def existing_source_lock(directory):
    # r+b is needed by the Windows lock API, but no write or mkdir is performed.
    path = Path(directory) / "writer.lock"
    if path.resolve().parent != Path(directory).resolve() or path.is_symlink():
        raise rebuild.CacheIntegrityError("SOURCE_WRITER_LOCK_ALIAS_INVALID")
    try:
        stream = path.open("r+b")
        if path.stat().st_size < 1:
            stream.close()
            raise rebuild.CacheIntegrityError("SOURCE_WRITER_LOCK_MISSING")
    except OSError:
        raise rebuild.CacheIntegrityError("SOURCE_WRITER_LOCK_MISSING") from None
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise rebuild.CacheIntegrityError("ANOTHER_REBUILD_WRITER_ACTIVE") from None
    try:
        yield stream
    finally:
        stream.seek(0)
        if os.name == "nt":
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def locked_stream_sha(stream):
    # A Windows byte lock is tied to its file handle. Read the same handle
    # instead of opening a second handle against the locked byte.
    stream.seek(0)
    result = hashlib.sha256(stream.read()).hexdigest()
    stream.seek(0)
    return result


def inventory(directory):
    pages = Path(directory) / "pages"
    if not pages.is_dir() or pages.resolve() != Path(directory).resolve() / "pages":
        raise rebuild.CacheIntegrityError("SOURCE_PAGES_DIRECTORY_MISSING")
    values = []
    for path in sorted(pages.glob("*.json")):
        if path.is_symlink() or not path.is_file() or not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
            raise rebuild.CacheIntegrityError("SOURCE_PAGE_NAME_OR_LINK_INVALID")
        values.append({"name": path.name, "sha256": file_sha(path), "bytes": path.stat().st_size})
    return values


def bound_plan(plan, manifest, profile, calendar=None):
    tasks = plan.get("tasks", [])
    if not tasks:
        raise rebuild.CacheIntegrityError("AUDIT_PLAN_HAS_NO_VERIFIED_TASKS")
    selected = {task.get("symbol") for task in tasks} | {row.get("symbol") for row in plan.get("unresolved_symbols", [])}
    rebuilt = rebuild.build_plan(manifest, plan["planned_at"], session_count=len(plan["sessions_newest_first"]),
                                 symbols=selected, profile=profile, calendar=calendar)
    if rebuild.canonical(rebuilt) != rebuild.canonical(plan):
        raise rebuild.CacheIntegrityError("AUDIT_PLAN_MANIFEST_CALENDAR_OR_CONTRACT_CHANGED")


def compact_ranges(minutes):
    ranges = []
    for stamp in map(rebuild.aware, minutes):
        if ranges and rebuild.aware(ranges[-1]["end_exclusive_utc"]) == stamp:
            ranges[-1]["end_exclusive_utc"] = (stamp + timedelta(minutes=1)).isoformat()
            ranges[-1]["minute_count"] += 1
        else:
            ranges.append({"start_utc": stamp.isoformat(), "end_exclusive_utc": (stamp + timedelta(minutes=1)).isoformat(),
                           "minute_count": 1})
    return ranges


def compact_coverage(coverage):
    return {key: value for key, value in coverage.items() if key not in {"missing_minutes", "conflicting_minutes"}} | {
        "missing_minutes_count": len(coverage["missing_minutes"]),
        "conflicting_minutes_count": len(coverage["conflicting_minutes"]),
        "missing_minutes_sha256": rebuild.digest(coverage["missing_minutes"]),
        "conflicting_minutes_sha256": rebuild.digest(coverage["conflicting_minutes"])}


def error_code(exc):
    value = str(exc) if isinstance(exc, rebuild.CacheIntegrityError) else ""
    return value if re.fullmatch(r"[A-Z0-9_]{1,100}", value) else type(exc).__name__


def audit_snapshot(plan, source, manifest, profile, *, calendar=None):
    """Offline core. Caller must use an already stopped, dedicated minute cache."""
    started = time.monotonic()
    source = Path(source).resolve()
    report = {"record_kind": "FULL_OFFLINE_NATIVE_MINUTE_AUDIT", "status": "AUDIT_NOT_FINISHED",
              "created_at_local_wall_utc": datetime.now(rebuild.UTC).isoformat(),
              "source_cache": str(source), "plan_sha256": rebuild.digest(plan),
              "manifest_sha256": rebuild.digest(manifest), "timestamp_profile": profile,
              "requests": 0, "sdk_used": False, "env_file_read": False, "source_modified_by_auditor": False,
              "production_admission_verified": False, "old_business_continuity": "UNKNOWN",
              "clock_precision_verified": False, "page_audits": [], "task_audits": [],
              "projection_mismatches": [], "integrity_errors": [], "source_unchanged_verified": False}
    bound_plan(plan, manifest, profile, calendar)
    with existing_source_lock(source) as lock_stream:
        index_path = source / "coverage-index.json"
        if index_path.resolve().parent != source or index_path.is_symlink():
            raise rebuild.CacheIntegrityError("SOURCE_INDEX_ALIAS_INVALID")
        raw_index = index_path.read_bytes()
        report["source_index_pre_sha256"] = hashlib.sha256(raw_index).hexdigest()
        before = inventory(source)
        report["source_pages_pre_inventory_sha256"] = rebuild.digest(before)
        report["source_page_count"] = len(before)
        report["source_lock_pre_sha256"] = locked_stream_sha(lock_stream)
        try:
            store = ReadOnlyPageStore(source, raw_index)
            names = {item["name"].removesuffix(".json") for item in before}
            if store.referenced_pages - names:
                raise rebuild.CacheIntegrityError("INDEXED_PAGE_MISSING")
            report["orphan_page_sha256"] = sorted(names - store.referenced_pages)
            audited, states = set(), Counter()
            def audit_page(sha):
                if sha in audited:
                    return
                page = store.read_page(sha)
                if not isinstance(page.get("rows"), list):
                    raise rebuild.CacheIntegrityError("PAGE_NATIVE_ROWS_INVALID")
                native_error = page.get("error")
                if native_error is not None and not isinstance(native_error, dict):
                    raise rebuild.CacheIntegrityError("PAGE_PROVIDER_ERROR_INVALID")
                scope_sha = page.get("provider_scope_sha256")
                if scope_sha is not None and (not isinstance(scope_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", scope_sha)):
                    raise rebuild.CacheIntegrityError("PAGE_PROVIDER_SCOPE_HASH_INVALID")
                validation = store._validated_page(sha, page) if native_error is None else None
                projection_matches = page.get("validation") == validation
                expected_meta = {"provider_symbol": page["task"]["provider_symbol"], "requested_at": page["requested_at"],
                                 "provider_scope_sha256": scope_sha, "request_success": native_error is None}
                indexed_meta = store.index.get("page_metadata", {}).get(sha)
                metadata_matches = indexed_meta == expected_meta
                if sha in store.referenced_pages and not metadata_matches:
                    report["projection_mismatches"].append({"kind": "INDEX_PAGE_PROVIDER_METADATA", "page_sha256": sha})
                row = {"page_sha256": sha, "task_id": page["task"]["task_id"],
                       "symbol": page["task"]["symbol"], "provider_symbol": page["task"]["provider_symbol"],
                       "session": page["task"]["session"], "provider_rows": len(page["rows"]),
                       "stored_validation_matches_recomputed": projection_matches,
                       "indexed_provider_metadata_matches_original_page": metadata_matches if sha in store.referenced_pages else None,
                       "error_category": native_error.get("error_category") if native_error else None}
                if validation:
                    row.update(state=validation["state"], accepted_unique_minutes=validation["accepted_unique_minutes"],
                               rejection_counts=validation["rejection_counts"],
                               missing_minutes_count=len(validation["missing_minutes"]),
                               capped_at_provider_limit=validation["page_at_provider_limit"])
                if not projection_matches:
                    report["projection_mismatches"].append({"kind": "PAGE_STORED_VALIDATION", "page_sha256": sha})
                report["page_audits"].append(row)
                audited.add(sha)
            for task in plan["tasks"]:
                coverage = store.coverage(task)
                states[coverage["state"]] += 1
                entry = store.index["tasks"].get(task["task_id"], {})
                for sha in entry.get("pages", []):
                    audit_page(sha)
                compact = compact_coverage(coverage)
                stored = entry.get("coverage")
                if stored is not None:
                    expected = dict(compact)
                    if entry.get("quota_deferred") and not coverage["historical_market_complete"]:
                        expected["state"] = "QUOTA_DEFERRED"
                    differences = [key for key, value in expected.items() if stored.get(key) != value]
                    if differences:
                        report["projection_mismatches"].append({"kind": "INDEX_COVERAGE", "task_id": task["task_id"],
                                                                "fields": differences})
                elif entry.get("pages"):
                    report["projection_mismatches"].append({"kind": "INDEX_COVERAGE_MISSING", "task_id": task["task_id"]})
                report["task_audits"].append({"task_id": task["task_id"], "symbol": task["symbol"],
                    "provider_symbol": task["provider_symbol"], "session": task["session"], **compact,
                    "missing_ranges": compact_ranges(coverage["missing_minutes"]),
                    "conflicting_minutes": coverage["conflicting_minutes"], "page_sha256": entry.get("pages", [])})
            # Every committed raw page is examined, including orphan pages and
            # pages outside the selected plan. No orphan recovery is persisted.
            for sha in sorted(names - audited):
                audit_page(sha)
            metadata_outside_source = set(store.index.get("page_metadata", {})) - names
            if metadata_outside_source:
                report["projection_mismatches"].append({"kind": "INDEX_PAGE_METADATA_POINTS_OUTSIDE_SOURCE",
                                                        "page_sha256": sorted(metadata_outside_source)})
            for block in store.index.get("quota_blocks", []):
                page = store.read_page(block["page_sha256"])
                requested = rebuild.aware(page["requested_at"])
                months = [requested.strftime("%Y-%m"),
                          requested.astimezone(rebuild.ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")]
                if (block.get("provider_scope_sha256") != page.get("provider_scope_sha256")
                        or block.get("months") != months or not page.get("error")
                        or page["error"].get("error_category") != "HISTORY_MONTHLY_SYMBOL_QUOTA"):
                    report["projection_mismatches"].append({"kind": "INDEX_MONTHLY_QUOTA_PROOF", "page_sha256": block["page_sha256"]})
            for block in store.index.get("access_blocks", []):
                page = store.read_page(block["page_sha256"])
                if (block.get("provider_scope_sha256") != page.get("provider_scope_sha256")
                        or block.get("provider_symbol") != page["task"]["provider_symbol"]
                        or block.get("month_utc") != rebuild.aware(page["requested_at"]).strftime("%Y-%m")
                        or not page.get("error") or page["error"].get("error_category") != "NO_QUOTE_ACCESS"):
                    report["projection_mismatches"].append({"kind": "INDEX_SYMBOL_ACCESS_PROOF", "page_sha256": block["page_sha256"]})
            report["all_source_pages_revalidated"] = audited == names
            plan_task_ids = {t["task_id"] for t in plan["tasks"]}
            report["source_pages_outside_plan"] = [row["page_sha256"] for row in report["page_audits"]
                                                    if row["task_id"] not in plan_task_ids]
            report["coverage"] = {"coverage_basis": "IMMUTABLE_PAGES_REVALIDATED", "task_count": len(plan["tasks"]),
                "eligible_symbols": plan["eligible_symbols"], "unresolved_symbols": plan["unresolved_symbols"],
                "sessions_newest_first": [s["session"] for s in plan["sessions_newest_first"]],
                "task_states": dict(states), "theoretical_slots": plan["theoretical_slots"],
                "accepted_unique_minutes": sum(row["accepted_unique_minutes"] for row in report["task_audits"]),
                "missing_minutes": sum(row["missing_minutes_count"] for row in report["task_audits"]),
                "production_admission_verified": False}
            report["status"] = ("AUDIT_PROJECTION_MISMATCH" if report["projection_mismatches"]
                else "AUDIT_INDEX_RECOVERY_REQUIRED" if report["orphan_page_sha256"]
                else "AUDIT_VERIFIED_COMPLETE" if states == {"COMPLETE": len(plan["tasks"])}
                else "AUDIT_VERIFIED_WITH_GAPS")
        except Exception as exc:
            report["status"] = "AUDIT_BLOCKED_INTEGRITY"
            report["integrity_errors"].append(error_code(exc))
        finally:
            report["source_index_post_sha256"] = file_sha(index_path)
            after = inventory(source)
            report["source_pages_post_inventory_sha256"] = rebuild.digest(after)
            report["source_lock_post_sha256"] = locked_stream_sha(lock_stream)
            report["source_unchanged_verified"] = (report["source_index_pre_sha256"] == report["source_index_post_sha256"]
                and before == after and report["source_lock_pre_sha256"] == report["source_lock_post_sha256"])
            if not report["source_unchanged_verified"]:
                report["status"] = "AUDIT_SOURCE_CHANGED"
    report["elapsed_monotonic_seconds"] = round(time.monotonic() - started, 3)
    return report


def save_receipt(report, out=OUT):
    out = Path(out).resolve()
    if out.is_relative_to(Path(report.get("source_cache", ROOT / "minute-rebuild")).resolve()):
        raise ValueError("AUDIT_RECEIPT_MUST_BE_OUTSIDE_SOURCE_CACHE")
    out.mkdir(parents=True, exist_ok=True)
    raw = rebuild.canonical(report)
    sha = hashlib.sha256(raw).hexdigest()
    path = out / (datetime.now(rebuild.UTC).strftime("%Y%m%dT%H%M%S%fZ-") + sha + ".json")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"status": report["status"], "requests": 0, "receipt_path": str(path), "receipt_sha256": sha,
            "source_unchanged_verified": report.get("source_unchanged_verified", False),
            "elapsed_monotonic_seconds": report.get("elapsed_monotonic_seconds"),
            "coverage": report.get("coverage"), "production_admission_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("audit-snapshot",))
    parser.add_argument("--cache-name", default="native-20261007-v1")
    parser.add_argument("--plan", type=Path, required=True, help="Exact existing immutable plan JSON")
    parser.add_argument("--manifest", type=Path, default=rebuild.DEFAULT_MANIFEST)
    parser.add_argument("--timestamp-contract", choices=("aware-only", "verified-naive-asia-shanghai"), default="aware-only")
    parser.add_argument("--timestamp-evidence", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.cache_name):
        parser.error("Invalid cache name")
    if not 30 <= args.timeout_seconds <= 3600:
        parser.error("Audit timeout must be 30..3600 seconds")
    cache_base = ROOT.resolve() / "minute-rebuild"
    source = (ROOT / "minute-rebuild" / args.cache_name).resolve()
    if (ROOT / "minute-rebuild").resolve() != cache_base or not source.is_relative_to(cache_base):
        parser.error("Source alias must remain in the isolated minute cache")
    if OUT.resolve() != ROOT.resolve() / "evidence/minute-audits":
        parser.error("Audit evidence alias must remain in the isolated evidence directory")
    for path in (args.plan, args.manifest, args.timestamp_evidence):
        if path and path.name.startswith(".env"):
            parser.error("Invalid evidence path")
    if args.worker:
        try:
            plan_raw = args.plan.read_bytes()
            plan = json.loads(plan_raw)
            if args.plan.name != hashlib.sha256(plan_raw).hexdigest() + ".json":
                raise rebuild.CacheIntegrityError("IMMUTABLE_PLAN_HASH_NAME_INVALID")
            manifest = json.loads(args.manifest.read_bytes())
            profile = rebuild.timestamp_profile(args.timestamp_contract, args.timestamp_evidence)
            report = audit_snapshot(plan, source, manifest, profile)
        except Exception as exc:
            report = {"record_kind": "FULL_OFFLINE_NATIVE_MINUTE_AUDIT", "status": "AUDIT_BLOCKED",
                      "reason": error_code(exc), "source_cache": str(source), "requests": 0,
                      "source_modified_by_auditor": False, "production_admission_verified": False}
        print(PREFIX + json.dumps(save_receipt(report), ensure_ascii=False))
        return
    arguments = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"]
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=args.timeout_seconds)
        payloads = [line[len(PREFIX):] for line in result.stdout.splitlines() if line.startswith(PREFIX)]
        summary = json.loads(payloads[-1]) if payloads else save_receipt({"status": "AUDIT_CHILD_FAILED",
                      "source_cache": str(source), "returncode": result.returncode, "requests": 0,
                      "production_admission_verified": False})
    except subprocess.TimeoutExpired:
        summary = save_receipt({"status": "AUDIT_PARENT_TIMEOUT", "source_cache": str(source), "requests": 0,
                               "child_terminated": True, "timeout_seconds": args.timeout_seconds,
                               "source_modified_by_auditor": False, "production_admission_verified": False})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
