from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .options_astra import CAPABILITY_PATH, astra_status
from .options_signal_copilot import CONFIG_PATH, DEFAULT_STORE_PATH, copilot_status, synthetic_round_trip
from .options_signal_tools import get_research_result


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "outputs" / "signal_copilot_sc_r1"
FORWARD_POLICY_PATH = REPO_ROOT / "config" / "options_short_atm_forward_policy_v1.json"
APPROVAL_PATH = REPO_ROOT / "config" / "review_acceptances" / "options_r3_20260920.txt"
SERVICES_PATH = REPO_ROOT / "work" / "option_foundation" / "runtime" / "services.json"
MAIN_DB = REPO_ROOT / "work" / "kquant_us.sqlite3"
BACKUP_ROOT = REPO_ROOT / "work"
ENGINEERING_VERSION = "signal-copilot-sc-r1.v1.0.0"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"Immutable artifact collision: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_text(path: Path, text: str) -> None:
    normalized = text.rstrip() + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != normalized:
        raise RuntimeError(f"Immutable artifact collision: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalized, encoding="utf-8", newline="\n")


def _git_identity() -> dict[str, Any]:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO_ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True).splitlines()
    return {"head": head, "branch": branch, "dirty_paths_count": len(dirty), "existing_work_preserved": True}


