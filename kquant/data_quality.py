from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .stock_store import connect


UTC = timezone.utc
PRIMARY_LONGBRIDGE_SOURCE = "longbridge_candles"
STALE_LONGBRIDGE_SOURCE = "stale_longbridge_cache"
YAHOO_SOURCES = {"live_yahoo_chart", "yahoo_public_fallback"}
KNOWN_ADJUSTMENT_MODES = {"unadjusted", "fixture", "provider_default_unknown"}
PUBLIC_SOURCE_STATUSES = frozenset({"live_primary", "stale_primary", "reference_only", "unavailable"})


def normalize_source_status(*, source: str, provider_status: str, stale: bool = False) -> str:
    """Map provider-specific lineage into the public cross-asset trust contract."""
    normalized_source = str(source or "").lower()
    normalized_provider = str(provider_status or "unknown").lower()
    if normalized_source == PRIMARY_LONGBRIDGE_SOURCE and normalized_provider == "available" and not stale:
        return "live_primary"
    if normalized_source == STALE_LONGBRIDGE_SOURCE or normalized_provider == "stale_cache" or stale:
        return "stale_primary"
    if normalized_source in YAHOO_SOURCES or normalized_source.startswith(("yahoo", "fixture")):
        return "reference_only"
    return "unavailable"


def _as_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _valid_candle(candle: dict[str, Any]) -> bool:
    try:
        open_price = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        volume = float(candle.get("volume") or 0)
    except (KeyError, TypeError, ValueError):
        return False
    return (
        all(math.isfinite(value) for value in (open_price, high, low, close, volume))
        and min(open_price, close) >= low
        and max(open_price, close) <= high
        and low > 0
        and volume >= 0
    )


