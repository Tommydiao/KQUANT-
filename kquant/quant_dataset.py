from __future__ import annotations

import hashlib
import json
import math
import platform
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .stock_store import connect


DATASET_CONTRACT_VERSION = "stock_quant_dataset_v0.1.0"
FEATURE_SCHEMA_VERSION = "stock_quant_features_v0.1.0"
LABEL_SCHEMA_VERSION = "stock_quant_labels_v0.1.0"
MODEL_ARTIFACT_CONTRACT_VERSION = "model_artifact_v0.1.0"
DEFAULT_EMBARGO_DAYS = 5


class DatasetIntegrityError(ValueError):
    """Raised when an immutable dataset or sealed test partition changes."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _utc(value: Any, *, field: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            raise DatasetIntegrityError(f"{field} is required.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DatasetIntegrityError(f"{field} must be ISO-8601.") from exc
    if parsed.tzinfo is None:
        raise DatasetIntegrityError(f"{field} must include a timezone.")
    return parsed.astimezone(UTC).isoformat()


def _day(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return float(value)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DatasetIntegrityError("Feature values must be finite numbers or null.") from exc
    if not math.isfinite(result):
        raise DatasetIntegrityError("Feature values must be finite numbers or null.")
    return result


def _normalize_features(value: Any) -> dict[str, float | None]:
    if not isinstance(value, dict) or not value:
        raise DatasetIntegrityError("Each dataset item needs a non-empty feature object.")
    return {
        str(key): None if raw is None else _number(raw)
        for key, raw in sorted(value.items(), key=lambda pair: str(pair[0]))
    }


def _normalize_label(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or "target" not in value:
        raise DatasetIntegrityError("Each dataset item needs a label object with target.")
    target = _number(value["target"])
    if not 0.0 <= target <= 1.0:
        raise DatasetIntegrityError("Dataset target must be a probability/direction label in [0, 1].")
    normalized = dict(value)
    normalized["target"] = target
    return normalized


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "item_id": str(item.get("item_id") or "").strip(),
        "symbol": str(item.get("symbol") or "").upper().strip(),
        "signal_time": _utc(item.get("signal_time"), field="signal_time"),
        "feature_available_at": _utc(item.get("feature_available_at"), field="feature_available_at"),
        "label_end_time": _utc(item.get("label_end_time"), field="label_end_time"),
        "source_snapshot_id": str(item.get("source_snapshot_id") or "").strip(),
        "features": _normalize_features(item.get("features")),
        "label": _normalize_label(item.get("label")),
    }
    if not normalized["item_id"] or not normalized["symbol"] or not normalized["source_snapshot_id"]:
        raise DatasetIntegrityError("item_id, symbol, and source_snapshot_id are required.")
    if normalized["feature_available_at"] > normalized["signal_time"]:
        raise DatasetIntegrityError("feature_available_at cannot be after signal_time.")
    if normalized["label_end_time"] <= normalized["signal_time"]:
        raise DatasetIntegrityError("label_end_time must be after signal_time.")
    return normalized


def _partition_hash(rows: Iterable[dict[str, Any]]) -> str:
    payload = [
        {
            "item_id": row["item_id"],
            "symbol": row["symbol"],
            "signal_time": row["signal_time"],
            "feature_available_at": row["feature_available_at"],
            "label_end_time": row["label_end_time"],
            "split_name": row.get("split_name", ""),
            "features": row["features"],
            "label": row["label"],
            "source_snapshot_id": row["source_snapshot_id"],
        }
        for row in sorted(rows, key=lambda item: item["item_id"])
    ]
    return _hash(payload)


def rolling_purged_splits(
    items: Iterable[dict[str, Any]],
    *,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
    train_pct: float = 0.60,
    validation_pct: float = 0.20,
) -> dict[str, Any]:
    """Assign whole signal dates to rolling partitions with purge and embargo.

    The split is date based, not row based. Labels that overlap the next
    partition are purged, and the first `embargo_days` trading dates after a
    boundary are excluded from the next partition.
    """

    rows = [_normalize_item(dict(item)) for item in items]
    if not rows:
        raise DatasetIntegrityError("At least one dataset item is required.")
    if not 0 < train_pct < 1 or not 0 < validation_pct < 1 or train_pct + validation_pct >= 1:
        raise DatasetIntegrityError("train_pct and validation_pct must leave a non-empty test partition.")
    dates = sorted({_day(row["signal_time"]) for row in rows})
    if len(dates) < 10:
        raise DatasetIntegrityError("At least 10 distinct signal dates are required for a rolling split.")
    embargo = max(0, int(embargo_days))
    train_end_index = max(1, min(len(dates) - 2, int(len(dates) * train_pct)))
    validation_end_index = max(train_end_index + 1, min(len(dates) - 1, int(len(dates) * (train_pct + validation_pct))))
    validation_start_index = min(len(dates), train_end_index + embargo)
    test_start_index = min(len(dates), validation_end_index + embargo)
    raw_ranges = {
        "train": dates[:train_end_index],
        "validation": dates[validation_start_index:validation_end_index],
        "test": dates[test_start_index:],
    }
    if not raw_ranges["validation"] or not raw_ranges["test"]:
        raise DatasetIntegrityError("Embargo leaves an empty validation or test partition.")
    next_start = {
        "train": raw_ranges["validation"][0],
        "validation": raw_ranges["test"][0],
        "test": None,
    }
    assigned: list[dict[str, Any]] = []
    purged_count = 0
    for row in rows:
        signal_day = _day(row["signal_time"])
        raw_split = next((name for name, members in raw_ranges.items() if signal_day in members), None)
        if raw_split is None:
            purged_count += 1
            continue
        boundary = next_start[raw_split]
        if boundary is not None and _day(row["label_end_time"]) >= boundary:
            purged_count += 1
            continue
        assigned.append({**row, "split_name": raw_split})
    partition_meta: dict[str, dict[str, Any]] = {}
    for split_name in ("train", "validation", "test"):
        members = [row for row in assigned if row["split_name"] == split_name]
        raw_dates = raw_ranges[split_name]
        partition_meta[split_name] = {
            "start_date": raw_dates[0].isoformat() if raw_dates else "",
            "end_date": raw_dates[-1].isoformat() if raw_dates else "",
            "embargo_start_date": (
                dates[train_end_index].isoformat() if split_name == "validation" and train_end_index < len(dates)
                else dates[validation_end_index].isoformat() if split_name == "test" and validation_end_index < len(dates)
                else ""
            ),
            "embargo_end_date": (
                dates[validation_start_index - 1].isoformat() if split_name == "validation" and validation_start_index > train_end_index
                else dates[test_start_index - 1].isoformat() if split_name == "test" and test_start_index > validation_end_index
                else ""
            ),
            "item_count": len(members),
            "content_hash": _partition_hash(members),
            "sealed": True,
        }
    if not all(partition_meta[name]["item_count"] for name in ("train", "validation", "test")):
        raise DatasetIntegrityError("Purge and embargo left an empty dataset partition.")
    return {
        "items": sorted(assigned, key=lambda item: (item["signal_time"], item["symbol"], item["item_id"])),
        "partitions": partition_meta,
        "purged_count": purged_count,
        "config": {
            "method": "rolling_date_split",
            "train_pct": train_pct,
            "validation_pct": validation_pct,
            "test_pct": round(1 - train_pct - validation_pct, 4),
            "embargo_days": embargo,
            "label_overlap_policy": "purge_if_label_end_reaches_next_partition",
        },
    }


def rolling_purged_oos_folds(
    items: Iterable[dict[str, Any]],
    *,
    fold_count: int = 3,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
    min_train_dates: int = 20,
    min_window_dates: int = 5,
) -> dict[str, Any]:
    """Create expanding-window walk-forward folds without mixing signal dates.

    This is deliberately separate from :func:`rolling_purged_splits`. The
    latter seals one final train/validation/test partition. This helper is
    used only on the pre-sealed-test history to measure walk-forward stability
    while leaving that final test partition untouched.
    """

    rows = [_normalize_item(dict(item)) for item in items]
    if fold_count < 1:
        raise DatasetIntegrityError("At least one walk-forward fold is required.")
    if min_train_dates < 1 or min_window_dates < 1:
        raise DatasetIntegrityError("Walk-forward date windows must be positive.")
    if not rows:
        raise DatasetIntegrityError("At least one dataset item is required for walk-forward folds.")

    dates = sorted({_day(row["signal_time"]) for row in rows})
    embargo = max(0, int(embargo_days))
    reserved_dates = fold_count * (2 * embargo + 2 * min_window_dates)
    if len(dates) < min_train_dates + reserved_dates:
        raise DatasetIntegrityError(
            "Insufficient distinct signal dates for the requested walk-forward folds with embargo."
        )

    window_dates = (len(dates) - min_train_dates - 2 * embargo * fold_count) // (2 * fold_count)
    if window_dates < min_window_dates:
        raise DatasetIntegrityError(
            "Walk-forward folds would leave a validation or OOS window below the minimum size."
        )
    initial_train_dates = len(dates) - fold_count * (2 * embargo + 2 * window_dates)
    if initial_train_dates < min_train_dates:
        raise DatasetIntegrityError("Walk-forward folds would leave an insufficient initial training window.")

    cursor = initial_train_dates
    folds: list[dict[str, Any]] = []
    for fold_index in range(fold_count):
        validation_start = cursor + embargo
        validation_end = validation_start + window_dates
        test_start = validation_end + embargo
        test_end = test_start + window_dates
        if test_end > len(dates):
            raise DatasetIntegrityError("Walk-forward fold construction exceeded the available date range.")

        raw_ranges = {
            "train": dates[:cursor],
            "validation": dates[validation_start:validation_end],
            "test": dates[test_start:test_end],
        }
        if not all(raw_ranges.values()):
            raise DatasetIntegrityError("Walk-forward fold contains an empty partition.")
        next_start = {
            "train": raw_ranges["validation"][0],
            "validation": raw_ranges["test"][0],
            "test": None,
        }

        assigned: list[dict[str, Any]] = []
        label_overlap_purged_count = 0
        embargo_excluded_count = 0
        future_excluded_count = 0
        for row in rows:
            signal_day = _day(row["signal_time"])
            split_name = next(
                (name for name, members in raw_ranges.items() if signal_day in members),
                None,
            )
            if split_name is None:
                if signal_day > raw_ranges["test"][-1]:
                    future_excluded_count += 1
                else:
                    embargo_excluded_count += 1
                continue
            boundary = next_start[split_name]
            if boundary is not None and _day(row["label_end_time"]) >= boundary:
                label_overlap_purged_count += 1
                continue
            assigned.append({**row, "split_name": split_name})

        partitions: dict[str, dict[str, Any]] = {}
        for split_name in ("train", "validation", "test"):
            members = [row for row in assigned if row["split_name"] == split_name]
            raw_dates = raw_ranges[split_name]
            partitions[split_name] = {
                "start_date": raw_dates[0].isoformat(),
                "end_date": raw_dates[-1].isoformat(),
                "item_count": len(members),
                "content_hash": _partition_hash(members),
                "sealed": True,
            }
        if not all(partitions[name]["item_count"] for name in ("train", "validation", "test")):
            raise DatasetIntegrityError("Purge and embargo left an empty walk-forward partition.")

        folds.append({
            "fold_id": f"walk_forward_{fold_index + 1:02d}",
            "items": sorted(assigned, key=lambda item: (item["signal_time"], item["symbol"], item["item_id"])),
            "partitions": partitions,
            "purged_count": label_overlap_purged_count,
            "excluded": {
                "label_overlap_purged_count": label_overlap_purged_count,
                "embargo_excluded_count": embargo_excluded_count,
                "future_excluded_count": future_excluded_count,
            },
            "embargo": {
                "train_to_validation": [
                    dates[cursor].isoformat(),
                    dates[validation_start - 1].isoformat(),
                ] if embargo else [],
                "validation_to_test": [
                    dates[validation_end].isoformat(),
                    dates[test_start - 1].isoformat(),
                ] if embargo else [],
            },
        })
        cursor = test_end

    return {
        "folds": folds,
        "config": {
            "method": "expanding_window_purged_oos",
            "fold_count": fold_count,
            "embargo_days": embargo,
            "initial_train_dates": initial_train_dates,
            "validation_window_dates": window_dates,
            "oos_window_dates": window_dates,
            "label_overlap_policy": "purge_if_label_end_reaches_next_partition",
        },
    }


def build_quant_dataset(
    db_path: Path,
    items: Iterable[dict[str, Any]],
    *,
    dataset_id: str | None = None,
    universe_registry_id: str = "",
    source_policy_version: str = "market_source_eligibility_v1",
    start_date: str | None = None,
    end_date: str | None = None,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
    contract_version: str = DATASET_CONTRACT_VERSION,
    feature_schema_version: str = FEATURE_SCHEMA_VERSION,
    label_schema_version: str = LABEL_SCHEMA_VERSION,
) -> dict[str, Any]:
    normalized = [_normalize_item(dict(item)) for item in items]
    if len({item["item_id"] for item in normalized}) != len(normalized):
        raise DatasetIntegrityError("Dataset item_id values must be unique.")
    split = rolling_purged_splits(normalized, embargo_days=embargo_days)
    all_items = split["items"]
    if not all_items:
        raise DatasetIntegrityError("No items remain after purge and embargo.")
    first_date = start_date or min(item["signal_time"][:10] for item in all_items)
    last_date = end_date or max(item["signal_time"][:10] for item in all_items)
    feature_order = sorted({key for item in all_items for key in item["features"]})
    canonical = {
        "contract_version": contract_version,
        "feature_schema_version": feature_schema_version,
        "label_schema_version": label_schema_version,
        "universe_registry_id": universe_registry_id,
        "source_policy_version": source_policy_version,
        "start_date": first_date,
        "end_date": last_date,
        "split": split["config"],
        "feature_order": feature_order,
        "purged_count": split["purged_count"],
        "partitions": split["partitions"],
        "items": all_items,
    }
    content_hash = _hash(canonical)
    resolved_id = dataset_id or f"qds_{content_hash[:24]}"
    test_partition_hash = split["partitions"]["test"]["content_hash"]
    created_at = _now()
    with connect(db_path) as conn:
        existing = conn.execute("SELECT * FROM quant_datasets WHERE dataset_id = ?", (resolved_id,)).fetchone()
        if existing is not None and str(existing["content_hash"]) != content_hash:
            raise DatasetIntegrityError("Immutable dataset_id already exists with a different content hash.")
        conn.execute(
            """
            INSERT OR IGNORE INTO quant_datasets(
              dataset_id, contract_version, feature_schema_version, label_schema_version,
              universe_registry_id, source_policy_version, start_date, end_date,
              split_config_json, content_hash, status, test_partition_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sealed', ?, ?)
            """,
            (resolved_id, contract_version, feature_schema_version, label_schema_version,
             universe_registry_id, source_policy_version, first_date, last_date,
             _canonical({**split["config"], "feature_order": feature_order, "purged_count": split["purged_count"]}),
             content_hash, test_partition_hash, created_at),
        )
        sealed_row = conn.execute(
            "SELECT dataset_id FROM quant_datasets WHERE dataset_id = ?",
            (resolved_id,),
        ).fetchone()
        if sealed_row is None:
            duplicate = conn.execute(
                "SELECT dataset_id FROM quant_datasets WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            if duplicate is not None:
                raise DatasetIntegrityError(
                    f"Dataset content is already sealed under dataset_id={duplicate['dataset_id']}; "
                    "reuse that immutable id instead of creating a second alias."
                )
            raise DatasetIntegrityError("Dataset row was not sealed before its partitions could be written.")
        conn.executemany(
            """
            INSERT OR IGNORE INTO quant_dataset_partitions(
              dataset_id, split_name, start_date, end_date, embargo_start_date,
              embargo_end_date, item_count, content_hash, sealed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            [(resolved_id, name, meta["start_date"], meta["end_date"], meta["embargo_start_date"], meta["embargo_end_date"], meta["item_count"], meta["content_hash"], created_at) for name, meta in split["partitions"].items()],
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO quant_dataset_items(
              dataset_id, item_id, symbol, signal_time, feature_available_at,
              label_end_time, split_name, feature_json, label_json, feature_hash,
              label_hash, source_snapshot_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(resolved_id, item["item_id"], item["symbol"], item["signal_time"], item["feature_available_at"], item["label_end_time"], item["split_name"], _canonical(item["features"]), _canonical(item["label"]), _hash(item["features"]), _hash(item["label"]), item["source_snapshot_id"], created_at) for item in all_items],
        )
        conn.commit()
    return read_quant_dataset(db_path, resolved_id)


def read_quant_dataset(db_path: Path, dataset_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        dataset = conn.execute("SELECT * FROM quant_datasets WHERE dataset_id = ?", (dataset_id,)).fetchone()
        if dataset is None:
            raise ValueError(f"Unknown quant dataset: {dataset_id}")
        partitions = [dict(row) for row in conn.execute("SELECT * FROM quant_dataset_partitions WHERE dataset_id = ? ORDER BY split_name", (dataset_id,)).fetchall()]
        rows = [dict(row) for row in conn.execute("SELECT * FROM quant_dataset_items WHERE dataset_id = ? ORDER BY signal_time, symbol, item_id", (dataset_id,)).fetchall()]
    items = []
    for row in rows:
        items.append({
            "item_id": row["item_id"], "symbol": row["symbol"], "signal_time": row["signal_time"],
            "feature_available_at": row["feature_available_at"], "label_end_time": row["label_end_time"],
            "split_name": row["split_name"], "features": json.loads(row["feature_json"]),
            "label": json.loads(row["label_json"]), "source_snapshot_id": row["source_snapshot_id"],
        })
    partition_hashes = {row["split_name"]: _partition_hash([item for item in items if item["split_name"] == row["split_name"]]) for row in partitions}
    stored_hashes = {row["split_name"]: row["content_hash"] for row in partitions}
    integrity_status = "verified" if partition_hashes == stored_hashes and stored_hashes.get("test") == dataset["test_partition_hash"] else "blocked"
    if integrity_status != "verified":
        raise DatasetIntegrityError("Dataset partition hash mismatch; model use is blocked.")
    return {
        "dataset_id": dataset["dataset_id"], "contract_version": dataset["contract_version"],
        "feature_schema_version": dataset["feature_schema_version"], "label_schema_version": dataset["label_schema_version"],
        "universe_registry_id": dataset["universe_registry_id"], "source_policy_version": dataset["source_policy_version"],
        "start_date": dataset["start_date"], "end_date": dataset["end_date"], "split_config": json.loads(dataset["split_config_json"]),
        "content_hash": dataset["content_hash"], "status": dataset["status"], "test_partition_hash": dataset["test_partition_hash"],
        "partitions": partitions, "items": items, "integrity_status": integrity_status,
    }


def _environment() -> dict[str, str]:
    return {"python": sys.version.split()[0], "platform": platform.platform(), "contract": MODEL_ARTIFACT_CONTRACT_VERSION}


def _target(item: dict[str, Any]) -> float:
    return float(item["label"]["target"])


def _fit_logistic(rows: list[dict[str, Any]], feature_order: list[str], seed: int) -> dict[str, Any]:
    if not rows:
        raise DatasetIntegrityError("Cannot fit a model without train rows.")
    means: dict[str, float] = {}
    scales: dict[str, float] = {}
    for feature in feature_order:
        values = [float(item["features"].get(feature) or 0.0) for item in rows]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        means[feature] = mean
        scales[feature] = math.sqrt(variance) or 1.0
    weights = [0.0] * len(feature_order)
    prevalence = min(0.999, max(0.001, sum(_target(item) for item in rows) / len(rows)))
    bias = math.log(prevalence / (1 - prevalence))
    learning_rate = 0.05
    for _ in range(350):
        gradients = [0.0] * len(feature_order)
        bias_gradient = 0.0
        for item in rows:
            vector = [(float(item["features"].get(feature) or 0.0) - means[feature]) / scales[feature] for feature in feature_order]
            score = bias + sum(weight * value for weight, value in zip(weights, vector))
            probability = 1 / (1 + math.exp(-max(-30.0, min(30.0, score))))
            error = probability - _target(item)
            for index, value in enumerate(vector):
                gradients[index] += error * value
            bias_gradient += error
        divisor = len(rows)
        weights = [weight - learning_rate * gradient / divisor for weight, gradient in zip(weights, gradients)]
        bias -= learning_rate * bias_gradient / divisor
    return {"kind": "logistic", "seed": seed, "feature_order": feature_order, "means": means, "scales": scales, "weights": [round(value, 10) for value in weights], "bias": round(bias, 10)}


def _predict(artifact: dict[str, Any], item: dict[str, Any]) -> float:
    kind = artifact["kind"]
    if kind == "constant_probability":
        return float(artifact["probability"])
    if kind == "feature_passthrough":
        return max(0.0, min(1.0, float(item["features"].get(artifact["feature_id"]) or 0.0) / 100.0))
    vector = []
    for feature in artifact["feature_order"]:
        mean = float(artifact["means"].get(feature, 0.0))
        scale = float(artifact["scales"].get(feature, 1.0)) or 1.0
        vector.append((float(item["features"].get(feature) or 0.0) - mean) / scale)
    score = float(artifact["bias"]) + sum(weight * value for weight, value in zip(artifact["weights"], vector))
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, score))))