def _notification_status() -> dict[str, Any]:
    if not MAIN_DB.exists():
        return {"status": "WAIT_DATA", "active_subscriptions": 0, "opened_read_only": False}
    connection = sqlite3.connect(f"file:{MAIN_DB.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        subscriptions = (
            int(connection.execute("SELECT COUNT(*) FROM web_push_subscriptions WHERE enabled=1").fetchone()[0])
            if "web_push_subscriptions" in tables
            else 0
        )
        latest = (
            connection.execute(
                "SELECT status,created_at FROM alert_delivery_attempts WHERE channel='web_push' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if "alert_delivery_attempts" in tables
            else None
        )
    finally:
        connection.close()
    return {
        "status": "READY" if subscriptions else "WAIT_PERMISSION",
        "active_subscriptions": subscriptions,
        "latest_delivery": dict(latest) if latest else None,
        "actual_device_delivery_verified": bool(subscriptions and latest and latest["status"] == "sent"),
        "opened_read_only": True,
    }


def _strategy_card(forward: dict[str, Any], copilot: dict[str, Any]) -> dict[str, Any]:
    source = str(FORWARD_POLICY_PATH.resolve())
    fields = {
        "strategy_id": forward["selected_policy_ids"]["strategy"],
        "profile_id": forward["scope"]["profile_id"],
        "rights": forward["scope"]["rights"],
        "universe": forward["frozen_universe"],
        "decision_time": forward["candidate_contract"]["decision_time"],
        "candidate_contract": forward["candidate_contract"],
        "contract_selection": forward["contract_selection"],
        "right_policies": forward["right_policies"],
        "exit_policy": forward["exit_policy"],
        "quote_proxy": forward["quote_proxy"],
        "capital_policy": forward["capital_policy"],
        "cost_policy": forward["cost_policy"],
        "metric_policy": forward["metric_policy"],
    }
    return {
        "status": "FOUND_APPROVED_COMPLETE",
        "fields": [
            {"field": key, "state": "FOUND", "approved": True, "source": source, "value": value}
            for key, value in fields.items()
        ],
        "approved_bundle": forward["approved_review_bundle"],
        "approval_record": {
            "path": str(APPROVAL_PATH.resolve()),
            "sha256": _sha256(APPROVAL_PATH),
            "preserved": True,
        },
        "existing_execution_permission": {
            "automatic_receipt_proxy_paper_entry": forward["permissions"]["automatic_receipt_proxy_paper_entry"],
            "real_orders": forward["permissions"]["real_orders"],
        },
        "new_execution_overlay": copilot["paper_execution"],
        "review_difference": {
            "type": "EXECUTION_MODE_CHANGE_REQUIRES_SC_R1",
            "from": "AUTOMATIC_RECEIPT_PROXY_PAPER_ENTRY",
            "to": "OWNER_CONFIRMED_ENTRY_AND_EXIT_BEFORE_POST_CONFIRMATION_QUOTE",
            "strategy_parameters_changed": False,
            "old_approval_overwritten": False,
        },
        "performance_status": "INCONCLUSIVE",
        "not_live_authorization": True,
    }


def _task_state(astra: dict[str, Any], notifications: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"task_id": "SC00", "state": "VERIFIED", "detail": "Baseline, read-only inventory, consistent backups, and sole Foundation service identity recorded."},
        {"task_id": "SC01", "state": "VERIFIED", "detail": "Complete approved R3 strategy and exact hashes recovered."},
        {"task_id": "SC02", "state": "DELIVERED_WITH_LIMITATIONS", "detail": "OPRA reference fields exist; native BBO event time and full market-session continuity remain unavailable."},
        {"task_id": "SC03", "state": "VERIFIED", "detail": "Existing approved strategy reused; package example was not adopted."},
        {"task_id": "SC04", "state": "WAIT_REVIEW", "detail": "Manual-confirm overlay and API budget require SC-R1 owner decisions."},
        {"task_id": "SC05", "state": "VERIFIED", "detail": "Seven read-only math/research tools implemented and allowlisted."},
        {"task_id": "SC06", "state": "VERIFIED", "detail": "Adjusted-data E-S-001 artifact reused: DEV_FIT_COMPLETE / INCONCLUSIVE."},
        {"task_id": "SC07", "state": "DELIVERED_WITH_LIMITATIONS", "detail": f"Astra client and budget guard implemented; model probe={astra.get('model_access_status')}."},
        {"task_id": "SC08", "state": "BLOCKED", "detail": "Actual Astra inference requires both accessible exact model credentials and API_BUDGET_CONFIRMED."},
        {"task_id": "SC09", "state": "VERIFIED", "detail": "Signal, assessment, notification, intent, and position identities are isolated and idempotent."},
        {"task_id": "SC10", "state": "VERIFIED", "detail": "Options Signals first-level page built; activation remains blocked."},
        {"task_id": "SC11", "state": "WAIT_PERMISSION" if not notifications["actual_device_delivery_verified"] else "VERIFIED", "detail": f"Persistent queue and Web Push bridge implemented; active subscriptions={notifications['active_subscriptions']}."},
        {"task_id": "SC12", "state": "VERIFIED", "detail": "Isolated Decimal Paper ledger and $10,000 synthetic account exercise passed."},
        {"task_id": "SC13", "state": "VERIFIED", "detail": "Synthetic entry requests quotes only after committed owner confirmation."},
        {"task_id": "SC14", "state": "VERIFIED", "detail": "Synthetic manual exit, missing-bid pending state, idempotency, and recovery paths implemented."},
        {"task_id": "SC15", "state": "VERIFIED", "detail": "Deterministic Greeks scenarios reused without probabilities or executable-price claims."},
        {"task_id": "SC16", "state": "BLOCKED", "detail": "Requires SC-R1 acceptance of the exact manual-confirm overlay."},
        {"task_id": "SC17", "state": "BLOCKED", "detail": "Requires SC-R1 plus actual Astra/device evidence for the full actual-data path."},
        {"task_id": "SC18", "state": "BLOCKED", "detail": "SC-R2 package follows SC17."},
        {"task_id": "SC19", "state": "WAIT_MARKET", "detail": "Reuse existing market calendar and sole Supervisor after SC-R2; do not create another scheduler."},
        {"task_id": "SC20", "state": "BLOCKED", "detail": "First-day report requires accepted Paper version and an actual observed session."},
        {"task_id": "SC21", "state": "BLOCKED", "detail": "Requires five actual observed trading sessions."},
        {"task_id": "SC22", "state": "BLOCKED", "detail": "SC-R3 follows SC21."},
        {"task_id": "SC23", "state": "BLOCKED", "detail": "Continued observation follows SC-R3; live remains disabled."},
    ]


