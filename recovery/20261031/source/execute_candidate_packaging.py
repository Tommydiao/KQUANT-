"""Parent-approved core archive inputs; no hour logs, status, plan or active DBs."""
from pathlib import Path
import json

import build_candidate_archive_freeze as builder
import prepare_candidate_archive as archive

ROOT = Path(__file__).resolve().parent
CANDIDATE = "r58-p10-resume-20261007-7ff4101a4962ecc1"
PREP = "evidence/local-runtime-preparation-20261007T071740946787Z-pid11156"
BACKEND = "evidence/backend-candidate-regression-20261007T075209411147Z-pid9332"
SERIES = "evidence/minute-series-20261007T080810291317Z/final.json"
AUDIT = "evidence/minute-audits/20261007T081016463042Z-2bf68ba161b03909b830e0417d5aea1e0557e8e72c81ce9bc5c545437f81d627.json"
GAPS = "evidence/minute-audits/20261007T081334423205Z-gap-review-2295a41c6aa03861dc142aabbbf337f45917b724f3b659dba8e754871d12c6fc.json"
QUOTE = "evidence/market-readiness/20261007T080541100598Z-73464aaad1bbf1f4a0cf0defc4cf0071e706500a919d439e157a681df5d4658b.json"
FREEZE = "evidence/candidate-freeze-" + CANDIDATE + ".json"
EXTRAS = [
    "execute_candidate_packaging.py", "audit_migration.py", "audit_local_bindings.py", "prepare_local_runtime.py",
    "inventory_minutes.py", "minute_rebuild.py", "run_minute_backfill.py", "run_minute_backfill_series.py",
    "probe_minute_history.py", "probe_market_readiness.py", "verify_sdk_timestamp.py", "diagnose_clock_read_only.py",
    "test_minute_rebuild.py", "test_probe_minute_history.py", "test_probe_market_readiness.py",
    "migration-verification.json", "evidence/run_backend_candidate_regression.py",
    BACKEND + "/results.xml", BACKEND + "/pytest-output.log",
    "evidence/candidate-archive-fixtures-20261007-p4-v5-results.xml",
    "evidence/frontend-resume-policy-build.json", "evidence/frontend-resume-policy-vitest.json",
    "evidence/frontend-resume-policy-vitest.log", "evidence/frontend-resume-policy-types.log",
    "evidence/frontend-resume-policy-build-stock.log", "evidence/frontend-resume-policy-build-unified.log",
    "evidence/frontend-resume-cloud-original-restoration.json", "evidence/frontend-resume-cloud-original-restoration.md",
    "evidence/frontend-resume-config-search.json", "evidence/frontend-resume-cloud-policy-tests.xml",
    "development/handoff/evidence/p9-base-manifest.json",
    "evidence/local-binding-audit.json", "evidence/local-binding-audit.md",
    "evidence/sdk-timestamp-contract-20261007T071652086437Z.json", "evidence/sdk-wheel-verification.json",
    "evidence/workspace-environment-current.lock.txt", "evidence/new-machine-environment.lock.txt",
    "evidence/CLOCK_READ_ONLY_DIAGNOSIS_20261007.md",
    "evidence/clock-diagnosis-review-20261007-5a31cbc27cb00d748a5b8dfefc15ae1a68804268d203c15fe012df5802293198.json",
    "evidence/clock-diagnosis-20261007T074354219995Z-9115efc754f8b930b0b56e63f32e6b94d2ef391cee7bbcaf2b3600a7081785a8.json",
    "evidence/clock-diagnosis-20261007T074428143168Z-6e7442708d02551e35e4b6e7a744510f49591c4243230bc636c340d5130061ea.json",
    "evidence/clock-diagnosis-20261007T074502363829Z-636cb1e5e8e3ed859d44517a26bd3ef5fcc7efa5967345f057824fe3db9a3ab4.json",
    "evidence/retained-watchlist.json", "evidence/minute-recovery-inventory.json",
    "evidence/database-audit.json", AUDIT, GAPS, QUOTE,
    "development/handoff/tools/new_data_epoch.py", "development/handoff/tools/cloud_archive_inventory.py",
    "development/handoff/tools/cloud_archive_restore.py", "development/handoff/tools/cloud_archive_package.py",
    PREP + "/original-byte-inventory-before.json", PREP + "/original-byte-inventory-after.json",
    PREP + "/minute-schema.sql", PREP + "/new-minute-epoch-declaration-proposed.json", PREP + "/README.md",
    *[PREP + "/" + role + "-recovery.json" for role in sorted(archive.ROLES)],
    *[PREP + "/" + role + "-candidate.json" for role in sorted(archive.ROLES)],
]


def main():
    print(json.dumps({"kind": "P4_EXPLICIT_FREEZE_BUILD_STARTED", "candidate_id": CANDIDATE,
                      "immutable_final_inputs": [SERIES, AUDIT, GAPS, QUOTE],
                      "active_hour_files_included": False}, ensure_ascii=False), flush=True)
    frozen = builder.build(ROOT, candidate_id=CANDIDATE, minute_final=SERIES,
                           regression_receipt=BACKEND + "/receipt.json", destination=FREEZE,
                           source_frozen=True, minute_series_final=True, extras=EXTRAS)
    print(json.dumps({"kind": "P4_EXPLICIT_FREEZE_BUILT", **frozen}, ensure_ascii=False), flush=True)
    receipt = archive.package(ROOT, FREEZE)
    print(json.dumps({"kind": "P4_CANDIDATE_CORE_ARCHIVE_VERIFIED", "status": receipt["status"],
                      "candidate_id": CANDIDATE, "archive_path": receipt["archive_path"],
                      "archive": receipt["archive"], "manifest_sha256": receipt["manifest_sha256"],
                      "restore_verification_path": receipt["restore_verification_path"],
                      "owner_acceptance_written": False, "can_launch": False}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
