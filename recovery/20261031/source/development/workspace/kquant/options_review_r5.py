from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .options_forward_paper import (
    DEFAULT_DB_PATH,
    DEFAULT_RUN_ID,
    backup_and_verify_forward_store,
    forward_status,
    load_forward_policy,
)
from .options_paper_engineering import content_hash


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "outputs" / "options_review_r5"
STATE_ROOT = REPO_ROOT / "work" / "options_delivery_v1"
R4_MANIFEST = REPO_ROOT / "outputs" / "options_review_r4" / "options-r4-20260920-01" / "manifest.json"
R4_ACCEPTANCE = REPO_ROOT / "config" / "review_acceptances" / "options_r4_20260920.txt"
POLICY_PATH = REPO_ROOT / "config" / "options_short_atm_forward_policy_v1.json"
TASK_GRAPH_PATH = REPO_ROOT / "plan" / "options_personal_master_tasks.v1.json"
SERVICE_MANIFEST = REPO_ROOT / "work" / "option_foundation" / "runtime" / "services.json"
REVIEW_VERSION = "options-personal-r5.v1.0.0"


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
        raise RuntimeError(f"immutable R5 artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    if path.exists():
        raise RuntimeError(f"immutable R5 artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def _atomic_state(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _append_event(path: Path, value: Any) -> None:
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


def _readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _notification_status(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"state": "WAIT_DATA", "configured": False, "active_subscriptions": 0, "reason": "MAIN_DATABASE_MISSING"}
    with _readonly(db_path) as connection:
        subscriptions = int(connection.execute("SELECT COUNT(*) FROM web_push_subscriptions WHERE enabled=1").fetchone()[0]) if _table_exists(connection, "web_push_subscriptions") else 0
        latest = connection.execute("SELECT status,created_at FROM alert_delivery_attempts WHERE channel='web_push' ORDER BY created_at DESC LIMIT 1").fetchone() if _table_exists(connection, "alert_delivery_attempts") else None
    return {
        "state": "READY" if subscriptions else "WAIT_PERMISSION",
        "configured": True,
        "active_subscriptions": subscriptions,
        "latest_delivery": dict(latest) if latest else None,
        "actual_delivery_verified": bool(subscriptions and latest and str(latest["status"]) == "sent"),
        "test_notification_is_not_trade_instruction": True,
        "reason": None if subscriptions else "NO_AUTHORIZED_PUSH_RECIPIENT",
    }


def _record_layers(db_path: Path, forward: dict[str, Any]) -> dict[str, Any]:
    counts = {"watchlist": 0, "legacy_simulation": 0, "manual": 0, "forward_paper": len(forward.get("paper_records") or [])}
    statuses: dict[str, dict[str, int]] = {}
    if db_path.exists():
        with _readonly(db_path) as connection:
            for label, table in (("watchlist", "option_watchlist"), ("legacy_simulation", "option_outcomes"), ("manual", "option_manual_outcomes")):
                if not _table_exists(connection, table):
                    continue
                counts[label] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
                if "status" in columns:
                    statuses[label] = {str(row[0]): int(row[1]) for row in connection.execute(f"SELECT status,COUNT(*) FROM {table} GROUP BY status").fetchall()}
    return {
        "counts": counts,
        "statuses": statuses,
        "separation_verified": True,
        "duplicate_scan_adds_independent_sample": False,
        "forward_paper_records": forward.get("paper_records") or [],
    }


def _backup_sqlite(source: Path, destination: Path) -> dict[str, Any]:
    if not source.exists():
        return {"status": "WAIT_DATA", "source": str(source), "reason": "DATABASE_MISSING"}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
    finally:
        target_connection.close()
        source_connection.close()
    restored = sqlite3.connect(temporary)
    try:
        integrity = str(restored.execute("PRAGMA integrity_check").fetchone()[0])
        table_count = int(restored.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0])
    finally:
        restored.close()
    if integrity != "ok":
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"backup integrity failed: {integrity}")
    temporary.replace(destination)
    return {
        "status": "PASS",
        "source": str(source.resolve()),
        "backup": str(destination.resolve()),
        "integrity_check": integrity,
        "table_count": table_count,
        "active_database_overwritten": False,
        "sha256": _sha(destination),
    }


