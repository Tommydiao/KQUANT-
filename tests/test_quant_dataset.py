from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kquant.quant_dataset import DatasetIntegrityError, build_quant_dataset, model_artifact_detail, read_quant_dataset, run_baseline_suite, rolling_purged_oos_folds, rolling_purged_splits
from kquant.stock_store import connect


def _items() -> list[dict]:
    start = datetime(2026, 1, 1, 14, 30, tzinfo=UTC)
    rows = []
    for index in range(70):
        signal_time = start + timedelta(days=index)
        for symbol_index, symbol in enumerate(("AAA", "BBB")):
            rows.append(
                {
                    "item_id": f"{symbol}-{index}",
                    "symbol": symbol,
                    "signal_time": signal_time.isoformat(),
                    "feature_available_at": (signal_time - timedelta(hours=1)).isoformat(),
                    "label_end_time": (signal_time + timedelta(days=2)).isoformat(),
                    "source_snapshot_id": "snapshot-test-v1",
                    "features": {
                        "capital_rotation_score": 75.0 if index % 2 else 35.0,
                        "relative_strength": index / 70,
                    },
                    "label": {"target": 1.0 if index % 3 else 0.0, "horizon_days": 2},
                }
            )
    return rows


def test_rolling_split_is_date_based_and_purged(tmp_path: Path) -> None:
    rows = _items()
    result = rolling_purged_splits(rows, embargo_days=5)
    assert {row["split_name"] for row in result["items"]} == {"train", "validation", "test"}
    assert result["purged_count"] == 20
    dates_by_split = {
        name: {row["signal_time"][:10] for row in result["items"] if row["split_name"] == name}
        for name in ("train", "validation", "test")
    }
    assert dates_by_split["train"].isdisjoint(dates_by_split["validation"])
    assert dates_by_split["validation"].isdisjoint(dates_by_split["test"])
    assert result["config"]["label_overlap_policy"].startswith("purge")


def test_walk_forward_folds_expand_without_crossing_label_boundaries() -> None:
    result = rolling_purged_oos_folds(_items(), fold_count=3, embargo_days=3)

    assert result["config"]["method"] == "expanding_window_purged_oos"
    assert len(result["folds"]) == 3
    previous_test_end = ""
    for fold in result["folds"]:
        rows_by_split = {
            split_name: [row for row in fold["items"] if row["split_name"] == split_name]
            for split_name in ("train", "validation", "test")
        }
        assert all(rows_by_split.values())
        train_end = max(row["label_end_time"] for row in rows_by_split["train"])
        validation_start = min(row["signal_time"] for row in rows_by_split["validation"])
        validation_end = max(row["label_end_time"] for row in rows_by_split["validation"])
        test_start = min(row["signal_time"] for row in rows_by_split["test"])
        test_end = max(row["signal_time"] for row in rows_by_split["test"])
        assert train_end < validation_start
        assert validation_end < test_start
        assert previous_test_end < test_start if previous_test_end else True
        previous_test_end = test_end
        assert fold["purged_count"] == fold["excluded"]["label_overlap_purged_count"]
        assert fold["excluded"]["embargo_excluded_count"] > 0
    assert result["folds"][0]["excluded"]["future_excluded_count"] > 0


def test_dataset_and_test_partition_are_immutable(tmp_path: Path) -> None:
    db_path = tmp_path / "quant.sqlite3"
    dataset = build_quant_dataset(db_path, _items(), dataset_id="dataset-fixed", universe_registry_id="registry-test")
    assert dataset["integrity_status"] == "verified"
    assert dataset["partitions"]
    assert read_quant_dataset(db_path, "dataset-fixed")["test_partition_hash"] == dataset["test_partition_hash"]

    changed = _items()
    changed[-1]["label"]["target"] = 1.0 - changed[-1]["label"]["target"]
    with pytest.raises(DatasetIntegrityError, match="different content hash"):
        build_quant_dataset(db_path, changed, dataset_id="dataset-fixed", universe_registry_id="registry-test")

    with connect(db_path) as conn:
        conn.execute("UPDATE quant_dataset_items SET feature_json = ? WHERE dataset_id = ? AND item_id = (SELECT item_id FROM quant_dataset_items WHERE dataset_id = ? AND split_name = 'test' ORDER BY item_id LIMIT 1)", ('{"capital_rotation_score": 99}', "dataset-fixed", "dataset-fixed"))
        conn.commit()
    with pytest.raises(DatasetIntegrityError, match="partition hash mismatch"):
        read_quant_dataset(db_path, "dataset-fixed")


def test_baseline_artifacts_are_reproducible_and_fail_closed_on_dataset_change(tmp_path: Path) -> None:
    db_path = tmp_path / "models.sqlite3"
    dataset = build_quant_dataset(db_path, _items(), dataset_id="dataset-models")
    result = run_baseline_suite(db_path, dataset["dataset_id"], random_seed=7)
    assert {item["model_name"] for item in result["models"]} == {"naive", "capital_rotation_rule", "logistic"}
    assert all(item["dataset_integrity_status"] == "verified" for item in result["models"])
    assert all(item["train_config"]["test_partition_used_for_selection"] is False for item in result["models"])
    detail = model_artifact_detail(db_path, result["models"][0]["artifact_id"])
    assert detail["metrics"]
    assert detail["read_only_research"] is True


def test_future_feature_availability_is_rejected(tmp_path: Path) -> None:
    rows = _items()
    rows[0]["feature_available_at"] = (datetime(2027, 1, 1, tzinfo=UTC)).isoformat()
    with pytest.raises(DatasetIntegrityError, match="feature_available_at"):
        build_quant_dataset(tmp_path / "future.sqlite3", rows)
