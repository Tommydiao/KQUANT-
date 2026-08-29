from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .capital_rotation import latest_capital_rotation
from .stock_store import connect
from .theme_taxonomy import latest_theme_taxonomy


LEADERSHIP_VERSION = "leadership_engine_v1.0.0"
LEADERSHIP_STATES = ("Leader", "Emerging", "Neutral", "Weakening")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, value)), 4)


def _state(score: float, theme_relative_strength: float, acceleration: float) -> str:
    if score >= 72 and theme_relative_strength >= 0.01:
        return "Leader"
    if score >= 58 and (theme_relative_strength > 0 or acceleration > 0):
        return "Emerging"
    if score <= 42 or (theme_relative_strength <= -0.02 and acceleration < 0):
        return "Weakening"
    return "Neutral"


def _volatility_bucket(features: dict[str, Any]) -> str:
    return "high_proxy" if abs(_number(features.get("return_5d"))) >= 0.08 or abs(_number(features.get("acceleration_5d"))) >= 0.05 else "normal_proxy"


def _theme_members(db_path: Path, rotation_run_id: str) -> dict[str, list[dict[str, Any]]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT definition_id, symbol, weight, contribution, features_json, data_quality FROM capital_rotation_members WHERE run_id = ? ORDER BY definition_id, symbol",
            (rotation_run_id,),
        ).fetchall()
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        item = dict(row)
        item["features"] = json.loads(item.pop("features_json"))
        result[str(item["definition_id"])].append(item)
    return result


def run_leadership(db_path: Path) -> dict[str, Any]:
    """Materialize a same-timestamp leadership cross-section from Capital Rotation.

    This consumes only the already sealed Longbridge rotation snapshot. It does
    not read Theme Prediction outputs, future returns, or current ad hoc tags.
    """

    rotation = latest_capital_rotation(db_path)
    if rotation.get("status") != "materialized":
        raise ValueError("A materialized Capital Rotation snapshot is required before Leadership.")
    if rotation.get("summary", {}).get("future_data_used"):
        raise ValueError("Capital Rotation snapshot is marked as using future data.")
    rotation_run_id = str(rotation["run_id"])
    taxonomy_run_id = str(rotation["taxonomy_run_id"])
    as_of_time = str(rotation["as_of_time"])
    by_theme = _theme_members(db_path, rotation_run_id)
    score_rows: list[dict[str, Any]] = []
    strata: dict[str, dict[str, dict[str, int]]] = {"theme_size": defaultdict(lambda: defaultdict(int)), "volatility": defaultdict(lambda: defaultdict(int)), "data_quality": defaultdict(lambda: defaultdict(int))}
    for definition_id, members in sorted(by_theme.items()):
        if len(members) < 2:
            continue
        total_weight = sum(_number(member.get("weight")) for member in members) or float(len(members))
        theme_return = sum(_number(member["features"].get("return_5d")) * (_number(member.get("weight")) or 1.0) for member in members) / total_weight
        theme_volume = sum(_number(member["features"].get("average_dollar_volume_20d")) for member in members) / len(members)
        prepared: list[dict[str, Any]] = []
        for member in members:
            features = member["features"]
            theme_relative = _number(features.get("return_5d")) - theme_return
            market_relative = _number(features.get("relative_strength_5d"))
            volume_ratio = _number(features.get("average_dollar_volume_20d")) / theme_volume if theme_volume > 0 else 1.0
            volume_confirmation = _clip(50 + (volume_ratio - 1.0) * 50)
            persistence = _clip(_number(features.get("positive_10d_ratio")) * 100)
            theme_score = _clip(50 + theme_relative * 1500)
            market_score = _clip(50 + market_relative * 1200)
            acceleration = _number(features.get("acceleration_5d"))
            score = _clip(theme_score * 0.35 + market_score * 0.25 + volume_confirmation * 0.20 + persistence * 0.20)
            state = _state(score, theme_relative, acceleration)
            volatility = _volatility_bucket(features)
            item = {
                "definition_id": definition_id,
                "symbol": str(member["symbol"]),
                "score": score,
                "state": state,
                "theme_relative_strength": round(theme_relative, 8),
                "market_relative_strength": round(market_relative, 8),
                "volume_confirmation": volume_confirmation,
                "persistence_score": persistence,
                "volatility_bucket": volatility,
                "data_quality": str(member.get("data_quality") or "available"),
                "features": {
                    "return_5d": _number(features.get("return_5d")),
                    "acceleration_5d": acceleration,
                    "positive_10d_ratio": _number(features.get("positive_10d_ratio")),
                    "above_ema20": bool(features.get("above_ema20")),
                    "average_dollar_volume_20d": _number(features.get("average_dollar_volume_20d")),
                    "theme_return_5d": round(theme_return, 8),
                    "volume_ratio_vs_theme": round(volume_ratio, 8),
                    "as_of_time": as_of_time,
                    "source": "capital_rotation_members",
                },
            }
            prepared.append(item)
        for rank, item in enumerate(sorted(prepared, key=lambda row: (-row["score"], row["symbol"])), 1):
            item["rank"] = rank
            score_rows.append(item)
            size_bucket = "small" if len(members) < 10 else "medium" if len(members) < 25 else "large"
            strata["theme_size"][size_bucket][item["state"]] += 1
            strata["volatility"][item["volatility_bucket"]][item["state"]] += 1
            strata["data_quality"][item["data_quality"]][item["state"]] += 1
    state_counts = Counter(item["state"] for item in score_rows)
    summary = {
        "version": LEADERSHIP_VERSION,
        "rotation_run_id": rotation_run_id,
        "taxonomy_run_id": taxonomy_run_id,
        "as_of_time": as_of_time,
        "future_prediction_used": False,
        "future_data_used": False,
        "member_count": len(score_rows),
        "unique_symbol_count": len({item["symbol"] for item in score_rows}),
        "theme_membership_count": len(score_rows),
        "theme_count": len({item["definition_id"] for item in score_rows}),
        "state_counts": dict(sorted(state_counts.items())),
        "strata": {name: {bucket: dict(counts) for bucket, counts in buckets.items()} for name, buckets in strata.items()},
        "concentration": {
            "max_theme_member_weight": max((_number(member.get("weight")) for members in by_theme.values() for member in members), default=None),
            "leader_count": state_counts.get("Leader", 0),
            "single_symbol_profit_contribution_tested": False,
        },
        "data_source": "longbridge_candles",
        "read_only_research": True,
    }
    canonical = {"version": LEADERSHIP_VERSION, "rotation_run_id": rotation_run_id, "taxonomy_run_id": taxonomy_run_id, "as_of_time": as_of_time, "rows": score_rows, "summary": summary}
    content_hash = _hash(canonical)
    run_id = f"ldr_{content_hash[:20]}"
    created_at = _now()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO leadership_runs(run_id, rotation_run_id, taxonomy_run_id, as_of_time, content_hash, status, summary_json, created_at) VALUES (?, ?, ?, ?, ?, 'materialized', ?, ?)",
            (run_id, rotation_run_id, taxonomy_run_id, as_of_time, content_hash, _canonical(summary), created_at),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO leadership_scores(run_id, definition_id, symbol, rank_value, state, score, theme_relative_strength, market_relative_strength, volume_confirmation, persistence_score, volatility_bucket, data_quality, features_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (run_id, item["definition_id"], item["symbol"], item["rank"], item["state"], item["score"], item["theme_relative_strength"], item["market_relative_strength"], item["volume_confirmation"], item["persistence_score"], item["volatility_bucket"], item["data_quality"], _canonical(item["features"]), created_at)
                for item in score_rows
            ],
        )
        conn.commit()
    return leadership_detail(db_path, run_id)