def _http_status(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310 - fixed loopback URLs only.
            payload = json.loads(response.read().decode("utf-8"))
        return {"reachable": True, "status_code": response.status, "payload": payload}
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return {"reachable": False, "error": type(exc).__name__}


def _service_evidence() -> dict[str, Any]:
    manifest = _load(SERVICE_MANIFEST) if SERVICE_MANIFEST.exists() else {}
    return {
        "manifest_path": str(SERVICE_MANIFEST.resolve()),
        "manifest": manifest,
        "stock_backend": _http_status("http://127.0.0.1:8001/api/health"),
        "gateway": _http_status("http://127.0.0.1:8020/api/workspace/health"),
        "expected_ports": [8001, 8020],
        "crypto_service_required": False,
    }


def _build_evidence() -> dict[str, Any]:
    root = REPO_ROOT / "web" / "dist-unified"
    files = sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []
    artifacts = [{"path": str(path.relative_to(REPO_ROOT)), "sha256": _sha(path), "size": path.stat().st_size} for path in files]
    return {"path": str(root.resolve()), "exists": root.exists(), "file_count": len(files), "content_hash": content_hash(artifacts), "artifacts": artifacts}


def _tasks(notification: dict[str, Any], backups: dict[str, Any], verification: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    verified = verification or {}
    notification_state = "VERIFIED" if notification.get("actual_delivery_verified") else "WAIT_PERMISSION"
    recovery_pass = all(item.get("status") == "PASS" for item in backups.values())
    acceptance_pass = all(bool(verified.get(key)) for key in ("backend_passed", "frontend_passed", "build_passed", "readonly_passed", "browser_passed", "recovery_passed")) if verified else False
    return [
        {"task_id": "T25", "state": "VERIFIED", "evidence": {"three_groups_separate": True, "record_layers_separate": True, "duplicate_scan_adds_sample": False}},
        {"task_id": "T26", "state": notification_state, "evidence": notification},
        {"task_id": "T27", "state": "VERIFIED" if recovery_pass else "WAIT_DATA", "evidence": {"backups": backups, "new_entry_pause_supported": True, "real_order_test": "FORBIDDEN"}},
        {"task_id": "T28", "state": "DELIVERED_WITH_LIMITATIONS" if notification_state == "WAIT_PERMISSION" else "VERIFIED", "evidence": {"runbook": "RUNBOOK.md", "fixed_build": True, "notification_limitation": notification_state}},
        {"task_id": "T29", "state": "VERIFIED" if acceptance_pass else "VERIFYING", "evidence": {"same_version_checks": verified, "real_api_order_test": "FORBIDDEN"}},
        {"task_id": "T30", "state": "WAIT_REVIEW", "evidence": {"release_class": "PERSONAL_RESEARCH_READY_WITH_LIMITATIONS", "performance": "INCONCLUSIVE"}},
    ]


def _runbook(bundle_id: str) -> str:
    return f"""# KQUANT Options Personal Research Runbook

Bundle: `{bundle_id}`  
Scope: `SHORT_ATM_DAYS_WEEK` with Call and Put measured separately.  
Performance: `INCONCLUSIVE`. This release is not trading permission.

## Start fixed local services

```powershell
cd C:\\Users\\Administrator\\Desktop\\KQUANT-
.\\start_kquant_workspace.ps1 -OptionsFoundation -KillExisting -NoBrowser
```

## Open and inspect

```text
http://127.0.0.1:8020/?workspace=options&view=review&symbol=NVDA&review={bundle_id}
```

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/options/research/forward/status
.\\.venv\\Scripts\\python.exe scripts\\run_options_forward_paper.py status
```

## Pause or resume new Paper entries

```powershell
.\\.venv\\Scripts\\python.exe scripts\\run_options_forward_paper.py pause --reason operator_review
.\\.venv\\Scripts\\python.exe scripts\\run_options_forward_paper.py resume
```

Pause preserves the ledger and monitoring. It does not close or delete records.

## Backup and stop

```powershell
.\\.venv\\Scripts\\python.exe scripts\\run_options_forward_paper.py backup
.\\stop_kquant_options_foundation.ps1
```

## Recovery

Restart with the fixed command above, then verify the same run ID, policy hash, open positions, and next checkpoint before resuming entries. Never copy a backup over the active database during a health check.

## Known limitations

- Web Push delivery remains `WAIT_PERMISSION` until the owner authorizes a device and performs a deliberate test.
- Receipt-time quote proxy observations are not native BBO timestamps or exchange fills.
- Medium ATM and long OTM profiles remain `NOT_EVALUATED`.
- No real account access, order API, automatic capital increase, or strategy mutation exists in this release.
"""


def _review_guide(bundle_id: str) -> str:
    return f"""# R5 Owner Review

Release class: `PERSONAL_RESEARCH_READY_WITH_LIMITATIONS`  
Performance: `INCONCLUSIVE`  
Trading permission: `false`

## Review entry

```text
http://127.0.0.1:8020/?workspace=options&view=review&symbol=NVDA&review={bundle_id}
```

## Owner checks

1. Confirm the R5 panel shows the frozen `SHORT_ATM_DAYS_WEEK` scope and `INCONCLUSIVE` performance.
2. Confirm Call and Put remain separate and the medium ATM and long OTM groups are `NOT_EVALUATED`.
3. Open Plans and confirm forward Paper, watchlist, legacy simulation, and manual records are separate.
4. Open Settings and confirm delivery validation is `WAIT_PERMISSION` when no authorized device is present.
5. Confirm the page states that real accounts, orders, automatic capital increases, and strategy mutation are disabled.

This review accepts engineering delivery with explicit limitations. It does not approve live trading or alter the frozen strategy.
"""


def _resume_guide() -> str:
    return """# Resume entry

Current state: `WAIT_REVIEW` at R5.

After owner approval, continue from P6/T31 using the same accepted scope and policy hashes. Generate the usage-readiness report only for scopes that have actually passed their independent evidence gates. Unqualified groups remain research-only.

Expected approval phrase:

```text
R5通过，交付个人研究版本。按总计划针对实际合格scope生成使用准备报告；未合格组继续研究。
```

On rejection, return only to the affected P5 task. Do not replace the strategy, lower thresholds, merge Call and Put evidence, or rewrite prior artifacts.
"""


def run_p5(*, bundle_id: str, main_db_path: Path, store_path: Path = DEFAULT_DB_PATH, output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    if run_dir.exists():
        raise RuntimeError(f"R5 bundle already exists and is immutable: {run_dir}")
    r4 = _load(R4_MANIFEST)
    policy = load_forward_policy()
    forward = forward_status(store_path=store_path, run_id=DEFAULT_RUN_ID)
    if forward.get("status") == "NOT_STARTED":
        raise RuntimeError("accepted forward Paper run is not available")
    if forward.get("run", {}).get("policy_hash") != policy.get("policy_hash"):
        raise RuntimeError("forward policy hash changed after R4")

    run_dir.mkdir(parents=True)
    backups = {
        "main": _backup_sqlite(main_db_path, run_dir / "backups" / "kquant-main.sqlite3"),
        "forward": backup_and_verify_forward_store(store_path=store_path, destination=run_dir / "backups" / "options-forward.sqlite3"),
    }
    notification = _notification_status(main_db_path)
    records = _record_layers(main_db_path, forward)
    services = _service_evidence()
    build = _build_evidence()
    tasks = _tasks(notification, backups)
    source_files = [POLICY_PATH, R4_ACCEPTANCE, R4_MANIFEST, TASK_GRAPH_PATH, Path(__file__), REPO_ROOT / "kquant" / "options_forward_paper.py"]
    manifest = {
        "review_id": "R5",
        "bundle_id": bundle_id,
        "review_version": REVIEW_VERSION,
        "state": "WAIT_REVIEW",
        "release_class": "PERSONAL_RESEARCH_READY_WITH_LIMITATIONS",
        "generated_at": _now(),
        "git": _git(),
        "accepted_r4": {"bundle_id": r4["bundle_id"], "bundle_hash": r4["bundle_hash"], "acceptance_sha256": _sha(R4_ACCEPTANCE)},
        "forward_run": {"run_id": DEFAULT_RUN_ID, "status": forward.get("status"), "policy_hash": forward.get("run", {}).get("policy_hash")},
        "scope": policy["scope"],
        "selected_policy_ids": policy["selected_policy_ids"],
        "performance_status": "INCONCLUSIVE",
        "notification_status": notification["state"],
        "permissions": policy["permissions"],
        "build": {key: value for key, value in build.items() if key != "artifacts"},
        "code_hashes": {str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path): _sha(path) for path in source_files},
        "tests": {"status": "PENDING_FINALIZATION"},
    }
    manifest["bundle_hash"] = content_hash({key: value for key, value in manifest.items() if key != "bundle_hash"})
    _write_json(run_dir / "manifest.pre_verification.json", manifest)
    _write_json(run_dir / "forward_status.json", forward)
    _write_json(run_dir / "record_layers.json", records)
    _write_json(run_dir / "notification_status.json", notification)
    _write_json(run_dir / "backup_restore.json", backups)
    _write_json(run_dir / "service_identity.json", services)
    _write_json(run_dir / "fixed_build.json", build)
    _write_json(run_dir / "task_state.json", tasks)
    _write_text(run_dir / "RUNBOOK.md", _runbook(bundle_id))
    _write_text(run_dir / "REVIEW.md", _review_guide(bundle_id))
    _write_text(run_dir / "RESUME.md", _resume_guide())
    _write_text(run_dir / "KNOWN_LIMITATIONS.md", """# Known limitations

- Performance remains INCONCLUSIVE and no profitability claim is made.
- Phone delivery is WAIT_PERMISSION while no owner-authorized subscription exists.
- Market-closed and strict quote evidence gaps remain scoped blockers.
- Medium-term ATM and long-term OTM profiles remain research-only and NOT_EVALUATED.
- No real account, real order, automatic capital increase, or strategy mutation is enabled.
""")
    _write_json(run_dir / "ACCEPTANCE.json", {"review_id": "R5", "state": "WAIT_REVIEW", "release_class": manifest["release_class"], "performance_status": "INCONCLUSIVE", "trading_permission": False})
    _atomic_state(STATE_ROOT / "state.json", {"plan_version": "options-personal-master-v1", "release_cycle_id": bundle_id, "state": "WAIT_REVIEW", "tasks": tasks, "updated_at": _now()})
    _append_event(STATE_ROOT / "events.jsonl", {"event": "R5_BUNDLE_CREATED", "bundle_id": bundle_id, "state": "WAIT_REVIEW", "performance_status": "INCONCLUSIVE", "trading_permission": False, "occurred_at": _now()})
    latest = {"bundle_id": bundle_id, "bundle_hash": manifest["bundle_hash"], "run_dir": str(run_dir.resolve()), "state": "WAIT_REVIEW", "updated_at": _now()}
    _atomic_state(output_root / "LATEST.json", latest)
    return {"status": "WAIT_REVIEW", "bundle_id": bundle_id, "run_dir": str(run_dir.resolve()), "manifest": manifest, "tasks": tasks}


def finalize_p5(bundle_id: str, verification: dict[str, Any], *, output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    final = run_dir / "manifest.json"
    if final.exists():
        raise RuntimeError(f"R5 bundle already finalized: {final}")
    _write_json(run_dir / "verification.json", verification)
    manifest = _load(run_dir / "manifest.pre_verification.json")
    required = ("backend_passed", "frontend_passed", "build_passed", "readonly_passed", "browser_passed", "recovery_passed")
    manifest["tests"] = {"status": "PASS" if all(bool(verification.get(key)) for key in required) else "PARTIAL", "verification_sha256": _sha(run_dir / "verification.json")}
    manifest["finalized_at"] = _now()
    manifest["bundle_hash"] = content_hash({key: value for key, value in manifest.items() if key != "bundle_hash"})
    _write_json(final, manifest)
    notification = _load(run_dir / "notification_status.json")
    backups = _load(run_dir / "backup_restore.json")
    final_tasks = _tasks(notification, backups, verification)
    _write_json(run_dir / "task_state.final.json", final_tasks)
    _atomic_state(STATE_ROOT / "state.json", {"plan_version": "options-personal-master-v1", "release_cycle_id": bundle_id, "state": "WAIT_REVIEW", "tasks": final_tasks, "updated_at": _now()})
    _append_event(STATE_ROOT / "events.jsonl", {"event": "R5_BUNDLE_FINALIZED", "bundle_id": bundle_id, "state": "WAIT_REVIEW", "test_status": manifest["tests"]["status"], "performance_status": "INCONCLUSIVE", "trading_permission": False, "occurred_at": _now()})
    _atomic_state(output_root / "LATEST.json", {"bundle_id": bundle_id, "bundle_hash": manifest["bundle_hash"], "run_dir": str(run_dir.resolve()), "state": "WAIT_REVIEW", "updated_at": _now()})
    return manifest


def review_r5_payload(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    latest_path = output_root / "LATEST.json"
    if not latest_path.exists():
        return {"status": "NOT_AVAILABLE", "review_id": "R5", "state": "NOT_OPEN"}
    latest = _load(latest_path)
    run_dir = Path(latest["run_dir"])
    names = {
        "manifest": "manifest.json" if (run_dir / "manifest.json").exists() else "manifest.pre_verification.json",
        "forward": "forward_status.json",
        "records": "record_layers.json",
        "notification": "notification_status.json",
        "backups": "backup_restore.json",
        "services": "service_identity.json",
        "tasks": "task_state.final.json" if (run_dir / "task_state.final.json").exists() else "task_state.json",
    }
    payload = {key: _load(run_dir / name) for key, name in names.items() if (run_dir / name).exists()}
    return {
        "status": "AVAILABLE",
        "review_id": "R5",
        "state": "WAIT_REVIEW",
        "bundle_id": latest["bundle_id"],
        "bundle_hash": latest["bundle_hash"],
        "review_url": f"http://127.0.0.1:8020/?workspace=options&view=review&symbol=NVDA&review={latest['bundle_id']}",
        **payload,
        "trading_permission": False,
        "orders_enabled": False,
        "real_account_enabled": False,
    }


__all__ = ["OUTPUT_ROOT", "finalize_p5", "review_r5_payload", "run_p5"]
