"""Deterministic final readiness aggregation for the 999 research plan."""

from __future__ import annotations

from typing import Any, Mapping


READINESS_VERSION = "crypto_999_readiness_v1.0.0"


def _check(check_id: str, label: str, passed: bool, observed: Any, required: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "passed": bool(passed),
        "observed": observed,
        "required": required,
    }


def evaluate_readiness(
    *,
    validation_gate: Mapping[str, Any] | None,
    coverage_gate: Mapping[str, Any] | None,
    evidence_coverage: Mapping[str, Any] | None,
    staging: Mapping[str, Any] | None,
    shadow: Mapping[str, Any] | None,
    backup: Mapping[str, Any] | None,
    raw_index_repair_required: bool = True,
    research_only: bool = True,
    order_submission: bool = False,
) -> dict[str, Any]:
    """Aggregate release evidence without changing downstream permissions.

    Missing inputs are failures. The function intentionally does not infer
    coverage from historical labels, Paper results, or a healthy API process.
    """

    validation = validation_gate or {}
    coverage = coverage_gate or {}
    evidence = evidence_coverage or {}
    staging_value = staging or {}
    shadow_value = shadow or {}
    backup_value = backup or {}
    categories = evidence.get("categories") if isinstance(evidence.get("categories"), dict) else {}
    category_failures = sorted(
        str(name) for name, item in categories.items()
        if not isinstance(item, Mapping) or item.get("status") != "complete"
    )
    observed_days = int(shadow_value.get("observed_trading_days") or 0)
    checks = [
        _check(
            "read_only_boundary",
            "no account, wallet, order or automatic execution path",
            research_only is True and order_submission is False,
            {"research_only": research_only, "order_submission": order_submission},
            {"research_only": True, "order_submission": False},
        ),
        _check(
            "raw_data_index",
            "raw coverage index is complete and repair is not pending",
            coverage.get("coverage_index_status") == "complete" and not raw_index_repair_required,
            {
                "coverage_index_status": coverage.get("coverage_index_status"),
                "raw_index_repair_required": raw_index_repair_required,
            },
            {"coverage_index_status": "complete", "raw_index_repair_required": False},
        ),
        _check(
            "collection_gate",
            "continuous market-data collection gate passed",
            coverage.get("continuous_collection_gate", {}).get("status") == "PASS",
            coverage.get("continuous_collection_gate", {}).get("status"),
            "PASS",
        ),
        _check(
            "validation_gate",
            "locked OOS validation gate passed",
            validation.get("status") == "PASS",
            validation.get("status"),
            "PASS",
        ),
        _check(
            "external_evidence",
            "all required ETF, exchange, on-chain, whale and protocol evidence is complete",
            bool(categories) and not category_failures,
            {"status": evidence.get("status"), "failed_categories": category_failures},
            "every category status=complete",
        ),
        _check(
            "staging",
            "protected PostgreSQL staging is connected and migrated",
            staging_value.get("connection_status") == "available" and staging_value.get("migration_status") == "migrated",
            {
                "connection_status": staging_value.get("connection_status"),
                "migration_status": staging_value.get("migration_status"),
            },
            {"connection_status": "available", "migration_status": "migrated"},
        ),
        _check(
            "backup_restore",
            "latest backup has a verified restore",
            backup_value.get("restore_verified") is True,
            {"status": backup_value.get("status"), "restore_verified": backup_value.get("restore_verified")},
            {"restore_verified": True},
        ),
        _check(
            "shadow_observation",
            "at least 15 real trading-day observations completed",
            observed_days >= 15 and shadow_value.get("status") == "PASS",
            {"observed_trading_days": observed_days, "status": shadow_value.get("status")},
            {"observed_trading_days": ">=15", "status": "PASS"},
        ),
    ]
    failed = [item["id"] for item in checks if not item["passed"]]
    return {
        "version": READINESS_VERSION,
        "status": "GO" if not failed else "NO_GO",
        "passed": not failed,
        "release_state": "SHADOW_ONLY" if not failed else "RESEARCH_ONLY",
        "failed_checks": failed,
        "checks": checks,
        "research_only": True,
        "order_submission": False,
        "note": "This report is an auditable research gate and never authorizes live orders.",
    }


__all__ = ["READINESS_VERSION", "evaluate_readiness"]