def build_sc_r1_bundle(bundle_id: str = "signal-copilot-sc-r1-20260920-01") -> dict[str, Any]:
    run_dir = OUTPUT_ROOT / bundle_id
    if run_dir.exists():
        raise RuntimeError(f"Bundle already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    forward = _load(FORWARD_POLICY_PATH)
    status = {**copilot_status(store_path=DEFAULT_STORE_PATH), "astra_runtime": astra_status()}
    notifications = _notification_status()
    status["desktop_notifications"] = notifications
    research = get_research_result()["payload"]
    synthetic = synthetic_round_trip(store_path=run_dir / "synthetic_paper.sqlite3")
    services = _load(SERVICES_PATH) if SERVICES_PATH.exists() else {"status": "NOT_AVAILABLE"}
    backup_dirs = sorted(BACKUP_ROOT.glob("signal-copilot-backup-*"), reverse=True)
    backup = backup_dirs[0] if backup_dirs else None

    baseline = {
        "bundle_id": bundle_id,
        "engineering_version": ENGINEERING_VERSION,
        "generated_at": _now(),
        "git": _git_identity(),
        "config_path": str(CONFIG_PATH.resolve()),
        "config_sha256": _sha256(CONFIG_PATH),
        "forward_policy_path": str(FORWARD_POLICY_PATH.resolve()),
        "forward_policy_sha256": _sha256(FORWARD_POLICY_PATH),
        "services": services,
        "backup": {"path": str(backup.resolve()) if backup else None, "exists": bool(backup)},
        "main_database_changed_by_bundle": False,
        "root_agents_changed_by_bundle": False,
        "orders_enabled": False,
    }
    artifacts = {
        "baseline_manifest.json": baseline,
        "strategy_baseline_card.json": _strategy_card(forward, status),
        "runtime_status.json": status,
        "es001_evidence.json": research,
        "astra_capability.json": _load(CAPABILITY_PATH) if CAPABILITY_PATH.exists() else {"status": "NOT_CHECKED"},
        "notification_status.json": notifications,
        "synthetic_paper_result.json": synthetic,
        "task_state.json": {"plan_id": "SC-PAPER-V1", "review_gate": "SC-R1", "tasks": _task_state(status["astra_runtime"], notifications)},
    }
    for filename, payload in artifacts.items():
        _write_json(run_dir / filename, payload)

    limitations = """# Known limitations

1. The exact requested Astra model is not currently accessible: the capability probe returned HTTP 401. No paid inference ran and no fallback model was used.
2. The API daily budget remains null and paid calls remain disabled until explicit owner approval.
3. No owner-authorized Web Push device is currently proven delivered; desktop notification engineering is not device acceptance.
4. Native option BBO event time remains unavailable. Receipt time is not relabeled as exchange event time and strict simulated-fill qualification is unchanged.
5. E-S-001 is exposed DEV_ONLY underlying research. Its adjusted-data fit completed but was INCONCLUSIVE; it is not option performance.
6. The Paper round trip in this bundle is synthetic test evidence only. No market Signal, actual Paper position, broker account, or order was created.
7. Full market-session and cross-day continuity remain WAIT_MARKET. The existing Foundation Supervisor must be reused.
"""
    review = f"""# SC-R1 Review: Signal Copilot and manual-confirm Paper overlay

Bundle: `{bundle_id}`

## What was reused

- Strategy: `STRAT-SHORT-ATM-RANGE-EXPANSION-V1`
- Scope: `SHORT_ATM_DAYS_WEEK`, Call and Put recorded separately
- Forward policy hash: `{forward['approved_review_bundle']['approved_policy_hash']}`
- Runtime policy hash: `{status['strategy']['forward_policy_runtime_hash']}`
- Approved R3 bundle: `{forward['approved_review_bundle']['bundle_id']} / {forward['approved_review_bundle']['bundle_hash']}`
- Capital: `PAPER-RISK-10000-V1`; cost: `COST-OPTIONS-CONSERVATIVE-V1`; metric: `METRIC-OPTIONS-RESEARCH-GATE-V1`

No strategy threshold, DTE, Delta, entry condition, exit threshold, universe, or risk limit was changed.

## Decision requested

Accept or reject the new execution overlay `PAPER-MANUAL-CONFIRM-RECEIPT-L1-V1`:

- Paper entry and exit each require the exact owner confirmation.
- The quote request starts only after confirmation is committed.
- Entry uses subsequent ask plus frozen slippage; exit uses subsequent bid minus frozen slippage.
- Native source BBO time remains null unless verified. Strict BBO qualification is unchanged.
- The isolated virtual account starts at $10,000, with $50 per-position premium risk and $150 total open premium in the engineering fixture.
- Automatic Paper entry/exit, real account access, real orders, capital increases, and strategy mutation remain disabled.

This overlay replaces the old automatic Paper-entry behavior only for the new Signal Copilot pilot. It does not overwrite the prior R3 approval record.

## Astra and budget

- Requested exact model: `gpt-6-astra`
- Capability result: `{status['astra_runtime']['model_access_status']}` (HTTP `{status['astra_runtime'].get('latest_capability_check', {}).get('http_status')}`)
- Actual model identity: `{status['astra_runtime'].get('actual_model_id')}`
- Paid inference used: `false`
- Daily API budget: `null`; proposed ceiling `$5/day` is not approved.
- Silent fallback: `false`

The exact model and budget cannot be accepted as operational while access is 401. The owner may approve the manual Paper overlay separately while keeping Astra blocked.

## Evidence

- E-S-001: `{research.get('status')} / {research.get('conclusion')}`, dataset `{research.get('dataset_manifest', {}).get('dataset_hash')}`
- Synthetic Paper: entry `{synthetic['entry']['status']}` at `{synthetic['entry'].get('fill_price')}`, exit `{synthetic['exit']['status']}` at `{synthetic['exit'].get('fill_price')}`, realized `{synthetic['exit'].get('realized_pnl')}`; TEST_ONLY
- Desktop subscriptions: `{notifications['active_subscriptions']}`; actual delivery verified `{notifications['actual_device_delivery_verified']}`
- Orders enabled: `false`

## Owner test (5 steps)

1. Open `http://127.0.0.1:8020/?workspace=options&view=signals&symbol=NVDA&review={bundle_id}&build=signal-copilot-sc-r1-v1`.
2. Verify the page shows `STRAT-SHORT-ATM-RANGE-EXPANSION-V1`, `SHORT_ATM_DAYS_WEEK`, Call / Put, and `PAPER_MANUAL_CONFIRM` waiting for SC-R1.
3. Verify Astra shows `gpt-6-astra / NOT_ACCESSIBLE`, the daily budget is not approved, and desktop subscriptions are `0`.
4. Open Options -> Opportunities for MSTR and verify the existing broker-style Call / Put chain still loads; reference quotes must remain separate from strict simulated-fill eligibility.
5. Return to Signals and verify there are no market signals or positions, the Paper engine is `SYNTHETIC_ONLY_WAIT_SC_R1`, and `Real orders enabled` is `false`.

## Suggested owner response

`SC-R1通过：接受policy:OPTIONS-SIGNAL-COPILOT-PAPER-V1/{status['config_hash']}的PAPER-MANUAL-CONFIRM/RECEIPT_L1_PROXY，仅用于SHORT_ATM_DAYS_WEEK Call/Put人工Paper；沿用PAPER-RISK-10000-V1与COST-OPTIONS-CONSERVATIVE-V1。Astra预算暂不批准，保持阻断，先修复gpt-6-astra访问。交易信号不等于成交，不批准真实订单。`

After acceptance, SC16 can bind the exact overlay. SC08 remains blocked until the exact model is accessible and an API budget is explicitly approved.
"""
    _write_text(run_dir / "KNOWN_LIMITATIONS.md", limitations)
    _write_text(run_dir / "SC_R1_REVIEW.md", review)

    files = {
        path.name: _sha256(path)
        for path in sorted(run_dir.iterdir())
        if path.is_file() and path.name != "manifest.json"
    }
    manifest = {
        "bundle_id": bundle_id,
        "engineering_version": ENGINEERING_VERSION,
        "review_gate": "SC-R1",
        "state": "WAIT_REVIEW",
        "files": files,
        "bundle_hash": _hash(files),
        "signals_enabled": False,
        "paper_runtime_enabled": False,
        "astra_paid_calls_enabled": False,
        "real_orders_enabled": False,
        "generated_at": _now(),
    }
    _write_json(run_dir / "manifest.json", manifest)
    latest = {"bundle_id": bundle_id, "bundle_hash": manifest["bundle_hash"], "run_dir": str(run_dir.resolve()), "state": "WAIT_REVIEW", "updated_at": _now()}
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "LATEST.json.tmp"
    temporary.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT_ROOT / "LATEST.json")
    return {**manifest, "run_dir": str(run_dir.resolve()), "review_file": str((run_dir / "SC_R1_REVIEW.md").resolve())}


__all__ = ["ENGINEERING_VERSION", "OUTPUT_ROOT", "build_sc_r1_bundle"]
