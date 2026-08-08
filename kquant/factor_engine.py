from __future__ import annotations

"""Versioned, inspectable factor snapshots for the canonical swing strategy."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .stock_store import connect


FACTOR_REGISTRY_VERSION = "factor_registry_v1"


FACTOR_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "factor_id": "daily_ema_stack",
        "group": "trend",
        "label": "Daily EMA structure",
        "formula": "close > EMA20 > EMA50 > EMA200",
        "timeframe": "1D",
        "source": "longbridge_candles",
        "active_in_score": True,
    },
    {
        "factor_id": "daily_trend_return_5d",
        "group": "trend",
        "label": "Five-day trend return",
        "formula": "close / close[-5] - 1",
        "timeframe": "1D",
        "source": "longbridge_candles",
        "active_in_score": True,
    },
    {
        "factor_id": "hourly_ema_structure",
        "group": "confirmation",
        "label": "Hourly EMA confirmation",
        "formula": "close_1h > EMA20_1h > EMA50_1h",
        "timeframe": "1H",
        "source": "longbridge_candles",
        "active_in_score": True,
    },
    {
        "factor_id": "hourly_momentum_7h",
        "group": "confirmation",
        "label": "Hourly momentum",
        "formula": "close_1h / close_1h[-7] - 1",
        "timeframe": "1H",
        "source": "longbridge_candles",
        "active_in_score": True,
    },
    {
        "factor_id": "relative_volume_20d",
        "group": "volume",
        "label": "Relative volume",
        "formula": "latest volume / prior 20-day mean volume",
        "timeframe": "1D",
        "source": "longbridge_candles",
        "active_in_score": True,
    },
    {
        "factor_id": "atr_risk_20d",
        "group": "volatility_risk",
        "label": "ATR risk",
        "formula": "ATR percent over latest 20 daily candles",
        "timeframe": "1D",
        "source": "longbridge_candles",
        "active_in_score": True,
    },
    {
        "factor_id": "ema20_extension",
        "group": "volatility_risk",
        "label": "EMA20 extension",
        "formula": "close / EMA20 - 1",
        "timeframe": "1D",
        "source": "longbridge_candles",
        "active_in_score": True,
    },
    {
        "factor_id": "relative_strength_spy_20d",
        "group": "relative_strength",
        "label": "Relative strength versus SPY",
        "formula": "stock 20-day return - SPY 20-day return",
        "timeframe": "1D",
        "source": "longbridge_candles",
        "active_in_score": False,
    },
    {
        "factor_id": "relative_strength_qqq_20d",
        "group": "relative_strength",
        "label": "Relative strength versus QQQ",
        "formula": "stock 20-day return - QQQ 20-day return",
        "timeframe": "1D",
        "source": "longbridge_candles",
        "active_in_score": False,
    },
    {
        "factor_id": "rsi14_context",
        "group": "momentum_pullback",
        "label": "RSI context",
        "formula": "RSI(14)",
        "timeframe": "1D",
        "source": "longbridge_candles",
        "active_in_score": False,
    },
    {
        "factor_id": "vwap_reclaim_1h",
        "group": "momentum_pullback",
        "label": "Hourly VWAP reclaim",
        "formula": "close_1h >= VWAP20_1h",
        "timeframe": "1H",
        "source": "longbridge_candles",
        "active_in_score": False,
    },
    {
        "factor_id": "market_breadth",
        "group": "market_regime",
        "label": "Market breadth",
        "formula": "universe participation above EMA20/50/200",
        "timeframe": "1D",
        "source": "kquant_market_breadth",
        "active_in_score": False,
    },
    {
        "factor_id": "corporate_event_window",
        "group": "event_risk",
        "label": "Corporate event window",
        "formula": "days to known earnings, split, dividend, or corporate action",
        "timeframe": "event",
        "source": "event_calendar",
        "active_in_score": False,
    },
)


def factor_definitions() -> list[dict[str, Any]]:
    return [{**item, "registry_version": FACTOR_REGISTRY_VERSION} for item in FACTOR_DEFINITIONS]


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _entry(
    definition: dict[str, Any],
    *,
    value: Any,
    contribution: float | None = None,
    status: str = "available",
    as_of: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    return {
        **definition,
        "value": value,
        "contribution": round(contribution, 4) if contribution is not None else None,
        "status": status,
        "as_of": as_of,
        "note": note,
    }


def build_factor_snapshot(
    signal: dict[str, Any],
    market_regime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a transparent factor record without calculating any new market data."""

    definitions = {item["factor_id"]: item for item in FACTOR_DEFINITIONS}
    features = signal.get("features") or {}
    score = signal.get("score_breakdown") or {}
    scoring_factors = score.get("factors") or {}
    deductions = score.get("deductions") or {}
    packet = signal.get("ai_feature_packet_v3") or {}
    relative = packet.get("relative_strength_context") or {}
    technical = (signal.get("ai_feature_packet_v2") or {}).get("technical_state") or {}
    confirmation = technical.get("confirmation") or {}
    data_status = signal.get("data_status") or {}
    market = market_regime or {}
    as_of = str(data_status.get("confirmation_candle_time") or data_status.get("daily_candle_time") or "")

    trend_parts = scoring_factors.get("trend") or {}
    trigger_parts = scoring_factors.get("trigger") or {}
    stack_contribution = sum(_number(trend_parts.get(key)) or 0.0 for key in (
        "close_above_ema20", "ema20_above_ema50", "ema50_above_ema200"
    ))
    hourly_structure_contribution = sum(_number(trigger_parts.get(key)) or 0.0 for key in (
        "close_above_hourly_ema20", "hourly_ema20_above_ema50"
    ))
    atr_deduction = _number(deductions.get("atr")) or 0.0
    extension_deduction = (_number(deductions.get("extension_high")) or 0.0) + (_number(deductions.get("extension_low")) or 0.0)

    entries = [
        _entry(
            definitions["daily_ema_stack"],
            value=bool(stack_contribution >= 42), contribution=stack_contribution, as_of=as_of,
            note="Contribution is the sum of the three daily EMA alignment score components.",
        ),
        _entry(
            definitions["daily_trend_return_5d"], value=features.get("trend_return_5d_pct"),
            contribution=_number(trend_parts.get("trend_return")), as_of=as_of,
        ),
        _entry(
            definitions["hourly_ema_structure"], value=bool(hourly_structure_contribution >= 19),
            contribution=hourly_structure_contribution, as_of=as_of,
        ),
        _entry(
            definitions["hourly_momentum_7h"], value=features.get("one_hour_momentum_pct"),
            contribution=_number(trigger_parts.get("hourly_momentum")), as_of=as_of,
        ),
        _entry(
            definitions["relative_volume_20d"], value=features.get("volume_ratio"),
            contribution=_number(score.get("volume_score")), as_of=as_of,
        ),
        _entry(
            definitions["atr_risk_20d"], value=features.get("atr_pct"), contribution=-atr_deduction, as_of=as_of,
        ),
        _entry(
            definitions["ema20_extension"], value=features.get("extension_pct"), contribution=-extension_deduction, as_of=as_of,
        ),
        _entry(
            definitions["relative_strength_spy_20d"], value=relative.get("stock_minus_spy_pct"),
            as_of=as_of, note="Context factor; not yet included in the live score.",
        ),
        _entry(
            definitions["relative_strength_qqq_20d"], value=relative.get("stock_minus_qqq_pct"),
            as_of=as_of, note="Context factor; not yet included in the live score.",
        ),
        _entry(
            definitions["rsi14_context"], value=features.get("rsi14"), as_of=as_of,
            note="Context factor; not yet included in the live score.",
        ),
        _entry(
            definitions["vwap_reclaim_1h"], value=(confirmation.get("close_vs_vwap20_pct") is not None and (confirmation.get("close_vs_vwap20_pct") or 0) >= 0),
            as_of=as_of, note="Context factor; not yet included in the live score.",
        ),
        _entry(
            definitions["market_breadth"], value=(market.get("breadth") or {}).get("participation_score"),
            status="available" if (market.get("breadth") or {}).get("status") == "available" else "unavailable", as_of=as_of,
            note="Breadth is usable only after sufficient Longbridge coverage; otherwise it cannot support an action.",
        ),
        _entry(
            definitions["corporate_event_window"], value=(signal.get("event_context") or {}).get("nearest_event"),
            status="available" if signal.get("event_context") else "unavailable", as_of=as_of,
            note="Event-calendar ingestion is pending; unavailable factors cannot support an action.",
        ),
    ]
    supporting = sorted(
        (entry for entry in entries if (entry.get("contribution") or 0) > 0),
        key=lambda entry: float(entry["contribution"]), reverse=True,
    )[:3]
    opposing = sorted(
        (entry for entry in entries if (entry.get("contribution") or 0) < 0),
        key=lambda entry: float(entry["contribution"]),
    )[:3]
    blockers = [
        entry for entry in entries
        if entry["status"] != "available"
    ]
    data_blockers = list(data_status.get("data_quality_hard_vetoes") or [])
    payload = {
        "registry_version": FACTOR_REGISTRY_VERSION,
        "strategy_version": signal.get("strategy_version", "unversioned"),
        "strategy_config_hash": signal.get("strategy_config_hash", ""),
        "symbol": signal.get("symbol"),
        "profile": signal.get("profile_name"),
        "as_of": as_of,
        "factors": entries,
        "supporting_factors": [entry["factor_id"] for entry in supporting],
        "opposing_factors": [entry["factor_id"] for entry in opposing],
        "unavailable_factors": [entry["factor_id"] for entry in blockers],
        "data_blockers": data_blockers,
        "score": score.get("total_score", signal.get("score")),
        "market_regime": market.get("regime"),
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    payload["factor_snapshot_hash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return payload


def decision_evidence(snapshot: dict[str, Any], signal: dict[str, Any]) -> dict[str, Any]:
    entries = {entry["factor_id"]: entry for entry in snapshot.get("factors") or []}
    return {
        "factor_snapshot_hash": snapshot.get("factor_snapshot_hash"),
        "factor_registry_version": snapshot.get("registry_version"),
        "supporting_factors": [entries[item] for item in snapshot.get("supporting_factors") or [] if item in entries],
        "opposing_factors": [entries[item] for item in snapshot.get("opposing_factors") or [] if item in entries],
        "unavailable_factors": [entries[item] for item in snapshot.get("unavailable_factors") or [] if item in entries],
        "data_blockers": list(snapshot.get("data_blockers") or []),
        "rule_level": signal.get("level"),
        "rule_score": signal.get("score"),
        "research_only": True,
    }


def persist_factor_snapshot(db_path: Any, snapshot: dict[str, Any]) -> None:
    """Persist snapshots for audit; factor definitions are immutable by registry version."""

    recorded_at = datetime.now(UTC).isoformat()
    with connect(db_path) as conn:
        for definition in factor_definitions():
            conn.execute(
                """
                INSERT INTO factor_definitions(factor_id, registry_version, definition_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(factor_id, registry_version) DO NOTHING
                """,
                (definition["factor_id"], FACTOR_REGISTRY_VERSION, json.dumps(definition, ensure_ascii=True), recorded_at),
            )
        conn.execute(
            """
            INSERT INTO factor_snapshots(
              snapshot_hash, symbol, profile, strategy_version, strategy_config_hash,
              as_of_time, registry_version, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_hash) DO NOTHING
            """,
            (
                snapshot["factor_snapshot_hash"], str(snapshot.get("symbol") or ""),
                str(snapshot.get("profile") or ""), str(snapshot.get("strategy_version") or ""),
                str(snapshot.get("strategy_config_hash") or ""), str(snapshot.get("as_of") or ""),
                FACTOR_REGISTRY_VERSION, json.dumps(snapshot, ensure_ascii=True), recorded_at,
            ),
        )
        conn.commit()