def _corporate_action_count(payload: dict[str, Any], db_path: Path | None) -> int:
    if not db_path:
        return 0
    candles = list(payload.get("candles") or [])
    times = [_as_time(candle.get("open_time")) for candle in candles if isinstance(candle, dict)]
    observed = [value for value in times if value]
    if not observed:
        return 0
    try:
        with connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM corporate_action_events
                WHERE symbol = ? AND interval = ? AND adjustment_mode = ? AND dataset_version = ?
                  AND effective_time >= ? AND effective_time <= ?
                """,
                (
                    str(payload.get("symbol") or "").upper(),
                    str(payload.get("interval") or ""),
                    str(payload.get("adjustment_mode") or ""),
                    str(payload.get("dataset_version") or ""),
                    min(observed).isoformat(),
                    max(observed).isoformat(),
                ),
            ).fetchone()
    except Exception:
        return 0
    return int(row["count"] or 0) if row else 0


def assess_candle_payload(
    payload: dict[str, Any],
    *,
    db_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a conservative quality decision for one normalized candle payload."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    candles = [item for item in payload.get("candles") or [] if isinstance(item, dict)]
    source = str(payload.get("source_type") or "")
    provider_status = str(payload.get("provider_status") or "unknown")
    adjustment_mode = str(payload.get("adjustment_mode") or "")
    timestamps = [_as_time(candle.get("open_time")) for candle in candles]
    valid_times = [value for value in timestamps if value]
    invalid_count = sum(not _valid_candle(candle) for candle in candles)
    malformed_time_count = len(candles) - len(valid_times)
    duplicate_count = len(valid_times) - len(set(valid_times))
    future_count = sum(value > current + timedelta(minutes=5) for value in valid_times)
    forming_count = sum(candle.get("bar_state") == "forming_candle" for candle in candles)
    freshness = payload.get("freshness_seconds")
    interval = str(payload.get("interval") or "")
    max_freshness = {"1m": 180, "5m": 600, "15m": 1800, "1h": 7200}.get(interval)
    stale = isinstance(freshness, (int, float)) and max_freshness is not None and freshness > max_freshness
    source_status = normalize_source_status(source=source, provider_status=provider_status, stale=stale)
    hard_veto_reasons: list[str] = []
    caution_reasons: list[str] = []

    if not candles:
        hard_veto_reasons.append("no_candles")
    if invalid_count:
        hard_veto_reasons.append("invalid_ohlcv")
    if malformed_time_count or duplicate_count or future_count:
        hard_veto_reasons.append("invalid_candle_timestamps")
    if provider_status in {"unavailable", "missing_config", "standby", "degraded"}:
        hard_veto_reasons.append(f"provider_{provider_status}")
    if source in YAHOO_SOURCES or source.startswith("yahoo"):
        hard_veto_reasons.append("yahoo_reference_only")
    if source == STALE_LONGBRIDGE_SOURCE or provider_status == "stale_cache" or stale:
        hard_veto_reasons.append("stale_market_data")
    if source.startswith("fixture") or provider_status.startswith("fixture"):
        hard_veto_reasons.append("fixture_data")
    if adjustment_mode not in KNOWN_ADJUSTMENT_MODES:
        caution_reasons.append("unknown_adjustment_mode")
    if forming_count:
        caution_reasons.append("forming_candles_excluded_from_confirmation")

    corporate_action_count = _corporate_action_count(payload, db_path)
    if corporate_action_count:
        caution_reasons.append("unresolved_corporate_action")

    is_primary_live = source == PRIMARY_LONGBRIDGE_SOURCE and provider_status == "available"
    if hard_veto_reasons:
        status = "blocked"
    elif caution_reasons or not is_primary_live:
        status = "caution"
    else:
        status = "clean"
    return {
        "status": status,
        "buy_data_eligible": status == "clean",
        "source": source,
        "source_status": source_status,
        "provider_status": provider_status,
        "adjustment_mode": adjustment_mode or None,
        "dataset_version": payload.get("dataset_version"),
        "coverage": {
            "candle_count": len(candles),
            "first_open_time": min(valid_times).isoformat() if valid_times else None,
            "last_open_time": max(valid_times).isoformat() if valid_times else None,
            "forming_candle_count": forming_count,
        },
        "integrity": {
            "invalid_ohlcv_count": invalid_count,
            "malformed_time_count": malformed_time_count,
            "duplicate_time_count": duplicate_count,
            "future_time_count": future_count,
            "corporate_action_caution_count": corporate_action_count,
        },
        "freshness_seconds": freshness if isinstance(freshness, (int, float)) else None,
        "hard_veto_reasons": hard_veto_reasons,
        "caution_reasons": caution_reasons,
    }


def assess_realtime_market_data(
    *,
    candle_quality: dict[str, Any],
    quote: dict[str, Any],
    session: str,
    trust: str,
) -> dict[str, Any]:
    hard_veto_reasons = list(candle_quality.get("hard_veto_reasons") or [])
    if session != "regular":
        hard_veto_reasons.append("non_regular_session")
    if trust != "live_quote":
        hard_veto_reasons.append(f"trust_{trust}")
    if quote.get("provider_status") != "available":
        hard_veto_reasons.append("quote_unavailable")
    quote_age = quote.get("freshness_seconds")
    if not isinstance(quote_age, (int, float)) or quote_age > 15:
        hard_veto_reasons.append("quote_stale")
    if quote.get("depth_status") != "available":
        hard_veto_reasons.append("depth_unavailable")
    hard_veto_reasons = list(dict.fromkeys(hard_veto_reasons))
    return {
        "status": "clean" if not hard_veto_reasons and candle_quality.get("status") == "clean" else "blocked",
        "buy_data_eligible": not hard_veto_reasons and candle_quality.get("status") == "clean",
        "hard_veto_reasons": hard_veto_reasons,
        "candle_quality": candle_quality,
        "quote_freshness_seconds": quote_age if isinstance(quote_age, (int, float)) else None,
        "session": session,
        "trust": trust,
    }
