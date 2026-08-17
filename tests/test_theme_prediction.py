from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kquant.quant_dataset import DatasetIntegrityError
from kquant.theme_prediction import (
    THEME_PREDICTION_DATASET_CONTRACT,
    build_theme_prediction_dataset,
    latest_theme_prediction,
    run_theme_prediction,
    theme_prediction_detail,
)


def _items() -> list[dict]:
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    rows: list[dict] = []
    for index in range(80):
        signal_time = start + timedelta(days=index)
        for theme_index, theme_id in enumerate(("theme.ai", "theme.space")):
            excess_return = ((index % 9) - 3 + theme_index) / 100
            rows.append(
                {
                    "item_id": f"{theme_id}-{index}",
                    "theme_id": theme_id,
                    "signal_time": signal_time.isoformat(),
                    "feature_available_at": (signal_time - timedelta(hours=1)).isoformat(),
                    "label_end_time": (signal_time + timedelta(days=3)).isoformat(),
                    "source_snapshot_id": f"theme-snapshot-{index}",
                    "features": {
                        "capital_rotation_score": 50 + index % 45,
                        "breadth_ratio": 0.4 + (index % 5) / 10,
                        "relative_strength": (index - 30) / 100,
                    },
                    "label": {
                        "excess_return": excess_return,
                        "rank_percentile": min(0.99, max(0.01, 0.5 + excess_return * 5)),
                        "quantile": min(4, max(0, int((0.5 + excess_return * 5) * 5))),
                    },
                }
            )
    return rows


def test_theme_prediction_dataset_has_versioned_labels_and_is_reproducible(tmp_path: Path) -> None:
    db_path = tmp_path / "theme-prediction.sqlite3"
    dataset = build_theme_prediction_dataset(db_path, _items(), dataset_id="theme-dataset-v1", universe_registry_id="registry-v1")
    assert dataset["contract_version"] == THEME_PREDICTION_DATASET_CONTRACT
    assert dataset["label_schema_version"] == "theme_prediction_labels_v1.0.0"
    assert dataset["integrity_status"] == "verified"
    assert all({"direction", "excess_return", "rank_percentile", "quantile", "target"} <= set(item["label"]) for item in dataset["items"])


def test_theme_prediction_blocks_probability_display_before_oos_gate(tmp_path: Path) -> None:
    db_path = tmp_path / "theme-prediction-models.sqlite3"
    dataset = build_theme_prediction_dataset(db_path, _items(), dataset_id="theme-models-v1")
    result = run_theme_prediction(db_path, dataset["dataset_id"], random_seed=7)
    assert result["gate_status"] == "blocked_insufficient_oos_folds"
    assert result["summary"]["display_probability"] is False
    assert result["summary"]["calibration_gate"]["observed_oos_folds"] == 1
    assert {item["model_name"] for item in result["summary"]["models"]} >= {"theme_naive", "capital_rotation_rule", "theme_logistic"}
    assert {item["method"] for item in result["calibrations"]} == {"platt", "isotonic"}
    assert latest_theme_prediction(db_path)["run_id"] == result["run_id"]
    assert theme_prediction_detail(db_path, result["run_id"])["dataset_integrity_status"] == "verified"


def test_theme_prediction_dataset_change_is_fail_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "theme-prediction-integrity.sqlite3"
    build_theme_prediction_dataset(db_path, _items(), dataset_id="theme-fixed")
    changed = _items()
    changed[-1]["label"]["excess_return"] = 0.99
    changed[-1]["label"]["direction"] = 1
    changed[-1]["label"]["target"] = 1
    with pytest.raises(DatasetIntegrityError, match="different content hash"):
        build_theme_prediction_dataset(db_path, changed, dataset_id="theme-fixed")
