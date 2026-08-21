from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backtest_audit import stable_hash
from .stock_store import connect
from .stock_quant_validation import latest_stock_quant_validation, stock_quant_validation_detail
from .strategy_registry import StrategyDefinition, register_strategy_version


FREEZE_THRESHOLD = 70.0


def strategy_freeze_status(db_path: Path, strategy_version: str) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM strategy_freezes WHERE strategy_version = ?", (strategy_version,)).fetchone()
    return dict(row) if row else None


def freeze_strategy_for_forward_observation(
    *,
    db_path: Path,
    definition: StrategyDefinition,
    validation_audit: dict[str, Any],
    evidence_score: float,
) -> dict[str, Any]:
    """Freeze an immutable strategy manifest only when validation reaches its gate."""

    record = register_strategy_version(db_path, definition)
    existing = strategy_freeze_status(db_path, record.strategy_version)
    fingerprint = str(validation_audit.get("reproducibility_fingerprint") or "")
    if existing:
        return {"status": "already_frozen", "freeze": existing, "read_only_research": True}
    if evidence_score < FREEZE_THRESHOLD or not fingerprint:
        return {
            "status": "validation_not_passed",
            "strategy_version": record.strategy_version,
            "required_evidence_score": FREEZE_THRESHOLD,
            "evidence_score": evidence_score,
            "reason": "Do not begin forward observation until strategy evidence is explicit and sufficient.",
            "read_only_research": True,
        }
    manifest = {
        "strategy_id": record.strategy_id,
        "strategy_version": record.strategy_version,
        "profile_name": record.profile_name,
        "strategy_config_hash": record.config_hash,
        "validation_fingerprint": fingerprint,
        "validation_run_id": validation_audit.get("validation_run_id"),
        "validation_version": validation_audit.get("validation_version"),
        "deployment_model": validation_audit.get("deployment_model"),
        "evidence_score": evidence_score,
        "frozen_for": "forward_observation",
    }
    now = datetime.now(UTC).isoformat()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO strategy_freezes(
              strategy_version, strategy_id, profile_name, strategy_config_hash,
              validation_fingerprint, evidence_score, status, manifest_json, frozen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.strategy_version, record.strategy_id, record.profile_name,
                record.config_hash, fingerprint, evidence_score, "frozen",
                json.dumps({**manifest, "manifest_hash": stable_hash(manifest)}, ensure_ascii=True), now,
            ),
        )
        conn.commit()
    return {"status": "frozen", "freeze": strategy_freeze_status(db_path, record.strategy_version), "read_only_research": True}


def freeze_stock_quant_strategy_for_shadow(
    *,
    db_path: Path,
    definition: StrategyDefinition,
    validation_run_id: str | None = None,
) -> dict[str, Any]:
    """Freeze a strategy only from an immutable, eligible Stock Quant run."""

    try:
        payload = (
            stock_quant_validation_detail(db_path, validation_run_id)
            if validation_run_id
            else latest_stock_quant_validation(db_path)
        )
    except (ValueError, RuntimeError) as exc:
        return {
            "status": "validation_not_passed",
            "reason": f"Stock Quant validation could not be verified: {exc}",
            "read_only_research": True,
        }
    run = dict(payload.get("run") or payload)
    summary = dict(run.get("summary") or {})
    checks = dict(summary.get("overall_gate_checks") or {})
    blockers = list(summary.get("deployment_blockers") or [])
    eligible = bool(
        run.get("gate_status") == "pass"
        and run.get("dataset_integrity_status") == "verified"
        and summary.get("deployment_status") == "eligible"
        and summary.get("deployment_model")
        and checks
        and all(bool(value) for value in checks.values())
        and not blockers
    )
    if not eligible:
        return {
            "status": "validation_not_passed",
            "reason": "Stock Quant Phase 5 evidence is not eligible for Shadow Observation.",
            "validation_run_id": run.get("run_id"),
            "deployment_blockers": blockers,
            "read_only_research": True,
        }
    return freeze_strategy_for_forward_observation(
        db_path=db_path,
        definition=definition,
        validation_audit={
            "reproducibility_fingerprint": run.get("content_hash"),
            "validation_run_id": run.get("run_id"),
            "validation_version": run.get("validation_version"),
            "deployment_model": summary.get("deployment_model"),
        },
        evidence_score=FREEZE_THRESHOLD,
    )