def _decode_score(row: dict[str, Any]) -> dict[str, Any]:
    row["features"] = json.loads(row.pop("features_json"))
    return row


def leadership_detail(db_path: Path, run_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        run = conn.execute("SELECT * FROM leadership_runs WHERE run_id = ?", (run_id,)).fetchone()
        if run is None:
            raise ValueError(f"Unknown leadership run: {run_id}")
        rows = [_decode_score(dict(row)) for row in conn.execute("SELECT * FROM leadership_scores WHERE run_id = ? ORDER BY definition_id, rank_value, symbol", (run_id,)).fetchall()]
    return {
        "status": run["status"],
        "run_id": run["run_id"],
        "rotation_run_id": run["rotation_run_id"],
        "taxonomy_run_id": run["taxonomy_run_id"],
        "as_of_time": run["as_of_time"],
        "content_hash": run["content_hash"],
        "summary": json.loads(run["summary_json"]),
        "leaders": rows,
        "read_only_research": True,
    }


def latest_leadership(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        run = conn.execute("SELECT run_id FROM leadership_runs ORDER BY as_of_time DESC, created_at DESC LIMIT 1").fetchone()
    if run is None:
        return {"status": "not_materialized", "leaders": [], "summary": {}, "read_only_research": True}
    detail = leadership_detail(db_path, str(run["run_id"]))
    rotation = latest_capital_rotation(db_path)
    aligned = (
        rotation.get("status") == "materialized"
        and str(detail.get("rotation_run_id") or "") == str(rotation.get("run_id") or "")
        and str(detail.get("taxonomy_run_id") or "") == str(rotation.get("taxonomy_run_id") or "")
    )
    if aligned:
        return detail
    return {
        **detail,
        "status": "stale_rotation",
        "leaders": [],
        "lineage_alignment": {
            "aligned": False,
            "leadership_rotation_run_id": detail.get("rotation_run_id"),
            "latest_rotation_run_id": rotation.get("run_id"),
            "leadership_taxonomy_run_id": detail.get("taxonomy_run_id"),
            "latest_taxonomy_run_id": rotation.get("taxonomy_run_id"),
        },
        "read_only_research": True,
    }


def theme_leaders(db_path: Path, definition_id: str) -> dict[str, Any]:
    payload = latest_leadership(db_path)
    if payload.get("status") != "materialized":
        taxonomy = latest_theme_taxonomy(db_path)
        if not any(item.get("definition_id") == definition_id for item in taxonomy.get("definitions", [])):
            raise ValueError(f"Unknown theme definition: {definition_id}")
        return {"status": "not_materialized", "definition_id": definition_id, "leaders": [], "read_only_research": True}
    leaders = [row for row in payload["leaders"] if row["definition_id"] == definition_id]
    if not leaders:
        raise ValueError(f"Unknown or unranked theme: {definition_id}")
    return {
        "status": payload["status"],
        "run_id": payload["run_id"],
        "definition_id": definition_id,
        "as_of_time": payload["as_of_time"],
        "leaders": leaders,
        "summary": payload["summary"],
        "read_only_research": True,
    }
