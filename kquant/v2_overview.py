from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .capital_rotation import latest_capital_rotation
from .data_coverage import api_stock_data_coverage
from .leadership import latest_leadership
from .stock_quant import latest_stock_quant_run
from .stock_quant_validation import latest_stock_quant_validation
from .shadow_observation import latest_shadow_observation
from .theme_prediction import latest_theme_prediction
from .theme_taxonomy import latest_theme_taxonomy


OVERVIEW_CONTRACT_VERSION = "kquant_v2_overview_v1.0.0"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stage(status: str, run_id: str | None, as_of: str | None, source: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "run_id": run_id,
        "as_of": as_of,
        "source": source,
    }


def build_v2_overview(db_path: Path) -> dict[str, Any]:
    """Return the read-only v2 evidence chain for the Today workspace.

    This endpoint composes already materialized, point-in-time artifacts. It
    never creates a model run, refreshes data, or turns a research artifact
    into an execution permission.
    """

    coverage = api_stock_data_coverage(db_path)
    taxonomy = latest_theme_taxonomy(db_path)
    rotation = latest_capital_rotation(db_path)
    prediction = latest_theme_prediction(db_path)
    leadership = latest_leadership(db_path)
    stock_quant = latest_stock_quant_run(db_path)
    validation = latest_stock_quant_validation(db_path)
    interval_summary = coverage.get("interval_summary") or {}
    daily = interval_summary.get("1d") or {}
    hourly = interval_summary.get("1h") or {}
    validation_run = validation.get("run") or {}
    validation_summary = validation_run.get("summary") or {}
    validation_gate = validation_run.get("gate_status") or "not_available"
    coverage_gate = bool(daily.get("target_met")) and bool(hourly.get("target_met"))

    return {
        "status": "materialized",
        "contract_version": OVERVIEW_CONTRACT_VERSION,
        "as_of": _now(),
        "read_only_research": True,
        "automatic_execution_allowed": False,
        "order_submission_enabled": False,
        "evidence_chain": [
            _stage(
                "materialized" if rotation.get("status") == "materialized" else "not_available",
                rotation.get("run_id"),
                rotation.get("as_of_time"),
                (rotation.get("summary") or {}).get("data_source"),
            ),
            _stage(
                "materialized" if taxonomy.get("status") == "materialized" else "not_available",
                taxonomy.get("run_id"),
                taxonomy.get("as_of_date") or taxonomy.get("created_at"),
                "universe_registry",
            ),
            _stage(
                "materialized" if leadership.get("status") == "materialized" else "not_available",
                leadership.get("run_id"),
                leadership.get("as_of_time"),
                (leadership.get("summary") or {}).get("data_source"),
            ),
            _stage(
                "materialized" if stock_quant.get("status") == "materialized" else "not_available",
                (stock_quant.get("run") or {}).get("run_id"),
                (stock_quant.get("run") or {}).get("created_at"),
                "longbridge_candles",
            ),
        ],
        "versions": {
            "taxonomy": taxonomy.get("taxonomy_version"),
            "capital_rotation": (rotation.get("summary") or {}).get("version"),
            "theme_prediction": prediction.get("prediction_version"),
            "leadership": (leadership.get("summary") or {}).get("version"),
            "stock_quant_model": (stock_quant.get("run") or {}).get("model_version"),
            "stock_quant_validation": validation_run.get("validation_version"),
            "dataset_id": (stock_quant.get("run") or {}).get("dataset_id"),
        },
        "data_trust": {
            "primary_provider": coverage.get("primary_provider"),
            "universe_symbols": coverage.get("universe_symbols", 0),
            "canonical_validation_eligible_symbols": coverage.get("canonical_validation_eligible_symbols", 0),
            "legacy_reference_observations": coverage.get("legacy_reference_observations", 0),
            "intervals": interval_summary,
            "event_calendar": coverage.get("event_calendar") or {},
            "market_breadth": coverage.get("market_breadth") or {},
            "coverage_gate": "PASS" if coverage_gate else "REVIEW",
            "source_policy": "Longbridge canonical data only; legacy reference data is excluded from model evidence.",
        },
        "capital_rotation": {
            "status": rotation.get("status"),
            "run_id": rotation.get("run_id"),
            "as_of": rotation.get("as_of_time"),
            "ranked_theme_count": (rotation.get("summary") or {}).get("ranked_theme_count", 0),
            "stress_unreasonable_flips": (rotation.get("summary") or {}).get("stress_unreasonable_flips", 0),
            "top_themes": [
                {
                    "definition_id": item.get("definition_id"),
                    "dimension_type": item.get("dimension_type"),
                    "score": item.get("score"),
                    "rank_value": item.get("rank_value"),
                    "status": item.get("status"),
                    "data_quality": item.get("data_quality"),
                    "eligible_member_count": item.get("eligible_member_count", 0),
                }
                for item in (rotation.get("scores") or [])[:8]
            ],
        },
        "leadership": {
            "status": leadership.get("status"),
            "run_id": leadership.get("run_id"),
            "as_of": leadership.get("as_of_time"),
            "unique_symbol_count": (leadership.get("summary") or {}).get("unique_symbol_count", 0),
            "theme_count": (leadership.get("summary") or {}).get("theme_count", 0),
            "state_counts": (leadership.get("summary") or {}).get("state_counts", {}),
            "future_prediction_used": (leadership.get("summary") or {}).get("future_prediction_used", False),
            "top_leaders": [
                {
                    "symbol": item.get("symbol"),
                    "definition_id": item.get("definition_id"),
                    "state": item.get("state"),
                    "score": item.get("score"),
                    "theme_relative_strength": item.get("theme_relative_strength"),
                    "data_quality": item.get("data_quality"),
                }
                for item in (leadership.get("leaders") or [])
                if item.get("state") in {"Leader", "Emerging"}
            ][:12],
        },
        "stock_quant": {
            "status": stock_quant.get("status"),
            "run_id": (stock_quant.get("run") or {}).get("run_id"),
            "dataset_id": (stock_quant.get("run") or {}).get("dataset_id"),
            "model_version": (stock_quant.get("run") or {}).get("model_version"),
            "feature_count": (stock_quant.get("run") or {}).get("feature_count", 0),
            "label_count": (stock_quant.get("run") or {}).get("label_count", 0),
            "validation_gate": validation_gate,
            "validation_run_id": validation_run.get("run_id"),
            "research_candidate": validation_summary.get("selected_model_by_train_validation"),
            "deployment_model": validation_summary.get("deployment_model"),
            "deployment_status": validation_summary.get("deployment_status", "not_available"),
            "deployment_blockers": validation_summary.get("deployment_blockers") or [],
            "test_trade_count": validation_summary.get("selected_test_trade_count", 0),
            "readiness": "RESEARCH_ONLY" if validation_gate != "pass" else "SHADOW_ONLY",
        },
        "theme_prediction": {
            "status": prediction.get("status"),
            "gate_status": prediction.get("gate_status"),
            "display_probability": (prediction.get("summary") or {}).get("display_probability", False),
            "oos_fold_count": prediction.get("oos_fold_count", 0),
        },
        "shadow_observation": latest_shadow_observation(db_path),
    }
