"""Build an explicit, hashed archive whitelist only after both caller freezes.

The workspace candidate list comes from rg, excludes active stores/environments/
Git/dependency/cache paths, and is then checked by the archive's strict whitelist.
No credential content, SQLite connection, provider call or service start occurs.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

import prepare_candidate_archive as archive

ROOT = Path(__file__).resolve().parent
WORKSPACE_PREFIX = "development/workspace/"
PREPARATION = "evidence/local-runtime-preparation-20261007T071740946787Z-pid11156/receipt.json"
BASELINES = {
    "KQUANT_Environment_20261007.zip": {
        "bytes": 11723828, "sha256": "3903ed1d41a2bccce5f72f2d103b3c91ecfb6c1cffc5dcf85d6ea928232a38a5",
        "purpose": "Pinned Python SDK wheel and observed environment metadata"},
    "KQUANT_Development_20261007.zip": {
        "bytes": 308171015, "sha256": "8842306e3b00d4ad0012b77af53a7aebb689f73c908bf40b1477f872a3205217",
        "purpose": "Original migration source and handoff evidence baseline"},
    "KQUANT_Recovered_Data_20261007.zip": {
        "bytes": 308700387, "sha256": "d078e555e65ef2a42df31a924ddded019100b6d7f94f424d0c30f17a6fd1d514",
        "purpose": "Preserve the transferred original DB/WAL/SHM byte set without SQLite opening"},
}
SDK = {"package": "longbridge", "version": "4.4.1", "python_abi": "cp312-cp312-win_amd64",
       "wheel": "longbridge-4.4.1-cp312-cp312-win_amd64.whl",
       "wheel_sha256": "ddde921d9c6a7b90567218bd666fccb59530904fd2381559e6be8440fdf384de",
       "external_baseline": "KQUANT_Environment_20261007.zip",
       "archive_member": "wheels/longbridge-4.4.1-cp312-cp312-win_amd64.whl",
       "wheel_in_candidate_archive": False, "silent_version_substitution_allowed": False}
PRUNED_GLOBS = ["!work/**", "!.venv/**", "!venv/**", "!**/node_modules/**", "!.git/**",
                "!**/__pycache__/**", "!**/.pytest_cache/**", "!**/.mypy_cache/**",
                "!**/.ruff_cache/**", "!**/.cache/**", "!**/cache/**", "!**/caches/**"]
DEFAULT_EXTRAS = ["prepare_candidate_archive.py", "build_candidate_archive_freeze.py",
                  "test_candidate_archive.py", "evidence/candidate-packaging-contract.md",
                  "evidence/CANDIDATE_RESTORE_INSTRUCTIONS.md"]


def reference(root, source, target=None):
    source = archive.relative(source)
    if archive.is_secret_or_dependency(source):
        raise ValueError("SECRET_OR_DEPENDENCY_REJECTED_BEFORE_REFERENCE_READ")
    value = {"source": source, **archive.facts(archive.safe(root, source))}
    archive.verify_pinned_source(source, value["sha256"])
    if target:
        value["archive"] = archive.relative(target)
    return value


def workspace_listing(root):
    workspace = archive.safe(root, WORKSPACE_PREFIX.rstrip("/") + "/pyproject.toml").parent
    args = ["rg", "--files", "--hidden", "--no-ignore"]
    for pattern in PRUNED_GLOBS:
        args.extend(("--glob", pattern))
    result = subprocess.run(args, cwd=workspace, capture_output=True, encoding="utf-8", check=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=60)
    return [WORKSPACE_PREFIX + line.replace("\\", "/") for line in result.stdout.splitlines() if line]


def verify_regression(root, source):
    ref = reference(root, source)
    _, receipt, _ = archive.read_ref_json(root, ref, kind="final_backend_regression", archive="unused.json")
    if (receipt.get("schema") != "KQUANT_BACKEND_CANDIDATE_REGRESSION_V1"
            or receipt.get("status") != "PASSED_TEST_SCOPE_AND_UNCHANGED_CANDIDATES"
            or receipt.get("source_hashes_unchanged") is not True
            or receipt.get("candidate_database_hashes_unchanged") is not True
            or receipt.get("production_started") is not False
            or receipt.get("owner_acceptance_written") is not False
            or receipt.get("provider_requests") != 0):
        raise ValueError("PASSED_FINAL_UNCHANGED_BACKEND_REGRESSION_REQUIRED")
    inventory = receipt.get("source_inventory_after")
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("REGRESSION_SOURCE_INVENTORY_REQUIRED")
    for local, expected in inventory.items():
        actual = reference(root, WORKSPACE_PREFIX + local.replace("\\", "/"))
        if any(actual[key] != expected[key] for key in ("bytes", "sha256")):
            raise ValueError("SOURCE_CHANGED_AFTER_FINAL_BACKEND_REGRESSION")
    expected_databases = {
        "work/kquant_us.sqlite3", "work/options_full_watch/full_watch.sqlite3",
        "work/options_one_minute/opening_trend_research.sqlite3",
        "work/options_signal_copilot/signal_copilot.sqlite3"}
    databases = receipt.get("candidate_databases_after", {})
    if {p.replace("\\", "/") for p in databases} != expected_databases:
        raise ValueError("REGRESSION_FOUR_CANDIDATE_HASHES_REQUIRED")
    for local, expected in databases.items():
        actual = reference(root, WORKSPACE_PREFIX + local.replace("\\", "/"))
        if any(actual[key] != expected[key] for key in ("bytes", "sha256")):
            raise ValueError("CANDIDATE_BYTES_CHANGED_AFTER_FINAL_REGRESSION")
    return ref


def baseline_references(root):
    rows = []
    for name, expected in BASELINES.items():
        actual = archive.facts(archive.safe(root, "archives/" + name))
        if any(actual[key] != expected[key] for key in ("bytes", "sha256")):
            raise ValueError("ORIGINAL_CLOUD_BASELINE_BYTE_HASH_MISMATCH")
        rows.append({"file": name, **expected, "local_bytes_reverified": True,
                     "included_in_candidate_archive": False,
                     "cloud_download_must_match_exact_sha256": True})
    return rows


def build(root, *, candidate_id, minute_final, regression_receipt, destination,
          source_frozen=False, minute_series_final=False,
          preparation_receipt=PREPARATION,
          minute_index="minute-rebuild/native-20261007-v1/coverage-index.json", extras=()):
    # Freeze flags are factual caller statements, never inferred from elapsed time.
    if source_frozen is not True or minute_series_final is not True:
        raise ValueError("EXPLICIT_FINAL_SOURCE_AND_MINUTE_FREEZE_REQUIRED")
    root = Path(root).absolute()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", candidate_id):
        raise ValueError("INVALID_CANDIDATE_ID")
    destination = archive.relative(destination)
    if archive.is_secret_or_dependency(destination) or not destination.startswith("evidence/"):
        raise ValueError("NEW_EVIDENCE_FREEZE_DESTINATION_REQUIRED")
    output = archive.safe(root, destination, existing=False)
    inventory_path = output.with_name(output.stem + "-inventory.json")
    if output.exists() or inventory_path.exists():
        raise ValueError("EXISTING_FREEZE_OR_INVENTORY_NO_OVERWRITE")
    regression = verify_regression(root, regression_receipt)
    final_ref = reference(root, minute_final)
    _, final, _ = archive.read_ref_json(root, final_ref, kind="minute_series_final_receipt", archive="unused.json")
    if not final.get("series_stop_reason") or final.get("production_started") is not False or final.get("old_business_continuity") != "UNKNOWN":
        raise ValueError("ACTUAL_FINAL_STOPPED_UNACCEPTED_MINUTE_SERIES_REQUIRED")
    listed = workspace_listing(root)
    included, excluded = [], []
    for source in sorted(set(listed)):
        try:
            archive.explicit_source_allowed(archive.relative(source))
        except ValueError as exc:
            excluded.append({"source": source, "reason": str(exc)})
            continue
        included.append(reference(root, source, "source/" + source))
    additional = [*DEFAULT_EXTRAS, regression_receipt, *extras]
    seen = {r["source"].casefold() for r in included}
    for source in additional:
        source = archive.relative(source)
        archive.explicit_source_allowed(source)
        if source.casefold() not in seen:
            included.append(reference(root, source, "source/" + source))
            seen.add(source.casefold())
    if not included:
        raise ValueError("EMPTY_PROJECT_SOURCE_WHITELIST")
    baselines = baseline_references(root)
    freeze = {"schema": archive.FREEZE_SCHEMA, "candidate_id": candidate_id, "created_at": archive.stamp(),
              "source_frozen": True, "minute_series_final": True, **archive.SCOPE,
              "preparation_receipt": reference(root, preparation_receipt),
              "minute_cache": {"index": reference(root, minute_index), "series_final_receipt": final_ref},
              "files": sorted(included, key=lambda r: r["archive"]), "external_baselines": baselines,
              "pinned_sdk_requirement": SDK, "final_backend_regression": regression,
              "whitelist_method": "rg --files workspace, explicit exclusions, source allowlist, exact per-file SHA"}
    # Recheck the exact final regression after source hashing before publishing.
    verify_regression(root, regression_receipt)
    for row in freeze["files"]:
        latest = reference(root, row["source"])
        if any(latest[key] != row[key] for key in ("bytes", "sha256", "mtime_ns", "file_identity")):
            raise ValueError("SOURCE_CHANGED_DURING_FREEZE_BUILD")
    report = {"schema": "KQUANT_ARCHIVE_WHITELIST_INVENTORY_V1", "observed_at": archive.stamp(), **archive.SCOPE,
              "rg_workspace_candidates": len(listed), "included_files": len(freeze["files"]) + 1,
              "excluded_candidates": excluded, "pruned_globs": PRUNED_GLOBS,
              "environment_wheels_duplicated": False, "provider_requests": 0, "sqlite_connections": 0,
              "destination": destination, "external_baselines": baselines, "pinned_sdk_requirement": SDK}
    output.parent.mkdir(parents=True, exist_ok=True)
    archive.write_json_new(inventory_path, report)
    inventory_source = inventory_path.relative_to(root).as_posix()
    freeze["files"].append(reference(root, inventory_source, "source/" + inventory_source))
    freeze["files"].sort(key=lambda row: row["archive"])
    archive.write_json_new(output, freeze)
    return {"freeze_path": str(output), "inventory_path": str(inventory_path), "files": len(freeze["files"]),
            "freeze_sha256": archive.facts(output)["sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--minute-final", required=True, help="Actual stopped series final.json relative to project")
    parser.add_argument("--regression-receipt", required=True, help="Latest stable passed 13-module receipt")
    parser.add_argument("--destination", required=True, help="New evidence freeze.json relative to project")
    parser.add_argument("--source-frozen", action="store_true")
    parser.add_argument("--minute-series-final", action="store_true")
    parser.add_argument("--preparation-receipt", default=PREPARATION)
    parser.add_argument("--minute-index", default="minute-rebuild/native-20261007-v1/coverage-index.json")
    parser.add_argument("--include", action="append", default=[], help="Additional exact source/evidence path, repeatable")
    args = parser.parse_args()
    result = build(ROOT, candidate_id=args.candidate_id, minute_final=args.minute_final,
                   regression_receipt=args.regression_receipt, destination=args.destination,
                   source_frozen=args.source_frozen, minute_series_final=args.minute_series_final,
                   preparation_receipt=args.preparation_receipt, minute_index=args.minute_index, extras=args.include)
    import json
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
