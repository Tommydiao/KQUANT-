"""Close the bounded C workstream using existing test outputs, without services."""
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
WEEKEND = HERE.parent
DELIVERY = WEEKEND.parent
LIFECYCLE = DELIVERY / "opening-first-hour/lifecycle-candidate"


def main():
    evidence_paths = [HERE / "lifecycle-windows51-03/result.json", HERE / "lifecycle-core76-01/result.json",
                      HERE / "calendar-verification.json", HERE / "calendar-tests.xml"]
    lifecycle_results = [json.loads(path.read_text(encoding="utf-8")) for path in evidence_paths[:2]]
    suites = list(ET.parse(evidence_paths[3]).getroot().iter("testsuite"))
    calendar_total = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    calendar_failures = sum(int(suite.attrib.get(key, 0)) for suite in suites for key in ("errors", "failures", "skipped"))
    paths = [LIFECYCLE / name for name in (
        "start_kquant_workspace.ps1", "scripts/FoundationLifecycle.ps1", "acceptance-child.ps1",
        "acceptance-health.py", "test-process-isolation.ps1")]
    paths += [WEEKEND / "calendar" / name for name in (
        "window_calendar.py", "test_window_calendar.py", "capture_calendar.py")]
    evidence = {str(path.relative_to(WEEKEND)): sha256(path.read_bytes()).hexdigest() for path in evidence_paths}
    result = {
        "schema": "WEEKEND_WORKSTREAM_C_CLOSEOUT_V1", "recorded_at": datetime.now(UTC).isoformat(),
        "ready_for_parent_integration": calendar_total > 0 and calendar_failures == 0 and all(row["pass"] and row["remaining_test_children"] == 0 for row in lifecycle_results),
        "production_runtime_changed": False, "production_database_access": False,
        "matching_hour_started": False, "production_restart": False,
        "prior_seven_day_verdict": "FAIL_UNCHANGED",
        "source_hashes": {str(path.relative_to(DELIVERY)): sha256(path.read_bytes()).hexdigest() for path in paths},
        "evidence_hashes": evidence,
        "lifecycle": [{"host": row["host"], "version": row["ps_version"], "pass": row["pass"],
                       "checks": len(row["checks"]), "remaining_children": row["remaining_test_children"],
                       "scope": row["scope"]} for row in lifecycle_results],
        "calendar": {"tests_passed": calendar_total - calendar_failures, "tests_total": calendar_total,
                     "failures_errors_skips": calendar_failures, "exchange": "XNYS", "timezone": "America/New_York",
                     "window_day": "2026-11-02", "registered": 111, "applicable": 100, "unresolved": 11,
                     "checkpoints": 11, "positions_per_variant": 2200, "actually_registered": False},
        "exact_gaps": [
            "Not a successful full original launcher five-role recovery/approval gate run: that requires parent integration and exact acceptance.",
            "No actual Worker/Supervisor business topology, compiled page, SSE or matching 3600-second run was started in C scope.",
            "Access-denied and missing-identity fields are explicit narrow injections; real CIM failure is invalid-namespace, not reproduction of the unknown October 23 cancellation cause.",
            "Calendar task keys/reconciliation helpers are read-only verification adapters, not installed automation or newly persisted market tasks.",
            "Budget repeated-hour test proves timezone bucket behavior, not the AI ledger: workstream A must retain its own atomic reservation tests.",
            "Existing fixed BJT manual exit is verified; S1 manual-policy acceptance is not granted by timing tests."
        ],
        "parent_actions": [
            "Bind only lifecycle-candidate/start_kquant_workspace.ps1 and scripts/FoundationLifecycle.ps1 in the final release projection. Keep acceptance fixtures out of production runtime dependencies.",
            "No first_hour.py change is needed for DST: installed schedule/session_bounds_utc already uses XNYS/America_New_York correctly. Use window_calendar.window/expected_positions/reconcile only for readiness/audit if desired.",
            "Run the integrated affected short penetration, then freeze and run the matching hour; C files are ready and will not be edited further without coordination.",
            "Collect recovery, expired-method/AI budget and exact release choices once before production restoration."
        ]}
    (HERE / "C_CLOSEOUT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
