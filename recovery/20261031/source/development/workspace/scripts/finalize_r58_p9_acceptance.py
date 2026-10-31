"""Join actual incident evidence into an additive, explicitly scoped verdict."""
import argparse
from collections import Counter
from datetime import UTC, datetime, date, timedelta
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).absolute().parents[1]
PACK = ROOT / "handoff/r58-p9-incident-20261006/plan"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.absolute()
    if out.drive.upper() != "C:":
        raise ValueError("C_DRIVE_EVIDENCE_ONLY")
    mixed = json.loads((out / "mixed-60min-v5-complete-window/mixed_load_report.json").read_text())
    identity = json.loads((out / "candidate_identity.json").read_text())
    if not mixed["continuous_60_minutes"] or not mixed["wall_clock_advances_through_full_entry_window"]:
        raise ValueError("COMPLETE_WINDOW_AND_REAL_HOUR_REQUIRED")
    for name, expected in mixed["executed_source_hashes"].items():
        if sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError("EXECUTED_CODE_CHANGED: " + name)

    def limit(values, threshold):
        return bool(values) and all(v["p95_seconds"] <= threshold and v["max_seconds"] <= 1
            and set(v["statuses"]) <= {"200", "503"} for v in values)

    http = mixed["http"]
    live = [v for path, v in http.items() if path.endswith("/health/live")]
    live_pass = limit(live, .25) and all(set(v["statuses"]) == {"200"} for v in live)
    cards_pass = limit([v for k, v in http.items() if "current?" in k or "compact=true" in k], 1)
    performance_pass = len(mixed["checkpoints"]) == 5 and all(
        p["completed_symbols"] == 100 and p["enqueue_to_commit_p95_seconds"] <= 2 for p in mixed["checkpoints"])
    browser = mixed.get("real_browser_report") or {}
    browser_pass = browser.get("three_real_pages") and not browser.get("problems")
    cleanup = json.loads((out / "isolated-cleanup.json").read_text()) if (out / "isolated-cleanup.json").is_file() else None
    verdicts = {
        "A01": ("PASS_AUDIT", "baseline-sha256.json", "Original process has exited; preserved runtime/log identity, no fabricated live PID."),
        "A02": ("PARTIAL_ROOT_EVIDENCE", "incident_root_cause.json", "Storage events and launcher IOException confirmed; exact failed HTTP frame/SDK timing unavailable."),
        "A03": ("PASS_ISOLATED", "pytest-frozen-v8.log", "Actual live middleware stays memory-only; protected login-file I/O is single-flight, bounded and fail-closed."),
        "A04": ("PASS_ISOLATED" if live_pass else "FAIL_THRESHOLD", "mixed-60min-v5-complete-window/mixed_load_report.json", "Both direct backend and gateway live measured; worker state is separate."),
        "A05": ("PASS_ISOLATED" if cards_pass else "FAIL_THRESHOLD", "mixed-60min-v5-complete-window/mixed_load_report.json", "503 is availability, not a qualified signal or successful business result."),
        "A06": ("PARTIAL", "pytest-gateway-v4.log", "Cancellation/single-flight file and snapshot work tested; live SDK cancellation was not executed."),
        "A07": ("PASS_ISOLATED", "mixed-60min-v5-complete-window/TEST_ONLY.json", "Zero production owners/SDK connections; isolated HTTP processes do not create a second Supervisor."),
        "A08": ("PARTIAL", "production_call_path.md", "Checkpoint reads finish before write admission; not an exhaustive audit of every existing transaction."),
        "A09": ("PASS_ISOLATED", "mixed-60min-v5-complete-window/mixed_load_report.json", "Real 4-second C-database write lock; disk-driver failure on F is not repaired by this test."),
        "A10": ("PASS_CONVERSION_BLOCKED_FACT", "actual-replay-v3-symbol-asof/actual_inputs_replay.json", "Real FCX/NVTS producer/persistence/date-bound conversion succeeds; PREPARED_WITH_GAPS remains, not fake VERIFIED."),
        "A11": ("PASS_FAIL_CLOSED", "source_gap_matrix.json", "Missing/incomplete company-action coverage remains missing, never UNCHANGED."),
        "A12": ("PASS_ISOLATED_AND_REAL_REPLAY", "actual-replay-v3-symbol-asof/actual_inputs_replay.json", "M/Q saved from legal real bars, daily direction unknown and full S0 INCOMPLETE."),
        "A13": ("PASS_ISOLATED", "pytest-frozen-v8.log", "Auxiliary 20-day history is not a price-component gate."),
        "A14": ("PARTIAL_BLOCKED_METHOD", "actual-replay-v3-symbol-asof/actual_inputs_replay.json", "Actual ASTX raw/eligible/rejected/resolver/journal/CAS replay; no adopted correction without method evidence."),
        "A15": ("BLOCKED_ENGINEERING_AND_FACTS", "OWNER_PREOPEN_CHECKLIST.md", "Production measured clock-bound/SDK attachment producer and precise method selection remain missing; no zero-error assumption."),
        "A16": ("PASS_ISOLATED", "pytest-frozen-v8.log", "Reuses original raw versions, checkpoints and deadlines; production method still pending."),
        "A17": ("PASS_ISOLATED", "pytest-frozen-v8.log", "Generation/CAS/WAIT_INPUT and new reread-versus-connection-reuse regression."),
        "A18": ("PASS_AUDIT", "reconciliation-20261005.json", "Every original symbol/right/checkpoint explicitly enumerated; missing task lease state remains NOT_CAPTURED."),
        "A19": ("PASS_AUDIT", "actual-replay-v3-symbol-asof/actual_inputs_replay.json", "REPLAY_ONLY; zero historical instant signals/production writes."),
        "A20": ("NOT_RUN_STORAGE_GATE", "source_gap_matrix.json", "No October 6 dynamic real expiry/contract query; TEST_ONLY contracts are not real acceptance."),
        "A21": ("PASS_FAIL_CLOSED_BLOCKED_FACT", "source_gap_matrix.json", "Shared depth units null; no order_num/100/lot_size/contract_size guess."),
        "A22": ("PARTIAL", "pytest-frozen-v8.log", "Three-second evidence and original deadline regressions; no new real selected BBO sample."),
        "A23": ("PASS_ISOLATED", "frontend-tests.log", "Active first checkpoint is 09:35; no fixed legacy 09:45 wait text."),
        "A24": ("PASS_ISOLATED" if browser_pass else "PARTIAL_BROWSER_FAILURE", "mixed-60min-v5-complete-window/browser-report.json", "Real isolated browser and stale/expiry tests; not an actual natural Signal delivery measurement."),
        "A25": ("BLOCKED_OWNER_AND_STORAGE", "candidate_identity.json", "Exact candidate hashes exist; production pointer unchanged and owner_accepted=false."),
        "A26": ("PASS_BOUNDARY", "candidate_identity.json", "S0 unchanged, S1 offline; LLM/Paper/order/notification goals not re-enabled."),
        "A27": ("PASS_ISOLATED_CORE_PARTIAL_PROTOCOL" if browser_pass else "PARTIAL", "mixed-60min-v5-complete-window/mixed_load_report.json", "Actual 60-minute API/storage/source/3-page run with advancing 30-minute clock, real detail and authenticated manual HTTP operations. Slow history I/O surrogate, not live SDK; lane restore, not whole-owner OS restart. Browser manual UI is not exercised by the three read-page workload."),
        "A28": ("PASS_ISOLATED" if performance_pass else "FAIL_P95", "mixed-60min-v5-complete-window/mixed_load_report.json", "Five checkpoint input-ready/enqueue to durable result, not just pure math; failed earlier samples retained."),
        "A29": ("PARTIAL_RECOVERY_SCOPE", "isolated-cleanup.json", "Listener cleanup is separately observed. Same-journal lane recovery and new generation; no full production owner crash/restart on unsafe F."),
        "A30": ("READY_CHECKLIST_NOT_MARKET_ACCEPTED", "next-complete-window-20261006.json", "All future market counts null; storage/facts/acceptance gates explicit."),
    }
    base_tests = json.loads((PACK / "acceptance_tests.json").read_text())["tests"]
    tests = [{**row, "status": verdicts[row["id"]][0], "evidence": verdicts[row["id"]][1],
        "scope_and_limit": verdicts[row["id"]][2]} for row in base_tests]
    tasks = json.loads((PACK / "tasks.json").read_text())["tasks"]
    states = ("ROOT_EVIDENCE_AND_CODE_MITIGATION", "ISOLATED_HTTP_REPAIRED", "PARTIAL_RECOVERY_STORAGE_BLOCKED",
        "REAL_CONVERSION_PARTIAL_FACT_BLOCKED", "REAL_REPLAY_METHOD_CLOCK_BLOCKED", "ORIGINAL_RECONCILIATION_COMPLETE",
        "FACT_AND_OWNER_BLOCKED", "ISOLATED_UI_VERIFIED" if browser_pass else "PARTIAL_UI",
        "ISOLATED_MIXED_COMPLETED_WITH_SCOPED_LIMITS", "CANDIDATE_NOT_DEPLOYED_OR_ACCEPTED", "FUTURE_MARKET_NOT_OBSERVED")
    result = {"recorded_at": datetime.now(UTC).isoformat(), "plan_id": "KQ-R58P9-INCIDENT-20261006",
        "mode": "DELTA_DO_NOT_RESET_OLD_TASKS", "candidate_id": identity["candidate_id"],
        "production_deployed": False, "owner_accepted": False, "all_tasks_complete": False,
        "market_or_natural_signal_accepted": False, "tests": tests,
        "tasks": [{**row, "status": state} for row, state in zip(tasks, states)],
        "mixed_live_http_thresholds_pass": live_pass, "mixed_current_compact_thresholds_pass": cards_pass,
        "mixed_five_point_end_to_end_target_pass": performance_pass, "mixed_browser_pass": bool(browser_pass),
        "cleanup": cleanup, "status_counts_not_proof_of_completion": dict(Counter(t["status"] for t in tests))}
    (out / "r58_p9_acceptance_matrix_20261006.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    from kquant.market_clock import session_bounds_utc
    from kquant.options_opening_momentum import load_policy
    opening, closing = session_bounds_utc(date(2026, 10, 6))
    window = {"session": "2026-10-06", "candidate_id": identity["candidate_id"], "policy_hash": load_policy()["policy_hash"],
        "scope_hash": identity["scope_hash"], "opening_utc": opening.isoformat(), "closing_utc": closing.isoformat(),
        "production_state": "STOPPED_STORAGE_NOT_CLEARED", "deployed": False, "owner_accepted": False,
        "registered_symbols_expected": 111, "registered_directions_per_point_expected": 222,
        "storage_gate": "BLOCKED_DISK_0_BAD_BLOCKS_AND_CONTROLLER_RESETS",
        "precise_preopen_decision_at": "2026-10-06T21:25:00+08:00",
        "observed_market_inputs": None, "natural_signals": None,
        "points": [{"checkpoint_utc": (opening + timedelta(minutes=m)).isoformat(),
            "deadline_utc": min(opening + timedelta(minutes=m, seconds=300), opening + timedelta(minutes=30)).isoformat(),
            "observed_directions": None, "states": None, "latencies": None} for m in (5, 10, 15, 20, 25)]}
    (out / "next-complete-window-20261006.json").write_text(json.dumps(window, indent=2), encoding="utf-8")
    print(json.dumps({"candidate_id": identity["candidate_id"], "http_live_pass": live_pass,
        "current_compact_pass": cards_pass, "five_point_target_pass": performance_pass, "browser_pass": bool(browser_pass),
        "production_deployed": False, "all_tasks_complete": False}))


if __name__ == "__main__":
    main()