def _metrics(rows: list[dict[str, Any]], artifact: dict[str, Any]) -> dict[str, Any]:
    if not rows:
        return {"sample_count": 0, "brier": None, "accuracy": None, "positive_rate": None, "mean_probability": None}
    predictions = [_predict(artifact, row) for row in rows]
    targets = [_target(row) for row in rows]
    return {
        "sample_count": len(rows),
        "brier": round(sum((prediction - target) ** 2 for prediction, target in zip(predictions, targets)) / len(rows), 8),
        "accuracy": round(sum((prediction >= 0.5) == (target >= 0.5) for prediction, target in zip(predictions, targets)) / len(rows), 8),
        "positive_rate": round(sum(target >= 0.5 for target in targets) / len(rows), 8),
        "mean_probability": round(sum(predictions) / len(predictions), 8),
    }


def register_model_artifact(
    db_path: Path,
    *,
    dataset_id: str,
    model_name: str,
    model_version: str,
    feature_order: list[str],
    train_config: dict[str, Any],
    random_seed: int,
    artifact: dict[str, Any],
    metrics: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    dataset = read_quant_dataset(db_path, dataset_id)
    payload = {
        "contract_version": MODEL_ARTIFACT_CONTRACT_VERSION,
        "model_name": model_name,
        "model_version": model_version,
        "dataset_id": dataset_id,
        "feature_schema_version": dataset["feature_schema_version"],
        "label_schema_version": dataset["label_schema_version"],
        "feature_order": feature_order,
        "train_config": train_config,
        "random_seed": random_seed,
        "environment": _environment(),
        "artifact": artifact,
        "test_partition_hash": dataset["test_partition_hash"],
    }
    artifact_hash = _hash(payload)
    artifact_id = f"qma_{artifact_hash[:24]}"
    created_at = _now()
    with connect(db_path) as conn:
        existing = conn.execute("SELECT artifact_hash FROM quant_model_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        if existing is not None and existing["artifact_hash"] != artifact_hash:
            raise DatasetIntegrityError("Model artifact id collision with a different hash.")
        conn.execute(
            """
            INSERT OR IGNORE INTO quant_model_artifacts(
              artifact_id, model_name, model_version, dataset_id, split_policy,
              feature_schema_version, label_schema_version, feature_order_json,
              train_config_json, random_seed, environment_json, artifact_json,
              artifact_hash, test_partition_hash, status, created_at
            ) VALUES (?, ?, ?, ?, 'train_validation_only_for_selection', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'verified', ?)
            """,
            (artifact_id, model_name, model_version, dataset_id, dataset["feature_schema_version"], dataset["label_schema_version"], _canonical(feature_order), _canonical(train_config), random_seed, _canonical(payload["environment"]), _canonical(artifact), artifact_hash, dataset["test_partition_hash"], created_at),
        )
        for split_name, values in (metrics or {}).items():
            for metric_name, metric_value in values.items():
                numeric = float(metric_value) if isinstance(metric_value, (int, float)) else None
                conn.execute(
                    "INSERT OR IGNORE INTO quant_model_metrics(artifact_id, split_name, metric_name, metric_value, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (artifact_id, split_name, metric_name, numeric, _canonical({"value": metric_value}), created_at),
                )
        conn.commit()
    return model_artifact_detail(db_path, artifact_id)


def run_baseline_suite(db_path: Path, dataset_id: str, *, random_seed: int = 20260817) -> dict[str, Any]:
    dataset = read_quant_dataset(db_path, dataset_id)
    rows = dataset["items"]
    train_rows = [row for row in rows if row["split_name"] == "train"]
    feature_order = sorted({key for row in rows for key in row["features"]})
    models: list[tuple[str, dict[str, Any]]] = [
        ("naive", {"kind": "constant_probability", "probability": round(sum(_target(row) for row in train_rows) / len(train_rows), 10)}),
        ("capital_rotation_rule", {"kind": "feature_passthrough", "feature_id": "capital_rotation_score"}),
        ("logistic", _fit_logistic(train_rows, feature_order, random_seed)),
    ]
    result = []
    for name, artifact in models:
        metrics = {
            split_name: _metrics([row for row in rows if row["split_name"] == split_name], artifact)
            for split_name in ("train", "validation", "test")
        }
        result.append(register_model_artifact(
            db_path,
            dataset_id=dataset_id,
            model_name=name,
            model_version=f"{name}_v0.1.0",
            feature_order=feature_order,
            train_config={"selection_partitions": ["train", "validation"], "test_partition_used_for_selection": False},
            random_seed=random_seed,
            artifact=artifact,
            metrics=metrics,
        ))
    return {"dataset_id": dataset_id, "models": result, "test_partition_used_for_selection": False, "read_only_research": True}


def model_artifact_detail(db_path: Path, artifact_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM quant_model_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown model artifact: {artifact_id}")
        metrics = [dict(item) for item in conn.execute("SELECT * FROM quant_model_metrics WHERE artifact_id = ? ORDER BY split_name, metric_name", (artifact_id,)).fetchall()]
    dataset = read_quant_dataset(db_path, str(row["dataset_id"]))
    if str(row["test_partition_hash"]) != dataset["test_partition_hash"]:
        raise DatasetIntegrityError("Model artifact test partition hash does not match the sealed dataset.")
    return {
        "artifact_id": row["artifact_id"], "model_name": row["model_name"], "model_version": row["model_version"],
        "dataset_id": row["dataset_id"], "feature_schema_version": row["feature_schema_version"], "label_schema_version": row["label_schema_version"],
        "feature_order": json.loads(row["feature_order_json"]), "train_config": json.loads(row["train_config_json"]),
        "random_seed": row["random_seed"], "environment": json.loads(row["environment_json"]),
        "artifact_hash": row["artifact_hash"], "test_partition_hash": row["test_partition_hash"],
        "status": row["status"], "metrics": metrics, "dataset_integrity_status": dataset["integrity_status"],
        "read_only_research": True,
    }


def list_model_artifacts(db_path: Path, dataset_id: str | None = None) -> dict[str, Any]:
    with connect(db_path) as conn:
        if dataset_id:
            rows = conn.execute("SELECT artifact_id, model_name, model_version, dataset_id, artifact_hash, status, created_at FROM quant_model_artifacts WHERE dataset_id = ? ORDER BY created_at DESC", (dataset_id,)).fetchall()
        else:
            rows = conn.execute("SELECT artifact_id, model_name, model_version, dataset_id, artifact_hash, status, created_at FROM quant_model_artifacts ORDER BY created_at DESC").fetchall()
    return {"artifacts": [dict(row) for row in rows], "read_only_research": True}
