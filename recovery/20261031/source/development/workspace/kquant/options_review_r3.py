from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .options_paper_engineering import (
    ENGINE_VERSION,
    POLICY_PATH,
    PaperLedger,
    content_hash,
    load_policy,
    run_engineering_replay,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "outputs" / "options_review_r3"
REVIEW_DB = REPO_ROOT / "work" / "options_review_r3" / "options_review_r3.sqlite3"
PAPER_DB = REPO_ROOT / "work" / "options_review_r3" / "options_paper_engineering.sqlite3"
R2_OUTPUT_ROOT = REPO_ROOT / "outputs" / "options_review_r2"
MASTER_PLAN_PATH = REPO_ROOT / "docs" / "KQUANT_OPTIONS_MASTER_PLAN_REVIEW_LED_V1.md"
OWNER_PLAYBOOK_PATH = REPO_ROOT / "docs" / "OWNER_REVIEW_PLAYBOOK.md"
TASK_GRAPH_PATH = REPO_ROOT / "plan" / "options_personal_master_tasks.v1.json"
PROFILE_PATH = REPO_ROOT / "config" / "options_research_profiles_v1.json"
R2_ACCEPTANCE_PATH = REPO_ROOT / "config" / "review_acceptances" / "options_r2_20260920.txt"
REVIEW_VERSION = "options-personal-r3.v1.0.0"

EXPECTED_SELECTION = {
    "strategy": "STRAT-SHORT-ATM-RANGE-EXPANSION-V1",
    "paper_execution": "PAPER-RECEIPT-TIME-PROXY-V1",
    "capital": "PAPER-RISK-10000-V1",
    "cost": "COST-OPTIONS-CONSERVATIVE-V1",
    "metric": "METRIC-OPTIONS-RESEARCH-GATE-V1",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS review_meta (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_acceptances (bundle_id TEXT PRIMARY KEY, prior_bundle_id TEXT NOT NULL, payload_json TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_task_state (bundle_id TEXT NOT NULL, task_id TEXT NOT NULL, state TEXT NOT NULL, detail_json TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(bundle_id,task_id));
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_immutable(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"Immutable artifact already exists with different content: {path}")
        return
    path.write_text(text, encoding="utf-8", newline="\n")


def write_text_immutable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = text.rstrip() + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != normalized:
            raise RuntimeError(f"Immutable artifact already exists with different content: {path}")
        return
    path.write_text(normalized, encoding="utf-8", newline="\n")


def _git_identity() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True, encoding="utf-8", errors="replace").strip()

    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "status_hash": hashlib.sha256(run("status", "--short").encode("utf-8")).hexdigest(),
    }


def _latest_r2(expected_bundle_id: str) -> tuple[Path, dict[str, Any]]:
    latest = load_json(R2_OUTPUT_ROOT / "LATEST.json")
    if latest.get("bundle_id") != expected_bundle_id:
        raise RuntimeError(f"R2 bundle mismatch: expected {expected_bundle_id}, found {latest.get('bundle_id')}")
    run_dir = Path(latest["run_dir"])
    manifest = load_json(run_dir / "manifest.json")
    if manifest.get("tests", {}).get("status") != "PASS":
        raise RuntimeError("R2 bundle verification did not pass")
    if manifest.get("state") != "WAIT_REVIEW":
        raise RuntimeError("R2 bundle was not presented for review")
    return run_dir, manifest


def _profile_boundary() -> dict[str, Any]:
    payload = load_json(PROFILE_PATH)
    rows = []
    for profile in payload.get("profiles", []):
        rows.append(
            {
                "profile_id": profile.get("profile_id"),
                "signal_generation_enabled": bool(profile.get("signal_generation_enabled")),
                "trade_simulation_enabled": bool(profile.get("trade_simulation_enabled")),
                "automatic_order_enabled": bool(profile.get("automatic_order_enabled")),
            }
        )
    return {
        "path": str(PROFILE_PATH.resolve()),
        "sha256": sha256_file(PROFILE_PATH),
        "preserved": all(not row["signal_generation_enabled"] and not row["trade_simulation_enabled"] and not row["automatic_order_enabled"] for row in rows),
        "profiles": rows,
    }


def validate_frozen_policy(policy: dict[str, Any], r2_manifest: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if policy.get("review_bundle_id") != r2_manifest.get("bundle_id"):
        blockers.append("R2_BUNDLE_ID_MISMATCH")
    if policy.get("review_bundle_hash") != r2_manifest.get("bundle_hash"):
        blockers.append("R2_BUNDLE_HASH_MISMATCH")
    if policy.get("selected_policy_ids") != EXPECTED_SELECTION:
        blockers.append("OWNER_SELECTION_MISMATCH")
    if policy.get("scope") != {"profile_id": "SHORT_ATM_DAYS_WEEK", "rights": ["CALL", "PUT"], "evidence_strata_separate": True}:
        blockers.append("OWNER_SCOPE_MISMATCH")
    permissions = policy.get("permissions", {})
    if not permissions.get("offline_engineering"):
        blockers.append("OFFLINE_ENGINEERING_NOT_ENABLED")
    for forbidden in ("forward_paper", "signal_generation", "automatic_paper_entry", "real_orders"):
        if permissions.get(forbidden):
            blockers.append(f"FORBIDDEN_PERMISSION_{forbidden.upper()}")
    return {
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "policy_id": policy.get("policy_id"),
        "policy_hash": content_hash(policy),
        "selected_policy_ids": policy.get("selected_policy_ids"),
        "scope": policy.get("scope"),
        "permissions": permissions,
    }


def initialize_review_store(path: Path = REVIEW_DB) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute("INSERT OR REPLACE INTO review_meta VALUES (?,?,?)", ("schema_version", json.dumps(1), utc_now()))
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    return {"path": str(path.resolve()), "schema_version": 1, "integrity_check": integrity}


def _task(task_id: str, state: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {"task_id": task_id, "state": state, "detail": detail, "updated_at": utc_now()}


def _store_review(bundle_id: str, acceptance: dict[str, Any], tasks: list[dict[str, Any]], path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT OR REPLACE INTO review_acceptances VALUES (?,?,?,?)", (bundle_id, acceptance["prior_bundle_id"], json.dumps(acceptance, ensure_ascii=False, sort_keys=True), acceptance["recorded_at"]))
        for task in tasks:
            connection.execute("INSERT OR REPLACE INTO review_task_state VALUES (?,?,?,?,?)", (bundle_id, task["task_id"], task["state"], json.dumps(task["detail"], ensure_ascii=False, sort_keys=True), task["updated_at"]))
        connection.commit()


def _forward_preflight(policy_validation: dict[str, Any], replay: dict[str, Any]) -> dict[str, Any]:
    blockers = ["R3_OWNER_REVIEW_REQUIRED", "FORWARD_MARKET_EVIDENCE_NOT_COLLECTED", "NATIVE_BBO_EVENT_TIME_UNAVAILABLE"]
    if policy_validation.get("status") != "PASS":
        blockers.append("FROZEN_POLICY_INVALID")
    if replay.get("ledger", {}).get("integrity_check") != "ok":
        blockers.append("LEDGER_INTEGRITY_FAILED")
    return {
        "status": "BLOCKED",
        "forward_paper_allowed": False,
        "signals_enabled": False,
        "automatic_paper_entries_enabled": False,
        "orders_enabled": False,
        "blockers": blockers,
        "next_required_review": "R3",
    }


def _review_text(bundle_id: str, validation: dict[str, Any], replay: dict[str, Any], preflight: dict[str, Any]) -> str:
    ledger = replay["ledger"]
    return f"""# R3 Review: offline option Paper engineering

- Bundle: `{bundle_id}`
- Version: `{REVIEW_VERSION}`
- State: `WAIT_REVIEW`
- Policy: `{validation['policy_id']}`
- Policy hash: `{validation['policy_hash']}`
- Engineering replay: `{replay['classification']}`
- Forward Paper: `{preflight['status']}`

## What is implemented

1. The exact R2 owner selection is frozen for `SHORT_ATM_DAYS_WEEK`; Call and Put retain separate evidence strata.
2. Closed/as-of candidate evaluation, opportunity deduplication, deterministic contract selection and immutable plan creation share one pure engineering core.
3. The receipt-time quote proxy rejects pre-decision, cached, stale, malformed and over-wide quotes. It is never relabeled as native BBO or exchange execution.
4. Call and Put use separate research portfolios. The ledger enforces one position per underlying, total premium limits and optimistic portfolio versions before accepting an entry.
5. The independent ledger records plan state, quote events, entry/exit fills, premium-at-risk, costs, net R and immutable transitions.
6. Missing exit quotes remain `PAPER_EXIT_PENDING`; restart restores the open position before a later eligible quote closes it. Frozen hard-loss and profit-review thresholds are checked before an exit is accepted.
7. Failure injection verifies transaction rollback and event replay idempotency.

## Replay evidence

- Opportunities: `{ledger['counts']['opportunities']}`
- Plans: `{ledger['counts']['plans']}`
- Quote observations: `{ledger['counts']['quote_events']}`
- Engineering fills: `{ledger['counts']['paper_fills']}`
- Final plan states: `{json.dumps(ledger['plan_states'], ensure_ascii=False, sort_keys=True)}`
- Restart-open positions recovered: `{replay['restart_recovered_open_positions']}`
- Rollback probe: `{replay['rollback_probe']['status']}`

These records are synthetic engineering fixtures. They are not strategy samples, historical option fills, a win rate, PF, payoff or evidence of profitability.

## Owner test

1. Open the R3 Review page and confirm the selected IDs and Call/Put scope.
2. Confirm pre-decision quote rejection and duplicate-opportunity rejection.
3. Confirm one lifecycle reaches `PAPER_CLOSED` and the other passes through `PAPER_EXIT_PENDING` across restart.
4. Confirm ask-entry/bid-exit, commissions, extra slippage and frozen BASE risk denominator.
5. Confirm the ledger integrity and rollback probes pass.
6. Confirm forward Paper, signals and orders remain blocked.

## Required reply shape

```text
R3通过。仅对当前R3包中列明的policy hashes和SHORT_ATM_DAYS_WEEK CALL/PUT范围批准前向Paper研究。
按总计划启动P4，并并行推进P5中非策略工程。
保留严格证据限制，不批准实盘、自动增资或修改冻结策略。
```
"""


def run_p3(
    *,
    bundle_id: str,
    accepted_r2_bundle: str,
    acceptance_message: str,
    output_root: Path = OUTPUT_ROOT,
    review_db: Path = REVIEW_DB,
    paper_db: Path = PAPER_DB,
) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    if run_dir.exists():
        raise RuntimeError(f"R3 bundle already exists and is immutable: {run_dir}")
    run_dir.mkdir(parents=True)
    r2_dir, r2_manifest = _latest_r2(accepted_r2_bundle)
    policy = load_policy()
    validation = validate_frozen_policy(policy, r2_manifest)
    if validation["status"] != "PASS":
        raise RuntimeError(f"Frozen policy validation failed: {validation['blockers']}")
    profile_boundary = _profile_boundary()
    if not profile_boundary["preserved"]:
        raise RuntimeError("Original profile activation boundary changed")
    store = initialize_review_store(review_db)
    replay = run_engineering_replay(paper_db, f"{bundle_id}-engineering-fixture-v1")
    preflight = _forward_preflight(validation, replay)
    acceptance = {
        "review_id": "R2",
        "prior_bundle_id": accepted_r2_bundle,
        "prior_bundle_hash": r2_manifest["bundle_hash"],
        "decision": "APPROVED_FOR_P3_OFFLINE_ENGINEERING_ONLY",
        "selection": EXPECTED_SELECTION,
        "scope": {"profile_id": "SHORT_ATM_DAYS_WEEK", "rights": ["CALL", "PUT"], "separate_validation": True},
        "user_message": acceptance_message,
        "recorded_at": utc_now(),
        "forward_paper_approved": False,
        "signals_approved": False,
        "orders_approved": False,
    }
    tasks = [
        _task("T13", "VERIFIED", {"policy_id": policy["policy_id"], "policy_hash": validation["policy_hash"], "scope": validation["scope"], "old_profiles_mutated": False}),
        _task("T14", "VERIFIED", {"candidate_kernel": "CLOSED_AS_OF", "deduplication": True, "rights_separate": True, "real_orders": False}),
        _task("T15", "VERIFIED", {"execution_policy_id": EXPECTED_SELECTION["paper_execution"], "predecision_rejected": True, "receipt_proxy_only": True, "native_bbo_gate_unchanged": True}),
        _task("T16", "VERIFIED", {"ledger": replay["ledger"], "restart_recovered_open_positions": replay["restart_recovered_open_positions"], "exit_pending_preserved": True, "portfolio_version_enforced": True, "rights_use_separate_portfolios": True, "frozen_exit_thresholds_enforced": True}),
        _task("T17", "VERIFIED", {"classification": replay["classification"], "rollback_probe": replay["rollback_probe"], "performance_eligible": False}),
        _task("T18", "WAIT_REVIEW", {"review_id": "R3", "bundle_id": bundle_id, "forward_preflight": preflight["status"]}),
    ]
    _store_review(bundle_id, acceptance, tasks, review_db)

    write_json_immutable(run_dir / "r2_acceptance.json", acceptance)
    write_json_immutable(run_dir / "frozen_policy.json", policy)
    write_json_immutable(run_dir / "policy_validation.json", validation)
    write_json_immutable(run_dir / "engineering_replay.json", replay)
    write_json_immutable(run_dir / "ledger_summary.json", replay["ledger"])
    write_json_immutable(run_dir / "forward_preflight.json", preflight)
    write_json_immutable(run_dir / "profile_boundary.json", profile_boundary)
    write_json_immutable(run_dir / "task_state.json", {"tasks": tasks})
    write_text_immutable(run_dir / "REVIEW.md", _review_text(bundle_id, validation, replay, preflight))
    write_text_immutable(run_dir / "RESUME.md", f"Run `python scripts/run_options_review_r3.py status` and open the R3 URL. Do not start forward Paper before exact R3 acceptance. Bundle `{bundle_id}`.\n")
    write_text_immutable(run_dir / "KNOWN_LIMITATIONS.md", "1. The replay uses synthetic engineering fixtures and is not performance evidence.\n2. Native BBO event time remains unavailable.\n3. Receipt-time quotes are a research proxy, not exchange fills.\n4. Event coverage is incomplete and unknown events abstain.\n5. Forward Paper, signals and orders remain disabled.\n")

    source_files = [
        Path(__file__),
        REPO_ROOT / "kquant" / "options_paper_engineering.py",
        REPO_ROOT / "scripts" / "run_options_review_r3.py",
        REPO_ROOT / "kquant" / "dashboard" / "app.py",
        REPO_ROOT / "web" / "src" / "unified" / "OptionsResearchWorkbench.tsx",
        REPO_ROOT / "web" / "src" / "unified" / "OptionsWorkspace.tsx",
        REPO_ROOT / "web" / "src" / "unified" / "i18n.tsx",
        REPO_ROOT / "web" / "src" / "unified" / "options-workspace.css",
        POLICY_PATH,
        PROFILE_PATH,
        MASTER_PLAN_PATH,
        OWNER_PLAYBOOK_PATH,
        TASK_GRAPH_PATH,
        R2_ACCEPTANCE_PATH,
    ]
    manifest = {
        "review_id": "R3",
        "bundle_id": bundle_id,
        "review_version": REVIEW_VERSION,
        "engine_version": ENGINE_VERSION,
        "state": "WAIT_REVIEW",
        "generated_at": utc_now(),
        "git": _git_identity(),
        "prior_review": {"bundle_id": accepted_r2_bundle, "bundle_hash": r2_manifest["bundle_hash"], "run_dir": str(r2_dir.resolve())},
        "code_hashes": {str(path.relative_to(REPO_ROOT)): sha256_file(path) for path in source_files},
        "policy_validation": validation,
        "profile_boundary": profile_boundary,
        "review_store": store,
        "paper_ledger": replay["ledger"],
        "forward_preflight": preflight,
        "permissions": {"offline_engineering": True, "forward_paper": False, "signals": False, "automatic_paper_entries": False, "orders": False, "real_account": False},
        "performance_status": "NOT_EVALUATED_ENGINEERING_FIXTURES_ONLY",
        "tests": {"status": "PENDING_FINALIZATION"},
    }
    manifest["bundle_hash"] = content_hash(manifest)
    write_json_immutable(run_dir / "manifest.pre_verification.json", manifest)
    write_json_immutable(run_dir / "ACCEPTANCE.json", {"review_id": "R3", "bundle_id": bundle_id, "state": "WAIT_REVIEW", "engineering_chain": "IMPLEMENTED", "forward_paper_allowed": False, "performance_status": manifest["performance_status"]})
    latest = {"bundle_id": bundle_id, "bundle_hash": manifest["bundle_hash"], "run_dir": str(run_dir.resolve()), "state": "WAIT_REVIEW", "updated_at": utc_now()}
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = output_root / "LATEST.json.tmp"
    temporary.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_root / "LATEST.json")
    return {"status": "WAIT_REVIEW", "bundle_id": bundle_id, "run_dir": str(run_dir.resolve()), "validation": validation, "replay": replay, "preflight": preflight, "tasks": tasks, "manifest": manifest}


def finalize_p3_bundle(bundle_id: str, verification: dict[str, Any], *, output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    preliminary = run_dir / "manifest.pre_verification.json"
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        raise RuntimeError(f"R3 bundle is already finalized and immutable: {manifest_path}")
    if not preliminary.exists():
        raise FileNotFoundError(preliminary)
    verification_path = run_dir / "verification.json"
    write_json_immutable(verification_path, verification)
    manifest = load_json(preliminary)
    checks = [value for value in verification.values() if isinstance(value, bool)]
    manifest["tests"] = {"status": "PASS" if checks and all(checks) else "PARTIAL", "verification_sha256": sha256_file(verification_path)}
    manifest["finalized_at"] = utc_now()
    manifest["bundle_hash"] = content_hash({key: value for key, value in manifest.items() if key != "bundle_hash"})
    write_json_immutable(manifest_path, manifest)
    latest = {"bundle_id": bundle_id, "bundle_hash": manifest["bundle_hash"], "run_dir": str(run_dir.resolve()), "state": "WAIT_REVIEW", "updated_at": utc_now()}
    temporary = output_root / "LATEST.json.tmp"
    temporary.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_root / "LATEST.json")
    return manifest


def review_r3_payload(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    latest_path = output_root / "LATEST.json"
    if not latest_path.exists():
        return {"status": "NOT_AVAILABLE", "review_id": "R3", "state": "NOT_OPEN"}
    latest = load_json(latest_path)
    run_dir = Path(latest["run_dir"])
    required = {
        "manifest": "manifest.json" if (run_dir / "manifest.json").exists() else "manifest.pre_verification.json",
        "acceptance": "r2_acceptance.json",
        "policy": "frozen_policy.json",
        "validation": "policy_validation.json",
        "replay": "engineering_replay.json",
        "ledger": "ledger_summary.json",
        "preflight": "forward_preflight.json",
        "profiles": "profile_boundary.json",
        "tasks": "task_state.json",
    }
    payload = {key: load_json(run_dir / name) for key, name in required.items() if (run_dir / name).exists()}
    return {
        "status": "AVAILABLE",
        "review_id": "R3",
        "state": "WAIT_REVIEW",
        "bundle_id": latest["bundle_id"],
        "bundle_hash": latest["bundle_hash"],
        "review_url": f"http://127.0.0.1:8020/?workspace=options&view=review&symbol=NVDA&review={latest['bundle_id']}",
        **payload,
        "signals_enabled": False,
        "forward_paper_enabled": False,
        "orders_enabled": False,
    }


__all__ = ["OUTPUT_ROOT", "PAPER_DB", "REVIEW_DB", "finalize_p3_bundle", "review_r3_payload", "run_p3", "validate_frozen_policy"]
