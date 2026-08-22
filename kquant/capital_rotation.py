from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .market_availability import MARKET_AVAILABILITY_CONTRACT_VERSION, candle_is_available_at
from .stock_store import connect
from .theme_taxonomy import latest_theme_taxonomy


CAPITAL_ROTATION_VERSION = "capital_rotation_v0.1.0"
SINGLE_MEMBER_WEIGHT_CAP = 0.15
MIN_THEME_MEMBERS = 5
MIN_CAPPED_WEIGHT_MEMBERS = math.ceil(1 / SINGLE_MEMBER_WEIGHT_CAP)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, value)), 4)


def _ema(values: list[float], period: int = 20) -> float | None:
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result += alpha * (value - result)
    return result


def _as_of(value: str | None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _member_weight(count: int) -> float:
    if count <= 0 or count < MIN_CAPPED_WEIGHT_MEMBERS:
        return 0.0
    return 1.0 / count


def _stock_features(rows: list[dict[str, Any]], benchmark: dict[str, float] | None) -> dict[str, Any] | None:
    ordered = sorted(rows, key=lambda row: str(row["open_time"]))
    closes = [float(row["close"]) for row in ordered if _number(row.get("close")) and float(row["close"]) > 0]
    volumes = [max(0.0, float(row.get("volume") or 0.0)) for row in ordered]
    if len(closes) < 21:
        return None
    ret5 = closes[-1] / closes[-6] - 1
    prior_ret5 = closes[-6] / closes[-11] - 1 if len(closes) >= 11 else 0.0
    ret20 = closes[-1] / closes[-21] - 1
    ema20 = _ema(closes, 20)
    dollar_volume = sum(close * volume for close, volume in zip(closes[-20:], volumes[-20:])) / 20
    positive_days = sum(1 for left, right in zip(closes[-10:], closes[-9:]) if right > left)
    benchmark_ret5 = float((benchmark or {}).get("return_5d") or 0.0)
    return {
        "return_5d": ret5,
        "return_20d": ret20,
        "relative_strength_5d": ret5 - benchmark_ret5,
        "acceleration_5d": ret5 - prior_ret5,
        "positive_10d_ratio": positive_days / 9,
        "above_ema20": bool(ema20 is not None and closes[-1] > ema20),
        "average_dollar_volume_20d": dollar_volume,
        "last_open_time": ordered[-1]["open_time"],
        "bar_count": len(ordered),
    }


def _score_members(members: list[dict[str, Any]]) -> tuple[float | None, dict[str, float], float | None]:
    if not members:
        return None, {}, None
    weights = [_member_weight(len(members)) for _ in members]
    total = sum(weights)
    if not total:
        return None, {}, None
    fields = ("return_5d", "relative_strength_5d", "acceleration_5d", "positive_10d_ratio", "average_dollar_volume_20d")
    aggregates = {field: sum(weight * float(member["features"].get(field) or 0.0) for weight, member in zip(weights, members)) for field in fields}
    aggregates["breadth_ratio"] = sum(weight for weight, member in zip(weights, members) if member["features"].get("return_5d", 0) > 0)
    aggregates["above_ema20_ratio"] = sum(weight for weight, member in zip(weights, members) if member["features"].get("above_ema20"))
    dollar_score = _clip(math.log10(max(aggregates["average_dollar_volume_20d"], 1.0)) * 10)
    components = {
        "return_score": _clip(50 + aggregates["return_5d"] * 1000),
        "relative_strength_score": _clip(50 + aggregates["relative_strength_5d"] * 1200),
        "acceleration_score": _clip(50 + aggregates["acceleration_5d"] * 1500),
        "breadth_score": _clip(aggregates["breadth_ratio"] * 100),
        "dollar_volume_score": dollar_score,
        "persistence_score": _clip(aggregates["positive_10d_ratio"] * 100),
    }
    score = (
        components["return_score"] * 0.25
        + components["relative_strength_score"] * 0.20
        + components["acceleration_score"] * 0.15
        + components["breadth_score"] * 0.20
        + components["dollar_volume_score"] * 0.10
        + components["persistence_score"] * 0.10
    )
    top_weight = max(weights) if weights else None
    return round(score, 4), {**components, **aggregates}, top_weight


def _load_daily_rows(db_path: Path, symbols: set[str], cutoff: datetime) -> dict[str, list[dict[str, Any]]]:
    if not symbols:
        return {}
    placeholders = ",".join("?" for _ in symbols)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT symbol, interval, open_time, close, volume, fetched_at, bar_state
            FROM market_candles
            WHERE interval='1d' AND primary_source='longbridge_candles'
              AND provider_status='available' AND bar_state='closed_candle'
              AND open_time <= ?
              AND symbol IN ({placeholders})
            ORDER BY symbol, open_time
            """,
            (cutoff.isoformat(), *sorted(symbols)),
        ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        if candle_is_available_at(item, item["interval"], cutoff):
            result.setdefault(str(item["symbol"]), []).append(item)
    return result


def run_capital_rotation(*, db_path: Path, as_of_time: str | None = None) -> dict[str, Any]:
    taxonomy = latest_theme_taxonomy(db_path)
    if taxonomy.get("status") != "materialized":
        raise ValueError("A materialized theme taxonomy is required before Capital Rotation.")
    cutoff = _as_of(as_of_time)
    with connect(db_path) as conn:
        membership_rows = conn.execute(
            """
            SELECT definition_id, symbol, confidence, evidence_json
            FROM theme_memberships
            WHERE run_id=? AND dimension_type='theme' AND review_status='auto_mapped' AND definition_id != 'theme.unmapped'
            ORDER BY definition_id, symbol
            """,
            (taxonomy["run_id"],),
        ).fetchall()
    by_definition: dict[str, list[dict[str, Any]]] = {}
    for row in membership_rows:
        by_definition.setdefault(str(row["definition_id"]), []).append(dict(row))
    symbols = {str(row["symbol"]) for row in membership_rows}
    symbols.add("SPY")
    daily = _load_daily_rows(db_path, symbols, cutoff)
    benchmark_rows = daily.get("SPY", [])
    benchmark_closes = [float(row["close"]) for row in benchmark_rows]
    benchmark = {"return_5d": benchmark_closes[-1] / benchmark_closes[-6] - 1} if len(benchmark_closes) >= 6 else {"return_5d": 0.0}
    score_rows: list[dict[str, Any]] = []
    member_rows: list[dict[str, Any]] = []
    for definition_id, entries in by_definition.items():
        prepared: list[dict[str, Any]] = []
        for entry in entries:
            features = _stock_features(daily.get(str(entry["symbol"]), []), benchmark)
            if features is not None:
                prepared.append({"symbol": str(entry["symbol"]), "features": features, "confidence": float(entry["confidence"]), "evidence": json.loads(entry["evidence_json"])})
        member_count = len(entries)
        if len(prepared) < MIN_THEME_MEMBERS:
            score_rows.append({"definition_id": definition_id, "member_count": member_count, "eligible_member_count": len(prepared), "score": None, "status": "insufficient_members_or_data", "data_quality": "limited", "top_member_contribution": None, "features": {"min_members": MIN_THEME_MEMBERS, "single_member_weight_cap": SINGLE_MEMBER_WEIGHT_CAP}})
            continue
        if len(prepared) < MIN_CAPPED_WEIGHT_MEMBERS:
            score_rows.append({"definition_id": definition_id, "member_count": member_count, "eligible_member_count": len(prepared), "score": None, "status": "concentration_limited", "data_quality": "limited", "top_member_contribution": None, "features": {"min_members": MIN_THEME_MEMBERS, "minimum_members_for_weight_cap": MIN_CAPPED_WEIGHT_MEMBERS, "single_member_weight_cap": SINGLE_MEMBER_WEIGHT_CAP}})
            continue
        score, features, top_weight = _score_members(prepared)
        top = max(prepared, key=lambda item: float(item["features"].get("return_5d") or 0.0))
        without_top = [item for item in prepared if item is not top]
        stress_score, _, _ = _score_members(without_top) if len(without_top) >= MIN_THEME_MEMBERS else (None, {}, None)
        features["stress_without_top_member_score"] = stress_score
        features["stress_direction_flip"] = bool(stress_score is not None and (float(score or 0) - 50) * (stress_score - 50) < 0)
        features["stress_unreasonable_flip"] = bool(
            stress_score is not None
            and ((float(score or 0) >= 60 and stress_score < 50) or (float(score or 0) <= 40 and stress_score > 50))
        )
        score_rows.append({"definition_id": definition_id, "member_count": member_count, "eligible_member_count": len(prepared), "score": score, "status": "eligible", "data_quality": "caution" if features["stress_direction_flip"] else "available", "top_member_contribution": top_weight, "features": features})
        normalized_weight = _member_weight(len(prepared))
        for item in prepared:
            member_rows.append({"definition_id": definition_id, "symbol": item["symbol"], "weight": normalized_weight, "contribution": normalized_weight * float(score or 0), "features": item["features"], "data_quality": "available"})
    ranked = sorted((row for row in score_rows if row["score"] is not None), key=lambda row: (-float(row["score"]), row["definition_id"]))
    rank_lookup = {row["definition_id"]: index for index, row in enumerate(ranked, 1)}
    for row in score_rows:
        row["rank"] = rank_lookup.get(row["definition_id"])
    canonical = {"version": CAPITAL_ROTATION_VERSION, "taxonomy_run_id": taxonomy["run_id"], "as_of_time": cutoff.isoformat(), "scores": score_rows, "members": member_rows}
    content_hash = hashlib.sha256(json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    run_id = f"crr_{content_hash[:20]}"
    summary = {
        "version": CAPITAL_ROTATION_VERSION,
        "taxonomy_run_id": taxonomy["run_id"],
        "as_of_time": cutoff.isoformat(),
        "theme_count": len(score_rows),
        "ranked_theme_count": len(ranked),
        "min_theme_members": MIN_THEME_MEMBERS,
        "single_member_weight_cap": SINGLE_MEMBER_WEIGHT_CAP,
        "minimum_members_for_weight_cap": MIN_CAPPED_WEIGHT_MEMBERS,
        "data_source": "longbridge_candles",
        "availability_basis": MARKET_AVAILABILITY_CONTRACT_VERSION,
        "future_data_used": False,
        "stress_direction_flips": sum(1 for row in score_rows if row["features"].get("stress_direction_flip")),
        "stress_unreasonable_flips": sum(1 for row in score_rows if row["features"].get("stress_unreasonable_flip")),
    }
    with connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO capital_rotation_runs(run_id, taxonomy_run_id, as_of_time, content_hash, status, summary_json, created_at) VALUES (?, ?, ?, ?, 'materialized', ?, ?)", (run_id, taxonomy["run_id"], cutoff.isoformat(), content_hash, json.dumps(summary, ensure_ascii=True, sort_keys=True), _now()))
        conn.executemany("INSERT OR IGNORE INTO capital_rotation_scores(run_id, definition_id, dimension_type, rank_value, member_count, eligible_member_count, score, status, data_quality, top_member_contribution, features_json, created_at) VALUES (?, ?, 'theme', ?, ?, ?, ?, ?, ?, ?, ?, ?)", [(run_id, row["definition_id"], row["rank"], row["member_count"], row["eligible_member_count"], row["score"], row["status"], row["data_quality"], row["top_member_contribution"], json.dumps(row["features"], ensure_ascii=True, sort_keys=True), _now()) for row in score_rows])
        conn.executemany("INSERT OR IGNORE INTO capital_rotation_members(run_id, definition_id, symbol, weight, contribution, features_json, data_quality) VALUES (?, ?, ?, ?, ?, ?, ?)", [(run_id, row["definition_id"], row["symbol"], row["weight"], row["contribution"], json.dumps(row["features"], ensure_ascii=True, sort_keys=True), row["data_quality"]) for row in member_rows])
        conn.commit()
    return {"run_id": run_id, "content_hash": content_hash, "summary": summary, "scores": score_rows}


def latest_capital_rotation(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        run = conn.execute("SELECT * FROM capital_rotation_runs ORDER BY as_of_time DESC, created_at DESC LIMIT 1").fetchone()
        if run is None:
            return {"status": "not_materialized", "scores": [], "summary": {}}
        rows = conn.execute("SELECT * FROM capital_rotation_scores WHERE run_id=? ORDER BY rank_value IS NULL, rank_value, definition_id", (run["run_id"],)).fetchall()
    taxonomy = latest_theme_taxonomy(db_path)
    taxonomy_aligned = str(run["taxonomy_run_id"]) == str(taxonomy.get("run_id") or "") and taxonomy.get("status") == "materialized"
    scores = []
    for row in rows:
        item = dict(row)
        item["features"] = json.loads(item.pop("features_json"))
        scores.append(item)
    return {
        "status": str(run["status"]) if taxonomy_aligned else "stale_taxonomy",
        "run_id": run["run_id"],
        "taxonomy_run_id": run["taxonomy_run_id"],
        "as_of_time": run["as_of_time"],
        "summary": json.loads(run["summary_json"]),
        "scores": scores,
        "taxonomy_alignment": {
            "aligned": taxonomy_aligned,
            "rotation_taxonomy_run_id": run["taxonomy_run_id"],
            "latest_taxonomy_run_id": taxonomy.get("run_id"),
        },
        "read_only_research": True,
    }


def capital_rotation_detail(db_path: Path, definition_id: str) -> dict[str, Any]:
    payload = latest_capital_rotation(db_path)
    row = next((item for item in payload.get("scores", []) if item["definition_id"] == definition_id), None)
    if row is None:
        raise ValueError(f"Unknown or unranked theme: {definition_id}")
    with connect(db_path) as conn:
        members = [dict(item) for item in conn.execute("SELECT symbol, weight, contribution, features_json, data_quality FROM capital_rotation_members WHERE run_id=? AND definition_id=? ORDER BY contribution DESC, symbol", (payload["run_id"], definition_id)).fetchall()]
    for member in members:
        member["features"] = json.loads(member.pop("features_json"))
    return {"run_id": payload["run_id"], "score": row, "members": members, "read_only_research": True}
