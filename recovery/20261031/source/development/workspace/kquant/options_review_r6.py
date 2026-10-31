from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .options_forward_paper import DEFAULT_DB_PATH, DEFAULT_RUN_ID, forward_status, load_forward_policy
from .options_paper_engineering import content_hash


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "outputs" / "options_review_r6"
STATE_ROOT = REPO_ROOT / "work" / "options_delivery_v1"
R5_MANIFEST = REPO_ROOT / "outputs" / "options_review_r5" / "options-r5-20260920-04" / "manifest.json"
R5_ACCEPTANCE = REPO_ROOT / "config" / "review_acceptances" / "options_r5_20260920.txt"
R6_ACCEPTANCE = REPO_ROOT / "config" / "review_acceptances" / "options_r6_20260920.txt"
POLICY_PATH = REPO_ROOT / "config" / "options_short_atm_forward_policy_v1.json"
TASK_GRAPH_PATH = REPO_ROOT / "plan" / "options_personal_master_tasks.v1.json"
REVIEW_VERSION = "options-personal-r6.v1.0.0"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_label(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path.resolve())


def _write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise RuntimeError(f"immutable R6 artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    if path.exists():
        raise RuntimeError(f"immutable R6 artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def _atomic_state(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _append_event(value: dict[str, Any]) -> None:
    path = STATE_ROOT / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _git() -> dict[str, Any]:
    def run(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    status = run("status", "--short")
    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "status_hash": hashlib.sha256(status.encode()).hexdigest(),
        "dirty": bool(status),
    }


def _scope_readiness(forward: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    metrics = forward.get("metrics") or {}
    groups = {item.get("profile_id"): item for item in forward.get("groups") or []}
    minimum = int(policy["metric_policy"]["minimum_completed_per_profile_right"])
    short_rights = []
    for right in ("CALL", "PUT"):
        metric = metrics.get(right) or {}
        completed = int(metric.get("completed") or 0)
        gate_status = str(metric.get("gate_status") or "INCONCLUSIVE")
        short_rights.append({
            "right": right,
            "completed": completed,
            "minimum_completed": minimum,
            "profit_factor": metric.get("profit_factor"),
            "payoff": metric.get("payoff"),
            "average_net_r": metric.get("average_net_r"),
            "evidence_gate": gate_status,
            "readiness": "WAIT_EVIDENCE",
            "reasons": [
                "NO_COMPLETED_FORWARD_PAPER_TRADES" if completed == 0 else "MINIMUM_SAMPLE_GATE_NOT_MET",
                "PERFORMANCE_REMAINS_INCONCLUSIVE",
                "INDEPENDENT_EVIDENCE_GATE_NOT_MET",
            ],
        })
    scopes = [
        {
            "profile_id": "SHORT_ATM_DAYS_WEEK",
            "status": "WAIT_EVIDENCE",
            "forward_state": (groups.get("SHORT_ATM_DAYS_WEEK") or {}).get("state", forward.get("status")),
            "rights": short_rights,
            "strategy_id": policy["selected_policy_ids"]["strategy"],
            "policy_hash": forward.get("run", {}).get("policy_hash"),
            "eligible_for_owner_manual_use_review": False,
        },
        {
            "profile_id": "MEDIUM_ATM_WEEKS_MONTHS",
            "status": "NOT_EVALUATED",
            "forward_state": (groups.get("MEDIUM_ATM_WEEKS_MONTHS") or {}).get("state", "NOT_EVALUATED"),
            "rights": [],
            "eligible_for_owner_manual_use_review": False,
            "reason": "RESEARCH_CONTINUES_NOT_APPROVED_FOR_FORWARD_PAPER",
        },
        {
            "profile_id": "LONG_OTM_MONTHS_YEAR",
            "status": "NOT_EVALUATED",
            "forward_state": (groups.get("LONG_OTM_MONTHS_YEAR") or {}).get("state", "NOT_EVALUATED"),
            "rights": [],
            "eligible_for_owner_manual_use_review": False,
            "reason": "RESEARCH_CONTINUES_NOT_APPROVED_FOR_FORWARD_PAPER",
        },
    ]
    return {
        "readiness_status": "NO_GO_WAIT_EVIDENCE",
        "eligible_scopes": [],
        "scopes": scopes,
        "gates": {
            "D_PAPER_DATA": {"status": "WAIT_EVIDENCE", "reason": "ZERO_COMPLETED_FORWARD_PAPER_TRADES"},
            "V_STRATEGY_EVIDENCE": {"status": "INCONCLUSIVE", "reason": "NO_PROFILE_RIGHT_PASSES_FROZEN_METRIC_POLICY"},
            "R_RELEASE_SAFE": {"status": "PASS_WITH_LIMITATIONS", "reason": "R5_ENGINEERING_PASS_TRADING_DISABLED"},
            "H_EXACT_MANUAL_AUTH": {"status": "NOT_REQUESTED", "reason": "NO_QUALIFIED_SCOPE"},
        },
        "live_not_enabled": True,
        "orders_enabled": False,
        "real_account_enabled": False,
    }


def _manual_approval_template() -> dict[str, Any]:
    return {
        "status": "NOT_ISSUABLE_NO_QUALIFIED_SCOPE",
        "eligible_scope": None,
        "account_service_entity": None,
        "account_options_qualification_confirmed": None,
        "capital_usd": None,
        "absolute_maximum_loss_usd": None,
        "per_trade_limit_usd": None,
        "total_open_limit_usd": None,
        "daily_loss_limit_usd": None,
        "cumulative_loss_limit_usd": None,
        "allowed_underlyings": None,
        "allowed_rights": None,
        "expiry_policy": None,
        "attended_hours": None,
        "notification_destination": None,
        "valid_from": None,
        "expires_at": None,
        "revocation_method": None,
        "stop_method": None,
        "owner_confirmation": None,
        "codex_order_submission_allowed": False,
        "reason": "NO_SCOPE_PASSES_DATA_AND_STRATEGY_EVIDENCE_GATES",
    }


def _tasks(readiness: dict[str, Any], verification: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    verified = verification or {}
    checks = ("backend_passed", "frontend_passed", "build_passed", "readonly_passed", "browser_passed")
    report_verified = bool(verification) and all(bool(verified.get(key)) for key in checks)
    return [
        {"task_id": "T31", "state": "DELIVERED_NO_GO_WAIT_EVIDENCE", "evidence": {"eligible_scope_count": 0, "readiness_status": readiness["readiness_status"], "gate_statuses": readiness["gates"]}},
        {"task_id": "T32", "state": "NOT_ISSUED_NO_QUALIFIED_SCOPE", "evidence": {"actual_amounts_remain_null": True, "owner_manual_use_approval_requested": False}},
        {"task_id": "T33", "state": "NOT_STARTED_NO_AUTH", "evidence": {"human_broker_action_observed": False, "system_order_submission": False}},
        {"task_id": "T34", "state": "NOT_STARTED_NO_AUTH", "evidence": {"actual_fill_imported": False}},
        {"task_id": "T35", "state": "NOT_STARTED_NO_AUTH", "evidence": {"live_position_tracking_started": False}},
        {"task_id": "T36", "state": "WAIT_REVIEW_NO_LIVE_SUMMARY" if report_verified else "VERIFYING_NO_LIVE_SUMMARY", "evidence": {"live_status": "LIVE_NOT_ENABLED", "same_version_checks": verified, "performance_status": "INCONCLUSIVE"}},
    ]


def _readiness_report(bundle_id: str, readiness: dict[str, Any], forward: dict[str, Any]) -> str:
    return f"""# Options manual-use readiness report

Bundle: `{bundle_id}`  
Decision: `NO_GO_WAIT_EVIDENCE`  
Live status: `LIVE_NOT_ENABLED`

## Qualified scopes

None.

`SHORT_ATM_DAYS_WEEK` Call and Put remain separate. Both have 0 completed forward Paper trades against a frozen minimum of 200 per profile/right, so performance is `INCONCLUSIVE`. The forward run remains `{forward.get('status')}`.

`MEDIUM_ATM_WEEKS_MONTHS` and `LONG_OTM_MONTHS_YEAR` remain `NOT_EVALUATED` and continue research.

## Gate audit

- `D_PAPER_DATA`: `WAIT_EVIDENCE`
- `V_STRATEGY_EVIDENCE`: `INCONCLUSIVE`
- `R_RELEASE_SAFE`: `PASS_WITH_LIMITATIONS`
- `H_EXACT_MANUAL_AUTH`: `NOT_REQUESTED`, because no scope qualifies

No account, capital, loss limit, validity period, or broker authorization is requested in this report. No order path is enabled.
"""


def _review_guide(bundle_id: str) -> str:
    return f"""# R6 no-live owner review

Open:

```text
http://127.0.0.1:8020/?workspace=options&view=review&symbol=NVDA&review={bundle_id}
```

1. Confirm the R6 decision is `NO_GO_WAIT_EVIDENCE` and live status is `LIVE_NOT_ENABLED`.
2. Confirm the qualified-scope count is zero.
3. Confirm Short ATM Call and Put remain separate with 0 completed forward Paper results.
4. Confirm Medium ATM and Long OTM remain `NOT_EVALUATED`.
5. Confirm all real account, capital, risk, validity, and owner authorization fields remain null.
6. Confirm real-order submission remains disabled.

Accepting this review accepts the no-live conclusion. It does not authorize manual or automated trading.
"""


def _resume_guide() -> str:
    return """# Resume entry

Current state: `WAIT_REVIEW` at R6 with `LIVE_NOT_ENABLED`.

The frozen Short ATM forward observation continues. Medium ATM and Long OTM continue research. Re-run readiness only after a concrete profile/right passes the existing data, performance, risk, and release gates; do not lower thresholds or merge evidence.

Expected acceptance phrase:

```text
R6通过，接受LIVE_NOT_ENABLED结论。继续冻结观察与未合格组研究，不启用真实资金。
```
"""


def run_p6(*, bundle_id: str, store_path: Path = DEFAULT_DB_PATH, output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    if run_dir.exists():
        raise RuntimeError(f"R6 bundle already exists and is immutable: {run_dir}")
    r5 = _load(R5_MANIFEST)
    if r5.get("tests", {}).get("status") != "PASS":
        raise RuntimeError("R5 engineering verification is not PASS")
    if not R5_ACCEPTANCE.exists():
        raise RuntimeError("R5 owner acceptance is missing")
    policy = load_forward_policy()
    forward = forward_status(store_path=store_path, run_id=DEFAULT_RUN_ID)
    if forward.get("run", {}).get("policy_hash") != r5.get("forward_run", {}).get("policy_hash"):
        raise RuntimeError("forward policy hash changed after R5")
    readiness = _scope_readiness(forward, policy)
    approval = _manual_approval_template()
    tasks = _tasks(readiness)
    run_dir.mkdir(parents=True)
    sources = [R5_MANIFEST, R5_ACCEPTANCE, POLICY_PATH, TASK_GRAPH_PATH, Path(__file__)]
    manifest = {
        "review_id": "R6",
        "bundle_id": bundle_id,
        "review_version": REVIEW_VERSION,
        "state": "WAIT_REVIEW",
        "release_class": "PERSONAL_RESEARCH_CONTINUES_LIVE_NOT_ENABLED",
        "generated_at": _now(),
        "git": _git(),
        "accepted_r5": {"bundle_id": r5["bundle_id"], "bundle_hash": r5["bundle_hash"], "acceptance_sha256": _sha(R5_ACCEPTANCE)},
        "forward_run": {"run_id": DEFAULT_RUN_ID, "status": forward.get("status"), "policy_hash": forward.get("run", {}).get("policy_hash")},
        "readiness_status": readiness["readiness_status"],
        "performance_status": "INCONCLUSIVE",
        "live_status": "LIVE_NOT_ENABLED",
        "eligible_scope_count": 0,
        "orders_enabled": False,
        "real_account_enabled": False,
        "code_hashes": {_source_label(path): _sha(path) for path in sources},
        "tests": {"status": "PENDING_FINALIZATION"},
    }
    manifest["bundle_hash"] = content_hash({key: value for key, value in manifest.items() if key != "bundle_hash"})
    _write_json(run_dir / "manifest.pre_verification.json", manifest)
    _write_json(run_dir / "scope_readiness.json", readiness)
    _write_json(run_dir / "forward_status.json", forward)
    _write_json(run_dir / "manual_approval_template.json", approval)
    _write_json(run_dir / "task_state.json", tasks)
    _write_text(run_dir / "READINESS_REPORT.md", _readiness_report(bundle_id, readiness, forward))
    _write_text(run_dir / "NO_LIVE_SUMMARY.md", """# No-live summary

No scope currently qualifies for owner manual-use review. No live transaction occurred, no fill was imported, and no live position is being tracked. The system remains a personal research workspace with frozen forward Paper observation.
""")
    _write_text(run_dir / "REVIEW.md", _review_guide(bundle_id))
    _write_text(run_dir / "RESUME.md", _resume_guide())
    _write_json(run_dir / "ACCEPTANCE.json", {"review_id": "R6", "state": "WAIT_REVIEW", "live_status": "LIVE_NOT_ENABLED", "trading_permission": False})
    state = {"plan_version": "options-personal-master-v1", "release_cycle_id": bundle_id, "state": "WAIT_REVIEW", "tasks": tasks, "updated_at": _now()}
    _atomic_state(STATE_ROOT / "state.json", state)
    _append_event({"event": "R6_NO_LIVE_BUNDLE_CREATED", "bundle_id": bundle_id, "state": "WAIT_REVIEW", "readiness_status": readiness["readiness_status"], "live_status": "LIVE_NOT_ENABLED", "occurred_at": _now()})
    latest = {"bundle_id": bundle_id, "bundle_hash": manifest["bundle_hash"], "run_dir": str(run_dir.resolve()), "state": "WAIT_REVIEW", "updated_at": _now()}
    _atomic_state(output_root / "LATEST.json", latest)
    return {"status": "WAIT_REVIEW", "bundle_id": bundle_id, "run_dir": str(run_dir.resolve()), "manifest": manifest, "readiness": readiness, "tasks": tasks}


def finalize_p6(bundle_id: str, verification: dict[str, Any], *, output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    final = run_dir / "manifest.json"
    if final.exists():
        raise RuntimeError(f"R6 bundle already finalized: {final}")
    _write_json(run_dir / "verification.json", verification)
    manifest = _load(run_dir / "manifest.pre_verification.json")
    required = ("backend_passed", "frontend_passed", "build_passed", "readonly_passed", "browser_passed")
    manifest["tests"] = {"status": "PASS" if all(bool(verification.get(key)) for key in required) else "PARTIAL", "verification_sha256": _sha(run_dir / "verification.json")}
    manifest["finalized_at"] = _now()
    manifest["bundle_hash"] = content_hash({key: value for key, value in manifest.items() if key != "bundle_hash"})
    _write_json(final, manifest)
    readiness = _load(run_dir / "scope_readiness.json")
    tasks = _tasks(readiness, verification)
    _write_json(run_dir / "task_state.final.json", tasks)
    _atomic_state(STATE_ROOT / "state.json", {"plan_version": "options-personal-master-v1", "release_cycle_id": bundle_id, "state": "WAIT_REVIEW", "tasks": tasks, "updated_at": _now()})
    _append_event({"event": "R6_NO_LIVE_BUNDLE_FINALIZED", "bundle_id": bundle_id, "state": "WAIT_REVIEW", "test_status": manifest["tests"]["status"], "live_status": "LIVE_NOT_ENABLED", "occurred_at": _now()})
    _atomic_state(output_root / "LATEST.json", {"bundle_id": bundle_id, "bundle_hash": manifest["bundle_hash"], "run_dir": str(run_dir.resolve()), "state": "WAIT_REVIEW", "updated_at": _now()})
    return manifest


def accept_r6(bundle_id: str, *, output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    manifest = _load(run_dir / "manifest.json")
    if manifest.get("tests", {}).get("status") != "PASS":
        raise RuntimeError("R6 verification is not PASS")
    if manifest.get("live_status") != "LIVE_NOT_ENABLED" or int(manifest.get("eligible_scope_count") or 0) != 0:
        raise RuntimeError("R6 acceptance may only close the verified no-live branch")
    if not R6_ACCEPTANCE.exists():
        raise RuntimeError("R6 owner acceptance is missing")
    receipt_path = run_dir / "acceptance_receipt.json"
    receipt = {
        "review_id": "R6",
        "bundle_id": bundle_id,
        "bundle_hash": manifest["bundle_hash"],
        "state": "ACCEPTED_LIVE_NOT_ENABLED",
        "accepted_at": _now(),
        "acceptance_sha256": _sha(R6_ACCEPTANCE),
        "acceptance_processor_sha256": _sha(Path(__file__)),
        "live_status": "LIVE_NOT_ENABLED",
        "real_capital_enabled": False,
        "orders_enabled": False,
        "continuation": {
            "SHORT_ATM_DAYS_WEEK": "FROZEN_FORWARD_PAPER_OBSERVATION_CONTINUES",
            "MEDIUM_ATM_WEEKS_MONTHS": "RESEARCH_CONTINUES_NOT_EVALUATED",
            "LONG_OTM_MONTHS_YEAR": "RESEARCH_CONTINUES_NOT_EVALUATED",
            "strategy_mutation": False,
            "threshold_relaxation": False,
        },
    }
    _write_json(receipt_path, receipt)
    readiness = _load(run_dir / "scope_readiness.json")
    tasks = _tasks(readiness, {
        "backend_passed": True,
        "frontend_passed": True,
        "build_passed": True,
        "readonly_passed": True,
        "browser_passed": True,
    })
    for task in tasks:
        if task["task_id"] == "T36":
            task["state"] = "ACCEPTED_NO_LIVE"
            task["evidence"]["owner_acceptance_sha256"] = receipt["acceptance_sha256"]
    _write_json(run_dir / "task_state.accepted.json", tasks)
    state = {
        "plan_version": "options-personal-master-v1",
        "release_cycle_id": bundle_id,
        "state": "MAINTENANCE_RESEARCH_CONTINUES",
        "live_status": "LIVE_NOT_ENABLED",
        "tasks": tasks,
        "updated_at": _now(),
    }
    _atomic_state(STATE_ROOT / "state.json", state)
    _append_event({"event": "R6_ACCEPTED_LIVE_NOT_ENABLED", "bundle_id": bundle_id, "state": state["state"], "acceptance_sha256": receipt["acceptance_sha256"], "live_status": "LIVE_NOT_ENABLED", "occurred_at": _now()})
    _atomic_state(output_root / "LATEST.json", {"bundle_id": bundle_id, "bundle_hash": manifest["bundle_hash"], "run_dir": str(run_dir.resolve()), "state": "ACCEPTED_LIVE_NOT_ENABLED", "updated_at": _now()})
    return receipt


def review_r6_payload(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    latest_path = output_root / "LATEST.json"
    if not latest_path.exists():
        return {"status": "NOT_AVAILABLE", "review_id": "R6", "state": "NOT_OPEN"}
    latest = _load(latest_path)
    run_dir = Path(latest["run_dir"])
    names = {
        "manifest": "manifest.json" if (run_dir / "manifest.json").exists() else "manifest.pre_verification.json",
        "readiness": "scope_readiness.json",
        "forward": "forward_status.json",
        "manual_approval": "manual_approval_template.json",
        "tasks": "task_state.accepted.json" if (run_dir / "task_state.accepted.json").exists() else ("task_state.final.json" if (run_dir / "task_state.final.json").exists() else "task_state.json"),
        "acceptance": "acceptance_receipt.json",
    }
    payload = {key: _load(run_dir / name) for key, name in names.items() if (run_dir / name).exists()}
    return {
        "status": "AVAILABLE",
        "review_id": "R6",
        "state": latest.get("state", "WAIT_REVIEW"),
        "bundle_id": latest["bundle_id"],
        "bundle_hash": latest["bundle_hash"],
        "review_url": f"http://127.0.0.1:8020/?workspace=options&view=review&symbol=NVDA&review={latest['bundle_id']}",
        **payload,
        "trading_permission": False,
        "orders_enabled": False,
        "real_account_enabled": False,
    }


__all__ = ["OUTPUT_ROOT", "accept_r6", "finalize_p6", "review_r6_payload", "run_p6"]
