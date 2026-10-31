from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .options_research_features import content_hash


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "outputs" / "options_review_r2"
REVIEW_DB = REPO_ROOT / "work" / "options_review_r2" / "options_review_r2.sqlite3"
R1_OUTPUT_ROOT = REPO_ROOT / "outputs" / "options_review_r1"
PROFILE_PATH = REPO_ROOT / "config" / "options_research_profiles_v1.json"
STRATEGY_PATH = REPO_ROOT / "config" / "options_strategy_proposals_r2_v1.json"
PAPER_PATH = REPO_ROOT / "config" / "options_paper_policy_proposals_r2_v1.json"
METRIC_PATH = REPO_ROOT / "config" / "options_metric_policy_proposals_r2_v1.json"
MASTER_PLAN_PATH = REPO_ROOT / "docs" / "KQUANT_OPTIONS_MASTER_PLAN_REVIEW_LED_V1.md"
OWNER_PLAYBOOK_PATH = REPO_ROOT / "docs" / "OWNER_REVIEW_PLAYBOOK.md"
TASK_GRAPH_PATH = REPO_ROOT / "plan" / "options_personal_master_tasks.v1.json"

REVIEW_VERSION = "options-personal-r2.v1.0.0"
PROFILE_IDS = {
    "SHORT_ATM_DAYS_WEEK",
    "MEDIUM_ATM_WEEKS_MONTHS",
    "LONG_OTM_MONTHS_YEAR",
}
PENDING_PROFILE_FIELDS = (
    "holding_period_policy",
    "expiry_selection_policy",
    "moneyness_selection_policy",
    "delta_range",
    "liquidity_selection_policy",
    "event_risk_policy",
    "factor_policy",
    "entry_policy",
    "exit_policy",
    "position_sizing_policy",
    "model_artifact_id",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS review_meta (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_acceptances (
  bundle_id TEXT PRIMARY KEY,
  prior_review_id TEXT NOT NULL,
  prior_bundle_id TEXT NOT NULL,
  acceptance_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposal_catalogs (
  bundle_id TEXT NOT NULL,
  catalog_kind TEXT NOT NULL,
  catalog_id TEXT NOT NULL,
  catalog_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  PRIMARY KEY(bundle_id, catalog_kind)
);
CREATE TABLE IF NOT EXISTS review_task_state (
  bundle_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  state TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(bundle_id, task_id)
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


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


def initialize_review_store(path: Path = REVIEW_DB) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT OR REPLACE INTO review_meta VALUES (?,?,?)",
            ("schema_version", json_text(1), utc_now()),
        )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    return {"path": str(path.resolve()), "schema_version": 1, "integrity_check": integrity}


def _git_identity() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.check_output(
            ["git", *args], cwd=REPO_ROOT, text=True, encoding="utf-8", errors="replace"
        ).strip()

    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "status_hash": hashlib.sha256(run("status", "--short").encode("utf-8")).hexdigest(),
    }


def _latest_r1(expected_bundle_id: str | None = None) -> tuple[Path, dict[str, Any]]:
    latest_path = R1_OUTPUT_ROOT / "LATEST.json"
    if not latest_path.exists():
        raise RuntimeError("R1 review bundle is unavailable")
    latest = load_json(latest_path)
    bundle_id = str(latest.get("bundle_id") or "")
    if expected_bundle_id and bundle_id != expected_bundle_id:
        raise RuntimeError(f"R1 bundle mismatch: expected {expected_bundle_id}, found {bundle_id}")
    run_dir = Path(latest["run_dir"])
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("R1 bundle is not finalized")
    manifest = load_json(manifest_path)
    if manifest.get("tests", {}).get("status") != "PASS":
        raise RuntimeError("R1 verification did not pass")
    if manifest.get("state") != "WAIT_REVIEW":
        raise RuntimeError("R1 was not presented at WAIT_REVIEW")
    return run_dir, manifest


def _profile_boundary(r1_manifest: dict[str, Any]) -> dict[str, Any]:
    payload = load_json(PROFILE_PATH)
    profiles = []
    for profile in payload.get("profiles", []):
        profiles.append(
            {
                "profile_id": profile.get("profile_id"),
                "non_null_policy_fields": [
                    field for field in PENDING_PROFILE_FIELDS if profile.get(field) is not None
                ],
                "signal_generation_enabled": bool(profile.get("signal_generation_enabled")),
                "trade_simulation_enabled": bool(profile.get("trade_simulation_enabled")),
                "automatic_order_enabled": bool(profile.get("automatic_order_enabled")),
            }
        )
    current_hash = sha256_file(PROFILE_PATH)
    r1_hash = r1_manifest.get("profile_boundary", {}).get("config_sha256")
    preserved = (
        current_hash == r1_hash
        and {item["profile_id"] for item in profiles} == PROFILE_IDS
        and all(
            not item["non_null_policy_fields"]
            and not item["signal_generation_enabled"]
            and not item["trade_simulation_enabled"]
            and not item["automatic_order_enabled"]
            for item in profiles
        )
    )
    return {
        "path": str(PROFILE_PATH.resolve()),
        "config_sha256": current_hash,
        "r1_config_sha256": r1_hash,
        "profiles": profiles,
        "preserved": preserved,
    }


def validate_proposal_catalogs(
    strategy: dict[str, Any],
    paper: dict[str, Any],
    metric: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    proposals = strategy.get("proposals", [])
    execution_policies = paper.get("execution_policies", [])
    proposal_ids = [str(item.get("proposal_id")) for item in proposals]
    policy_ids = [str(item.get("policy_id")) for item in execution_policies]
    policy_ids.extend(
        [
            str(paper.get("capital_policy", {}).get("policy_id")),
            str(paper.get("cost_policy", {}).get("policy_id")),
        ]
    )

    if len(proposals) != 4 or len(set(proposal_ids)) != len(proposal_ids):
        blockers.append("STRATEGY_PROPOSAL_IDENTITY_INVALID")
    if len(execution_policies) != 2 or len(set(policy_ids)) != len(policy_ids):
        blockers.append("PAPER_POLICY_IDENTITY_INVALID")
    if metric.get("policy_id") != "METRIC-OPTIONS-RESEARCH-GATE-V1":
        blockers.append("METRIC_POLICY_IDENTITY_INVALID")

    profile_summary: dict[str, dict[str, Any]] = {}
    required_strategy_keys = {
        "profit_mechanism",
        "rights",
        "entry_policy",
        "exit_policy",
        "contract_selection",
        "liquidity_policy",
        "event_policy",
        "paper_policy_refs",
        "metric_policy_ref",
        "validation_policy",
        "experiment_budget",
        "data_availability",
        "examples",
    }
    for profile_id in PROFILE_IDS:
        rows = [item for item in proposals if item.get("profile_id") == profile_id]
        primary = [item for item in rows if item.get("variant") == "PRIMARY"]
        alternatives = [item for item in rows if item.get("variant") == "ALTERNATIVE"]
        profile_summary[profile_id] = {
            "primary": [item.get("proposal_id") for item in primary],
            "alternatives": [item.get("proposal_id") for item in alternatives],
            "data_status": [item.get("data_availability") for item in rows],
        }
        if len(primary) != 1:
            blockers.append(f"{profile_id}_PRIMARY_COUNT_INVALID")
        if len(alternatives) > 1:
            blockers.append(f"{profile_id}_ALTERNATIVE_COUNT_INVALID")

    for proposal in proposals:
        proposal_id = str(proposal.get("proposal_id"))
        missing = sorted(required_strategy_keys - set(proposal))
        if missing:
            blockers.append(f"{proposal_id}_MISSING_{'_'.join(missing)}")
        if set(proposal.get("rights", [])) != {"CALL", "PUT"}:
            blockers.append(f"{proposal_id}_RIGHTS_INCOMPLETE")
        if proposal.get("status") not in {"PROPOSAL_ONLY", "PROPOSAL_ONLY_DATA_BLOCKED"}:
            blockers.append(f"{proposal_id}_STATUS_NOT_PROPOSAL_ONLY")
        if any(
            bool(proposal.get(field))
            for field in ("signal_generation_enabled", "paper_enabled", "real_orders_enabled")
        ):
            blockers.append(f"{proposal_id}_PERMISSION_ENABLED")
        if proposal.get("metric_policy_ref") != metric.get("policy_id"):
            blockers.append(f"{proposal_id}_METRIC_REFERENCE_INVALID")
        unknown_refs = sorted(set(proposal.get("paper_policy_refs", [])) - set(policy_ids))
        if unknown_refs:
            blockers.append(f"{proposal_id}_UNKNOWN_PAPER_POLICY")
        if not proposal.get("examples"):
            blockers.append(f"{proposal_id}_EXAMPLES_MISSING")

    evidence_classes = {item.get("evidence_class") for item in execution_policies}
    if evidence_classes != {"NATIVE_BBO_TIME_STRICT", "RECEIPT_TIME_QUOTE_PROXY"}:
        blockers.append("EXECUTION_EVIDENCE_CLASSES_INVALID")
    if any(bool(value) for value in paper.get("permissions", {}).values()):
        blockers.append("PAPER_CATALOG_PERMISSION_ENABLED")
    if any(bool(value) for value in metric.get("permissions", {}).values()):
        blockers.append("METRIC_POLICY_PERMISSION_ENABLED")

    thresholds = metric.get("legacy_thresholds_preserved", {})
    expected_thresholds = {
        "minimum_observation_trading_days": 20,
        "minimum_completed_per_claimed_profile_right": 200,
        "net_profit_factor_min": 1.30,
        "net_payoff_min": 1.80,
        "net_expectancy_ci95_lower": ">0",
        "double_cost_profit_factor_min": 1.05,
    }
    if thresholds != expected_thresholds:
        blockers.append("LEGACY_THRESHOLDS_CHANGED")
    if metric.get("unknown_policy") != "UNKNOWN_NEVER_PASSES":
        blockers.append("UNKNOWN_POLICY_CAN_PASS")

    short = next(
        (item for item in proposals if item.get("proposal_id") == "STRAT-SHORT-ATM-RANGE-EXPANSION-V1"),
        {},
    )
    if short.get("source_evidence"):
        warnings.append("PROPOSAL_LEVEL_SOURCE_EVIDENCE_IS_NOT_USED_AS_AN_ACTIVATION_GATE")
    if strategy.get("source_evidence", {}).get("es001_policy") != "DESCRIPTIVE_ONLY_NOT_ENTRY_GATE":
        blockers.append("ES001_WAS_PROMOTED_TO_ENTRY_GATE")

    return {
        "status": "PASS" if not blockers else "FAIL",
        "review_id": "R2",
        "catalog_ids": {
            "strategy": strategy.get("catalog_id"),
            "paper": paper.get("catalog_id"),
            "metric": metric.get("policy_id"),
        },
        "proposal_count": len(proposals),
        "profile_summary": profile_summary,
        "execution_policy_ids": [item.get("policy_id") for item in execution_policies],
        "legacy_thresholds": thresholds,
        "blockers": blockers,
        "warnings": warnings,
        "permissions": {"signals": False, "paper_entries": False, "orders": False},
    }


def activation_preflight(
    strategy: dict[str, Any],
    paper: dict[str, Any],
    metric: dict[str, Any],
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selection = selection or {}
    blockers: list[str] = ["R2_OWNER_DECISION_NOT_RECORDED"]
    proposal = next(
        (item for item in strategy.get("proposals", []) if item.get("proposal_id") == selection.get("strategy_policy_id")),
        None,
    )
    execution = next(
        (item for item in paper.get("execution_policies", []) if item.get("policy_id") == selection.get("paper_execution_policy_id")),
        None,
    )
    scope = selection.get("scope") or {}
    if proposal is None:
        blockers.append("STRATEGY_POLICY_NOT_SELECTED_OR_UNKNOWN")
    if execution is None:
        blockers.append("PAPER_EXECUTION_POLICY_NOT_SELECTED_OR_UNKNOWN")
    if selection.get("metric_policy_id") != metric.get("policy_id"):
        blockers.append("METRIC_POLICY_NOT_SELECTED_OR_UNKNOWN")
    if selection.get("capital_policy_id") != paper.get("capital_policy", {}).get("policy_id"):
        blockers.append("CAPITAL_POLICY_NOT_SELECTED_OR_UNKNOWN")
    if selection.get("cost_policy_id") != paper.get("cost_policy", {}).get("policy_id"):
        blockers.append("COST_POLICY_NOT_SELECTED_OR_UNKNOWN")
    if not scope.get("profile_id") or not scope.get("rights"):
        blockers.append("SCOPE_PROFILE_AND_RIGHTS_REQUIRED")
    if proposal is not None:
        if scope.get("profile_id") != proposal.get("profile_id"):
            blockers.append("SCOPE_PROFILE_MISMATCH")
        invalid_rights = sorted(set(scope.get("rights", [])) - set(proposal.get("rights", [])))
        if invalid_rights:
            blockers.append("SCOPE_RIGHTS_INVALID")
        data_values = set(proposal.get("data_availability", {}).values())
        if "BLOCKED" in data_values or any(str(value).startswith("BLOCKED") for value in data_values):
            blockers.append("SELECTED_STRATEGY_DATA_BLOCKED")
    if execution is not None and execution.get("current_eligibility") == "BLOCKED":
        blockers.append("SELECTED_EXECUTION_POLICY_DATA_BLOCKED")
    return {
        "status": "BLOCKED",
        "activation_allowed": False,
        "selection": selection,
        "blockers": list(dict.fromkeys(blockers)),
        "signals_enabled": False,
        "paper_entries_enabled": False,
        "orders_enabled": False,
        "next_required_review": "R2",
    }


def _store_bundle(
    review_db: Path,
    bundle_id: str,
    acceptance: dict[str, Any],
    catalogs: dict[str, dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> None:
    with sqlite3.connect(review_db) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO review_acceptances VALUES (?,?,?,?,?)",
            (
                bundle_id,
                "R1",
                acceptance["prior_bundle_id"],
                json_text(acceptance),
                utc_now(),
            ),
        )
        for kind, payload in catalogs.items():
            catalog_id = str(payload.get("catalog_id") or payload.get("policy_id"))
            connection.execute(
                "INSERT OR REPLACE INTO proposal_catalogs VALUES (?,?,?,?,?,?)",
                (bundle_id, kind, catalog_id, content_hash(payload), json_text(payload), utc_now()),
            )
        for task in tasks:
            connection.execute(
                "INSERT OR REPLACE INTO review_task_state VALUES (?,?,?,?,?)",
                (bundle_id, task["task_id"], task["state"], json_text(task["detail"]), task["updated_at"]),
            )
        connection.commit()


def _task(task_id: str, state: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {"task_id": task_id, "state": state, "detail": detail, "updated_at": utc_now()}


def _write_review_documents(
    run_dir: Path,
    bundle_id: str,
    validation: dict[str, Any],
    preflight: dict[str, Any],
) -> None:
    review = f"""# R2 Review: strategy and Paper policy proposals

- Bundle: `{bundle_id}`
- Version: `{REVIEW_VERSION}`
- State: `WAIT_REVIEW`
- Review URL: `http://127.0.0.1:8020/?workspace=options&view=review&symbol=NVDA&review={bundle_id}`
- Proposal validation: `{validation['status']}`
- Activation: `{preflight['status']}`
- Strategy, Paper entry and real orders: `DISABLED`

## Recommended first engineering scope

For P3 engineering only, the clearest baseline is `STRAT-SHORT-ATM-RANGE-EXPANSION-V1` with `PAPER-RECEIPT-TIME-PROXY-V1`, `PAPER-RISK-10000-V1`, `COST-OPTIONS-CONSERVATIVE-V1`, and `METRIC-OPTIONS-RESEARCH-GATE-V1`. CALL and PUT remain separate evidence strata. This recommendation does not assert profitability and does not activate anything.

`PAPER-STRICT-NATIVE-BBO-V1` remains blocked because provider-native BBO event time is unavailable. The receipt-time policy is a research proxy and can never be relabeled as an exchange fill.

## Owner review steps

1. Read each profile's profit mechanism and explain what price, volatility, or catalyst change it is intended to capture.
2. Confirm holding time and DTE are separate, and inspect Call and Put rules independently.
3. Inspect the synthetic accept/reject cases and confirm unknown event or quote data abstains.
4. Review entry, invalidation, exit, expiry buffer, and event handling.
5. Review Paper capital, contract quantity, costs, spread accounting, and both quote policies.
6. Confirm validation targets, legacy thresholds, maturity floors, and experiment budgets.
7. Reply with exact strategy, execution, capital, cost, metric IDs, profile, and CALL/PUT scope. Unselected profiles remain draft.

## Required reply shape

```text
R2: select <strategy_policy_id> + <paper_execution_policy_id> + PAPER-RISK-10000-V1 + COST-OPTIONS-CONSERVATIVE-V1 + METRIC-OPTIONS-RESEARCH-GATE-V1.
scope=<profile_id and CALL/PUT scope>.
Approved for offline strategy simulation engineering only; no real trading.
```
"""
    limitations = """# R2 Known Limitations

1. No proposal has option profitability evidence; all are `PROPOSAL_ONLY`.
2. E-S-001 is `INCONCLUSIVE` underlying research and is not an entry factor or option P&L result.
3. Native BBO event time is unavailable, so strict quote execution remains blocked.
4. Receipt-time quote evidence is a research proxy, not exchange execution evidence.
5. Event coverage is partial; the short event-drift alternative and long catalyst proposal are data blocked.
6. Comparable IV history is partial for the medium proposal.
7. Long-duration outcomes require at least 252 trading days before a result can mature.
8. Foundation market-day and cross-day validation remains a separate WAIT_MARKET branch.
9. No policy may be loaded by signal, Paper, account, or order consumers before an exact R2 owner decision and P3 version freeze.
"""
    resume = """# Resume after R2

Wait for an exact R2 policy selection and scope in the current conversation. On acceptance, record the selected IDs and rights, then enter P3 tasks T13-T18. Do not infer acceptance from page visits or partial comments.

If the owner rejects a proposal, remain in P2 and revise only the identified proposal or evidence gap into a new immutable R2 bundle. Do not modify the old draft profiles.
"""
    write_text_immutable(run_dir / "REVIEW.md", review)
    write_text_immutable(run_dir / "KNOWN_LIMITATIONS.md", limitations)
    write_text_immutable(run_dir / "RESUME.md", resume)


def run_p2(
    *,
    bundle_id: str,
    accepted_r1_bundle: str,
    acceptance_message: str,
    review_db: Path = REVIEW_DB,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    if run_dir.exists():
        raise RuntimeError(f"R2 bundle already exists and is immutable: {run_dir}")
    run_dir.mkdir(parents=True)

    r1_dir, r1_manifest = _latest_r1(accepted_r1_bundle)
    store = initialize_review_store(review_db)
    profile_boundary = _profile_boundary(r1_manifest)
    if not profile_boundary["preserved"]:
        raise RuntimeError("Original profile boundary changed after R1")

    strategy = load_json(STRATEGY_PATH)
    paper = load_json(PAPER_PATH)
    metric = load_json(METRIC_PATH)
    validation = validate_proposal_catalogs(strategy, paper, metric)
    if validation["status"] != "PASS":
        raise RuntimeError(f"R2 proposal validation failed: {validation['blockers']}")
    preflight = activation_preflight(strategy, paper, metric)
    acceptance = {
        "review_id": "R1",
        "prior_bundle_id": accepted_r1_bundle,
        "prior_bundle_hash": r1_manifest.get("bundle_hash"),
        "decision": "ACCEPTED_FOR_P2_PROPOSALS_ONLY",
        "user_message": acceptance_message,
        "recorded_at": utc_now(),
        "scientific_result_overridden": False,
        "signals_approved": False,
        "paper_entries_approved": False,
        "orders_approved": False,
    }

    tasks = [
        _task("T07", "VERIFIED", {"profile_summary": validation["profile_summary"], "maximum_two_proposals_per_profile": True, "unsupported_evidence_recorded": True}),
        _task("T08", "VERIFIED", {"proposal_id": "STRAT-SHORT-ATM-RANGE-EXPANSION-V1", "alternative_id": "STRAT-SHORT-ATM-EVENT-DRIFT-V1", "status": "PROPOSAL_ONLY"}),
        _task("T09", "VERIFIED", {"proposal_id": "STRAT-MEDIUM-ATM-TREND-CARRY-V1", "independent_from_short_profile": True, "status": "PROPOSAL_ONLY"}),
        _task("T10", "VERIFIED", {"proposal_id": "STRAT-LONG-OTM-CATALYST-CONVEXITY-V1", "low_premium_is_not_cheap": True, "status": "PROPOSAL_ONLY_DATA_BLOCKED"}),
        _task("T11", "VERIFIED", {"execution_policy_ids": validation["execution_policy_ids"], "legacy_thresholds": validation["legacy_thresholds"], "activation_preflight": preflight["status"]}),
        _task("T12", "WAIT_REVIEW", {"review_id": "R2", "bundle_id": bundle_id, "owner_selection_required": True}),
    ]
    catalogs = {"strategy": strategy, "paper": paper, "metric": metric}
    _store_bundle(review_db, bundle_id, acceptance, catalogs, tasks)

    write_json_immutable(run_dir / "r1_acceptance.json", acceptance)
    write_json_immutable(run_dir / "strategy_proposals.json", strategy)
    write_json_immutable(run_dir / "paper_policy_proposals.json", paper)
    write_json_immutable(run_dir / "metric_policy_proposal.json", metric)
    write_json_immutable(run_dir / "proposal_validation.json", validation)
    write_json_immutable(run_dir / "activation_preflight.json", preflight)
    write_json_immutable(run_dir / "profile_boundary.json", profile_boundary)
    write_json_immutable(run_dir / "task_state.json", {"tasks": tasks})

    source_files = [
        Path(__file__),
        REPO_ROOT / "scripts" / "run_options_review_r2.py",
        REPO_ROOT / "kquant" / "dashboard" / "app.py",
        REPO_ROOT / "web" / "src" / "unified" / "OptionsResearchWorkbench.tsx",
        REPO_ROOT / "web" / "src" / "unified" / "OptionsWorkspace.tsx",
        REPO_ROOT / "web" / "src" / "unified" / "i18n.tsx",
        REPO_ROOT / "web" / "src" / "unified" / "options-workspace.css",
        STRATEGY_PATH,
        PAPER_PATH,
        METRIC_PATH,
        PROFILE_PATH,
        MASTER_PLAN_PATH,
        OWNER_PLAYBOOK_PATH,
        TASK_GRAPH_PATH,
    ]
    manifest = {
        "review_id": "R2",
        "bundle_id": bundle_id,
        "review_version": REVIEW_VERSION,
        "state": "WAIT_REVIEW",
        "generated_at": utc_now(),
        "git": _git_identity(),
        "prior_review": {
            "bundle_id": accepted_r1_bundle,
            "bundle_hash": r1_manifest.get("bundle_hash"),
            "run_dir": str(r1_dir.resolve()),
            "accepted_for": "P2_PROPOSAL_DEVELOPMENT_ONLY",
        },
        "code_hashes": {str(path.relative_to(REPO_ROOT)): sha256_file(path) for path in source_files},
        "catalog_hashes": {kind: content_hash(payload) for kind, payload in catalogs.items()},
        "profile_boundary": profile_boundary,
        "proposal_validation": validation,
        "activation_preflight": preflight,
        "review_store": store,
        "permissions": {
            "signals": False,
            "paper_entries": False,
            "orders": False,
            "real_account": False,
            "crypto_new_research": False,
        },
        "tests": {"status": "PENDING_FINALIZATION"},
    }
    manifest["bundle_hash"] = content_hash(manifest)
    write_json_immutable(run_dir / "manifest.pre_verification.json", manifest)
    write_json_immutable(
        run_dir / "ACCEPTANCE.json",
        {
            "review_id": "R2",
            "bundle_id": bundle_id,
            "state": "WAIT_REVIEW",
            "proposal_validation": validation["status"],
            "activation_allowed": False,
            "owner_policy_selection_required": True,
            "signals_enabled": False,
            "paper_entries_enabled": False,
            "orders_enabled": False,
        },
    )
    _write_review_documents(run_dir, bundle_id, validation, preflight)
    latest = {
        "bundle_id": bundle_id,
        "bundle_hash": manifest["bundle_hash"],
        "run_dir": str(run_dir.resolve()),
        "state": "WAIT_REVIEW",
        "updated_at": utc_now(),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = output_root / "LATEST.json.tmp"
    temporary.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_root / "LATEST.json")
    return {
        "status": "WAIT_REVIEW",
        "bundle_id": bundle_id,
        "run_dir": str(run_dir.resolve()),
        "validation": validation,
        "activation_preflight": preflight,
        "tasks": tasks,
        "manifest": manifest,
    }


def finalize_p2_bundle(
    bundle_id: str,
    verification: dict[str, Any],
    *,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    manifest_path = run_dir / "manifest.json"
    preliminary_path = run_dir / "manifest.pre_verification.json"
    if manifest_path.exists():
        raise RuntimeError(f"R2 bundle is already finalized and immutable: {manifest_path}")
    if not preliminary_path.exists():
        raise FileNotFoundError(preliminary_path)
    verification_path = run_dir / "verification.json"
    write_json_immutable(verification_path, verification)
    manifest = load_json(preliminary_path)
    boolean_checks = [value for value in verification.values() if isinstance(value, bool)]
    manifest["tests"] = {
        "status": "PASS" if boolean_checks and all(boolean_checks) else "PARTIAL",
        "verification_sha256": sha256_file(verification_path),
    }
    manifest["finalized_at"] = utc_now()
    manifest["bundle_hash"] = content_hash({key: value for key, value in manifest.items() if key != "bundle_hash"})
    write_json_immutable(manifest_path, manifest)
    latest = {
        "bundle_id": bundle_id,
        "bundle_hash": manifest["bundle_hash"],
        "run_dir": str(run_dir.resolve()),
        "state": "WAIT_REVIEW",
        "updated_at": utc_now(),
    }
    temporary = output_root / "LATEST.json.tmp"
    temporary.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_root / "LATEST.json")
    return manifest


def review_r2_payload(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    latest_path = output_root / "LATEST.json"
    if not latest_path.exists():
        return {"status": "NOT_AVAILABLE", "review_id": "R2", "state": "NOT_OPEN"}
    latest = load_json(latest_path)
    run_dir = Path(latest["run_dir"])
    required = {
        "manifest": "manifest.json" if (run_dir / "manifest.json").exists() else "manifest.pre_verification.json",
        "strategies": "strategy_proposals.json",
        "paper": "paper_policy_proposals.json",
        "metric": "metric_policy_proposal.json",
        "validation": "proposal_validation.json",
        "preflight": "activation_preflight.json",
        "profiles": "profile_boundary.json",
        "tasks": "task_state.json",
        "acceptance": "r1_acceptance.json",
    }
    payload = {key: load_json(run_dir / name) for key, name in required.items() if (run_dir / name).exists()}
    return {
        "status": "AVAILABLE",
        "review_id": "R2",
        "state": "WAIT_REVIEW",
        "bundle_id": latest["bundle_id"],
        "bundle_hash": latest["bundle_hash"],
        "review_url": f"http://127.0.0.1:8020/?workspace=options&view=review&symbol=NVDA&review={latest['bundle_id']}",
        **payload,
        "signals_enabled": False,
        "paper_entries_enabled": False,
        "orders_enabled": False,
    }


__all__ = [
    "OUTPUT_ROOT",
    "REVIEW_DB",
    "REVIEW_VERSION",
    "activation_preflight",
    "finalize_p2_bundle",
    "review_r2_payload",
    "run_p2",
    "validate_proposal_catalogs",
]
