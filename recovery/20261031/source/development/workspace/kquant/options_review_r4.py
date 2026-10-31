from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .options_forward_paper import (
    DEFAULT_DB_PATH,
    DEFAULT_RUN_ID,
    ENGINE_VERSION,
    backup_and_verify_forward_store,
    forward_status,
    load_forward_policy,
)
from .options_paper_engineering import content_hash


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "outputs" / "options_review_r4"
R3_MANIFEST = REPO_ROOT / "outputs" / "options_review_r3" / "options-r3-20260920-03" / "manifest.json"
R3_ACCEPTANCE = REPO_ROOT / "config" / "review_acceptances" / "options_r3_20260920.txt"
POLICY_PATH = REPO_ROOT / "config" / "options_short_atm_forward_policy_v1.json"
TASK_GRAPH_PATH = REPO_ROOT / "plan" / "options_personal_master_tasks.v1.json"
REVIEW_VERSION = "options-personal-r4.v1.0.0"


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


def _write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise RuntimeError(f"immutable R4 artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    if path.exists():
        raise RuntimeError(f"immutable R4 artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def _git() -> dict[str, Any]:
    def run(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    status = run("status", "--short")
    return {"head": run("rev-parse", "HEAD"), "branch": run("branch", "--show-current"), "status_hash": hashlib.sha256(status.encode()).hexdigest(), "dirty": bool(status)}


def _tasks(status: dict[str, Any]) -> list[dict[str, Any]]:
    completed = int(status.get("ledger", {}).get("completed") or 0)
    wait = status.get("status") == "WAIT_MARKET"
    return [
        {"task_id": "T19", "state": "WAIT_MARKET" if wait else "RUNNING", "evidence": {"run_id": status.get("run", {}).get("run_id"), "policy_hash": status.get("run", {}).get("policy_hash"), "natural_opportunities_only": True}},
        {"task_id": "T20", "state": "WAIT_DATA" if completed == 0 else "RUNNING", "evidence": {"completed_forward_paper_trades": completed, "dependency_groups_persisted": True}},
        {"task_id": "T21", "state": "WAIT_DATA", "evidence": {"gate_result": "INCONCLUSIVE", "zero_sample_metrics": "NOT_APPLICABLE"}},
        {"task_id": "T22", "state": "VERIFIED", "evidence": {"result": "NOT_REQUIRED_NO_MODEL_CONSUMED"}},
        {"task_id": "T23", "state": "VERIFIED", "evidence": status.get("risk_research")},
        {"task_id": "T24", "state": "WAIT_REVIEW", "evidence": {"allowed_result": "INTERIM_ENGINEERING_REVIEW_ONLY"}},
        {"task_id": "T25", "state": "VERIFYING", "evidence": {"three_groups_separate": True, "paper_and_manual_records_separate": True}},
        {"task_id": "T26", "state": "WAIT_PERMISSION", "evidence": {"reason": "NO_AUTHORIZED_PUSH_RECIPIENT_CONFIRMED_IN_THIS_REVIEW"}},
        {"task_id": "T27", "state": "VERIFIED", "evidence": {"backup_restore": "PASS", "kill_new_entries": True, "real_orders": False}},
        {"task_id": "T28", "state": "VERIFYING", "evidence": {"runbook": "RUNBOOK.md"}},
        {"task_id": "T29", "state": "VERIFYING", "evidence": {"browser_and_mobile": "PENDING_FINAL_VERIFICATION", "real_api_order_test": "FORBIDDEN"}},
    ]


def _runbook(bundle_id: str, run_id: str) -> str:
    return f"""# KQUANT Options P4/P5 Runbook

Bundle: `{bundle_id}`  
Forward run: `{run_id}`  
Execution class: receipt-time quote proxy Paper research only.

## Start or resume

```powershell
cd C:\\Users\\Administrator\\Desktop\\KQUANT-
.\\start_kquant_workspace.ps1 -OptionsFoundation -KillExisting -NoBrowser
.\\.venv\\Scripts\\python.exe scripts\\run_options_forward_paper.py status
```

The existing Foundation Supervisor owns scheduling. Do not launch a second supervisor.

## Status

```powershell
.\\.venv\\Scripts\\python.exe scripts\\run_options_forward_paper.py status
Invoke-RestMethod http://127.0.0.1:8001/api/options/research/forward/status
```

## Pause or resume new Paper entries

```powershell
.\\.venv\\Scripts\\python.exe scripts\\run_options_forward_paper.py pause --reason operator_review
.\\.venv\\Scripts\\python.exe scripts\\run_options_forward_paper.py resume
```

Pausing new entries does not delete the ledger and does not stop monitoring open Paper records.

## Backup and restore proof

```powershell
.\\.venv\\Scripts\\python.exe scripts\\run_options_forward_paper.py backup
```

## Stop services

```powershell
.\\stop_kquant_options_foundation.ps1
```

## Boundaries

- No real account API and no order route.
- No public trade signal.
- No automatic capital increase.
- No policy mutation.
- Receipt-time observations are never relabeled as native BBO or exchange fills.
- `0` completed trades produces `N/A / INCONCLUSIVE`, never PASS.
"""


def run_p4(
    *,
    bundle_id: str,
    run_id: str = DEFAULT_RUN_ID,
    store_path: Path = DEFAULT_DB_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    if run_dir.exists():
        raise RuntimeError(f"R4 bundle already exists and is immutable: {run_dir}")
    r3 = _load(R3_MANIFEST)
    policy = load_forward_policy()
    status = forward_status(store_path=store_path, run_id=run_id)
    if status.get("status") == "NOT_STARTED":
        raise RuntimeError("forward Paper run has not started")
    if status.get("run", {}).get("r3_bundle_hash") != r3.get("bundle_hash"):
        raise RuntimeError("forward run is not bound to the accepted R3 bundle")
    backup = backup_and_verify_forward_store(store_path=store_path)
    deficiency = {
        "generated_at": _now(),
        "market_state": status.get("status"),
        "completed_forward_paper_trades": status.get("ledger", {}).get("completed", 0),
        "blocking_only": [
            "WAIT_MARKET" if status.get("status") == "WAIT_MARKET" else None,
            "EVENT_COVERAGE_INCOMPLETE_OR_BLOCKED",
            "SAME_CLOCK_TURNOVER_20_SESSION_LINEAGE_UNAVAILABLE",
            "OPTION_DEPTH_SIZE_UNIT_UNVERIFIED",
        ],
        "not_blocked": ["service_engineering", "three_group_interface", "backup_restore", "read_only_status", "deterministic_risk"],
        "performance_result": "INCONCLUSIVE",
    }
    deficiency["blocking_only"] = [item for item in deficiency["blocking_only"] if item]
    task_state = _tasks(status)
    source_files = [POLICY_PATH, R3_ACCEPTANCE, TASK_GRAPH_PATH, Path(__file__), REPO_ROOT / "kquant" / "options_forward_paper.py", REPO_ROOT / "scripts" / "run_options_forward_paper.py"]
    manifest = {
        "review_id": "R4",
        "bundle_id": bundle_id,
        "review_version": REVIEW_VERSION,
        "engine_version": ENGINE_VERSION,
        "state": "WAIT_REVIEW",
        "result_class": "INTERIM_ENGINEERING_REVIEW_ONLY",
        "generated_at": _now(),
        "git": _git(),
        "accepted_r3": {"bundle_id": r3["bundle_id"], "bundle_hash": r3["bundle_hash"], "acceptance_sha256": _sha(R3_ACCEPTANCE)},
        "forward_run": {"run_id": run_id, "status": status.get("status"), "policy_hash": status.get("run", {}).get("policy_hash")},
        "scope": policy["scope"],
        "selected_policy_ids": policy["selected_policy_ids"],
        "performance_status": "INCONCLUSIVE_WAIT_MARKET" if status.get("status") == "WAIT_MARKET" else "INCONCLUSIVE_INSUFFICIENT_FORWARD_EVIDENCE",
        "model_status": status.get("model_status"),
        "permissions": policy["permissions"],
        "backup": backup,
        "code_hashes": {str(path.relative_to(REPO_ROOT)): _sha(path) for path in source_files},
        "tests": {"status": "PENDING_FINALIZATION"},
    }
    manifest["bundle_hash"] = content_hash({key: value for key, value in manifest.items() if key != "bundle_hash"})
    _write_json(run_dir / "manifest.pre_verification.json", manifest)
    _write_json(run_dir / "forward_status.json", status)
    _write_json(run_dir / "frozen_forward_policy.json", policy)
    _write_json(run_dir / "deficiency_manifest.json", deficiency)
    _write_json(run_dir / "deterministic_risk.json", status["risk_research"])
    _write_json(run_dir / "model_decision.json", {"status": status["model_status"], "reason": "The approved strategy consumes deterministic frozen features, not a model score or probability."})
    _write_json(run_dir / "task_state.json", task_state)
    _write_json(run_dir / "backup_restore.json", backup)
    _write_text(run_dir / "RUNBOOK.md", _runbook(bundle_id, run_id))
    _write_json(run_dir / "ACCEPTANCE.json", {"review_id": "R4", "state": "WAIT_REVIEW", "allowed_result": "INTERIM_ENGINEERING_REVIEW_ONLY", "performance_status": manifest["performance_status"], "real_orders": False})
    output_root.mkdir(parents=True, exist_ok=True)
    latest = {"bundle_id": bundle_id, "bundle_hash": manifest["bundle_hash"], "run_dir": str(run_dir.resolve()), "state": "WAIT_REVIEW", "updated_at": _now()}
    temporary = output_root / "LATEST.json.tmp"
    temporary.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_root / "LATEST.json")
    return {"status": "WAIT_REVIEW", "bundle_id": bundle_id, "run_dir": str(run_dir.resolve()), "manifest": manifest, "forward": status, "tasks": task_state}


def finalize_p4(bundle_id: str, verification: dict[str, Any], *, output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    preliminary = run_dir / "manifest.pre_verification.json"
    final = run_dir / "manifest.json"
    if final.exists():
        raise RuntimeError(f"R4 bundle already finalized: {final}")
    _write_json(run_dir / "verification.json", verification)
    manifest = _load(preliminary)
    checks = [value for value in verification.values() if isinstance(value, bool)]
    manifest["tests"] = {"status": "PASS" if checks and all(checks) else "PARTIAL", "verification_sha256": _sha(run_dir / "verification.json")}
    manifest["finalized_at"] = _now()
    manifest["bundle_hash"] = content_hash({key: value for key, value in manifest.items() if key != "bundle_hash"})
    _write_json(final, manifest)
    latest = {"bundle_id": bundle_id, "bundle_hash": manifest["bundle_hash"], "run_dir": str(run_dir.resolve()), "state": "WAIT_REVIEW", "updated_at": _now()}
    temporary = output_root / "LATEST.json.tmp"
    temporary.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_root / "LATEST.json")
    return manifest


def review_r4_payload(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    latest_path = output_root / "LATEST.json"
    if not latest_path.exists():
        return {"status": "NOT_AVAILABLE", "review_id": "R4", "state": "NOT_OPEN"}
    latest = _load(latest_path)
    run_dir = Path(latest["run_dir"])
    names = {
        "manifest": "manifest.json" if (run_dir / "manifest.json").exists() else "manifest.pre_verification.json",
        "forward": "forward_status.json",
        "policy": "frozen_forward_policy.json",
        "deficiency": "deficiency_manifest.json",
        "risk": "deterministic_risk.json",
        "model": "model_decision.json",
        "tasks": "task_state.json",
        "backup": "backup_restore.json",
    }
    payload = {key: _load(run_dir / name) for key, name in names.items() if (run_dir / name).exists()}
    return {
        "status": "AVAILABLE",
        "review_id": "R4",
        "state": "WAIT_REVIEW",
        "bundle_id": latest["bundle_id"],
        "bundle_hash": latest["bundle_hash"],
        "review_url": f"http://127.0.0.1:8020/?workspace=options&view=review&symbol=NVDA&review={latest['bundle_id']}",
        **payload,
        "orders_enabled": False,
        "real_account_enabled": False,
    }


__all__ = ["OUTPUT_ROOT", "finalize_p4", "review_r4_payload", "run_p4"]
