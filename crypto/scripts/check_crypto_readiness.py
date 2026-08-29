"""Print the deterministic 999 plan Go/No-Go report."""

from __future__ import annotations

import json
from pathlib import Path

from kquant_crypto.backup import latest_backup_status
from kquant_crypto.collection_session import read_collection_gate
from kquant_crypto.config import load_settings
from kquant_crypto.external_evidence import evidence_coverage
from kquant_crypto.parquet_store import ParquetMarketStore
from kquant_crypto.readiness import evaluate_readiness
from kquant_crypto.roll_validation_store import latest_roll_validation_report
from kquant_crypto.shadow_store import shadow_summary
from kquant_crypto.staging import staging_status, verify_staging


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    settings = load_settings(root)
    report = latest_roll_validation_report(settings.db_path) or {}
    validation_gate = report.get("validation_gate") if isinstance(report, dict) else None
    staging = staging_status(settings)
    if staging.get("postgres_configured") and staging.get("driver_available"):
        staging = verify_staging(settings)
    shadow = shadow_summary(settings.db_path, validation_gate_status=str((validation_gate or {}).get("status") or "NO_GO"))
    storage = ParquetMarketStore(settings.data_dir).coverage()
    coverage = {
        "coverage_index_status": storage.get("coverage_index_status", "unknown"),
        "raw_index_repair_required": bool(storage.get("raw_index_repair_required", True)),
        "coverage_basis": storage.get("recovery_basis") or "incremental_index",
        "continuous_collection_gate": read_collection_gate(settings.outputs_dir),
    }
    backup = latest_backup_status(settings.outputs_dir)
    if backup.get("status") == "not_found":
        # Local backup operations deliberately store snapshots under work/;
        # keep the readiness CLI aligned with the protected API endpoint.
        backup = latest_backup_status(settings.root_dir / "work" / "backups")
    result = evaluate_readiness(
        validation_gate=validation_gate,
        coverage_gate=coverage,
        evidence_coverage=evidence_coverage(settings.db_path),
        staging=staging,
        shadow=shadow,
        backup=backup,
        raw_index_repair_required=coverage["raw_index_repair_required"],
        research_only=True,
        order_submission=False,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
