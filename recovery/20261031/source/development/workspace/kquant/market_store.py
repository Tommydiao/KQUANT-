from __future__ import annotations

import math
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .stock_store import connect


DATASET_VERSION = "market_data_contract_v1"
SOURCE_PRIORITY = {
    "longbridge_candles": 40,
    "stale_longbridge_cache": 30,
    "live_yahoo_chart": 10,
    "yahoo_public_fallback": 10,
    "stale_yahoo_chart_cache": 5,
    "fixture_read_only": 0,
}


def persist_canonical_candles(db_path: Path, payload: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    """Upsert one logical candle and retain all provider observations.

    The legacy `stock_candles` table remains available for compatibility. This
    store is the canonical, source-aware lineage layer used by new data-quality
    and validation work.
    """

    source = str(payload.get("source_type") or "unknown")
    provider_status = str(payload.get("provider_status") or "unknown")
    provider_symbol = str(payload.get("provider_symbol") or payload.get("symbol") or "")
    adjustment_mode = str(payload.get("adjustment_mode") or _default_adjustment_mode(source))
    dataset_version = str(payload.get("dataset_version") or DATASET_VERSION)
    freshness_seconds = _int(payload.get("freshness_seconds"), 0)
    accepted = rejected = 0
    reasons: list[str] = []
    with connect(db_path) as conn:
        for raw in payload.get("candles") or []:
            candle, reason = _normalize_candle(raw, fetched_at)
            if candle is None:
                rejected += 1
                reasons.append(reason)
                continue
            key = (
                str(payload.get("symbol") or ""),
                str(payload.get("interval") or ""),
                candle["open_time"],
                adjustment_mode,
                dataset_version,
            )
            conn.execute(
                """
                INSERT INTO market_candle_observations(
                  symbol, interval, open_time, adjustment_mode, dataset_version,
                  source, provider_symbol, provider_status, freshness_seconds,
                  bar_state, open, high, low, close, volume, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, interval, open_time, adjustment_mode, dataset_version, source)
                DO UPDATE SET
                  provider_symbol=excluded.provider_symbol,
                  provider_status=excluded.provider_status,
                  freshness_seconds=excluded.freshness_seconds,
                  bar_state=excluded.bar_state,
                  open=excluded.open,
                  high=excluded.high,
                  low=excluded.low,
                  close=excluded.close,
                  volume=excluded.volume,
                  fetched_at=excluded.fetched_at
                """,
                (
                    *key,
                    source,
                    provider_symbol,
                    provider_status,
                    freshness_seconds,
                    candle["bar_state"],
                    candle["open"],
                    candle["high"],
                    candle["low"],
                    candle["close"],
                    candle["volume"],
                    fetched_at,
                ),
            )
            existing = conn.execute(
                """
                SELECT primary_source FROM market_candles
                WHERE symbol=? AND interval=? AND open_time=? AND adjustment_mode=? AND dataset_version=?
                """,
                key,
            ).fetchone()
            previous = conn.execute(
                """
                SELECT close FROM market_candles
                WHERE symbol=? AND interval=? AND adjustment_mode=? AND dataset_version=? AND open_time < ?
                ORDER BY open_time DESC
                LIMIT 1
                """,
                (key[0], key[1], key[3], key[4], key[2]),
            ).fetchone()
            existing_source = str(existing["primary_source"]) if existing else ""
            if existing is None or _priority(source) >= _priority(existing_source):
                conn.execute(
                    """
                    INSERT INTO market_candles(
                      symbol, interval, open_time, adjustment_mode, dataset_version,
                      primary_source, provider_symbol, provider_status,
                      freshness_seconds, bar_state, open, high, low, close, volume,
                      fetched_at, first_seen_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, interval, open_time, adjustment_mode, dataset_version)
                    DO UPDATE SET
                      primary_source=excluded.primary_source,
                      provider_symbol=excluded.provider_symbol,
                      provider_status=excluded.provider_status,
                      freshness_seconds=excluded.freshness_seconds,
                      bar_state=excluded.bar_state,
                      open=excluded.open,
                      high=excluded.high,
                      low=excluded.low,
                      close=excluded.close,
                      volume=excluded.volume,
                      fetched_at=excluded.fetched_at,
                      updated_at=excluded.updated_at
                    """,
                    (
                        *key,
                        source,
                        provider_symbol,
                        provider_status,
                        freshness_seconds,
                        candle["bar_state"],
                        candle["open"],
                        candle["high"],
                        candle["low"],
                        candle["close"],
                        candle["volume"],
                        fetched_at,
                        fetched_at,
                        fetched_at,
                    ),
                )
            action = _split_like_action(previous["close"] if previous else None, candle)
            if action:
                conn.execute(
                    """
                    INSERT INTO corporate_action_events(
                      symbol, effective_time, interval, adjustment_mode, dataset_version,
                      action_type, price_ratio, source, status, details_json, detected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'caution', ?, ?)
                    ON CONFLICT(symbol, effective_time, interval, adjustment_mode, dataset_version, action_type)
                    DO UPDATE SET
                      price_ratio=excluded.price_ratio,
                      source=excluded.source,
                      status=excluded.status,
                      details_json=excluded.details_json,
                      detected_at=excluded.detected_at
                    """,
                    (
                        key[0], key[2], key[1], key[3], key[4],
                        action["action_type"], action["price_ratio"], source,
                        json.dumps(action, sort_keys=True), fetched_at,
                    ),
                )
            accepted += 1
        conn.commit()
    return {"accepted": accepted, "rejected": rejected, "reasons": reasons[:10]}


def _normalize_candle(raw: Any, fetched_at: str) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(raw, dict):
        return None, "candle is not an object"
    try:
        open_time = datetime.fromisoformat(str(raw.get("open_time") or "").replace("Z", "+00:00"))
    except ValueError:
        return None, "candle open_time is invalid"
    if open_time.tzinfo is None:
        return None, "candle open_time has no timezone"
    try:
        fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        fetched = datetime.now(UTC)
    open_time = open_time.astimezone(UTC)
    if open_time > fetched.astimezone(UTC) + timedelta(minutes=5):
        return None, "candle open_time is in the future"
    values = {key: _number(raw.get(key)) for key in ("open", "high", "low", "close", "volume")}
    if any(value is None for value in values.values()):
        return None, "candle contains a non-finite value"
    if min(values["open"], values["high"], values["low"], values["close"]) <= 0 or values["volume"] < 0:
        return None, "candle has non-positive price or negative volume"
    if values["low"] > values["high"] or not (values["low"] <= values["open"] <= values["high"]) or not (values["low"] <= values["close"] <= values["high"]):
        return None, "candle OHLC range is invalid"
    return {
        "open_time": open_time.isoformat(),
        "open": values["open"],
        "high": values["high"],
        "low": values["low"],
        "close": values["close"],
        "volume": values["volume"],
        "bar_state": str(raw.get("bar_state") or "closed_candle"),
    }, ""


def _default_adjustment_mode(source: str) -> str:
    if source in {"longbridge_candles", "stale_longbridge_cache"}:
        return "unadjusted"
    if source == "fixture_read_only":
        return "fixture"
    return "provider_default_unknown"


def _split_like_action(previous_close: Any, candle: dict[str, Any]) -> dict[str, Any] | None:
    if candle.get("bar_state") != "closed_candle" or previous_close is None:
        return None
    prior = _number(previous_close)
    current_open = _number(candle.get("open"))
    if prior is None or current_open is None or prior <= 0 or current_open <= 0:
        return None
    ratio = prior / current_open
    for expected in (2.0, 3.0, 4.0, 5.0, 10.0):
        if abs(ratio - expected) / expected <= 0.04:
            return {
                "action_type": "suspected_split",
                "price_ratio": round(ratio, 6),
                "expected_ratio": expected,
                "previous_close": prior,
                "current_open": current_open,
            }
        inverse = 1 / expected
        if abs(ratio - inverse) / inverse <= 0.04:
            return {
                "action_type": "suspected_reverse_split",
                "price_ratio": round(ratio, 6),
                "expected_ratio": inverse,
                "previous_close": prior,
                "current_open": current_open,
            }
    return None


def _priority(source: str) -> int:
    return SOURCE_PRIORITY.get(source, -1)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default
