from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_MAX_AGE_SECONDS = 15 * 60


def record_options_scan_snapshot(db_path: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = "options-scan-" + uuid4().hex[:16]
    created_at = _timestamp(payload)
    symbols = _symbols_from_payload(payload)
    provider_errors = list(payload.get("provider_errors") or [])
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO options_scan_snapshots (
                id, created_at, source_type, symbols_json, provider_errors_json, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                created_at,
                str(payload.get("source_type") or "unknown"),
                _json_dumps(symbols),
                _json_dumps(provider_errors),
                _json_dumps(payload),
            ),
        )
        connection.commit()
    return _scan_snapshot_row(db_path, snapshot_id) or {"id": snapshot_id, "created_at": created_at}


def record_options_chain_snapshot(
    db_path: str | Path,
    payload: dict[str, Any],
    *,
    scan_id: str | None = None,
) -> dict[str, Any]:
    snapshot_id = "options-chain-" + uuid4().hex[:16]
    created_at = _timestamp(payload)
    underlying = payload.get("underlying") if isinstance(payload.get("underlying"), dict) else {}
    symbol = str(underlying.get("symbol") or payload.get("symbol") or "").upper()
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO options_chain_snapshots (
                id, scan_id, symbol, expiration, created_at, data_quality, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                scan_id,
                symbol,
                payload.get("selected_expiration"),
                created_at,
                str(payload.get("data_quality") or payload.get("source_type") or "unknown"),
                _json_dumps(payload),
            ),
        )
        connection.commit()
    return _chain_snapshot_row(db_path, snapshot_id) or {"id": snapshot_id, "created_at": created_at}


def record_options_price_history_snapshot(db_path: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = "options-history-" + uuid4().hex[:16]
    created_at = _timestamp(payload)
    symbol = _normalize_symbol(payload.get("symbol"))
    option_symbol = _normalize_symbol(payload.get("option_symbol"))
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO options_price_history_snapshots (
                id, instrument_type, symbol, option_symbol, range_value, interval, created_at,
                source_type, provider_errors_json, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                str(payload.get("instrument_type") or "underlying"),
                symbol,
                option_symbol,
                str(payload.get("range") or "5d"),
                str(payload.get("interval") or "15m"),
                created_at,
                str(payload.get("source_type") or "unknown"),
                _json_dumps(list(payload.get("provider_errors") or [])),
                _json_dumps(payload),
            ),
        )
        connection.commit()
    return _price_history_snapshot_row(db_path, snapshot_id) or {"id": snapshot_id, "created_at": created_at}


def attach_scan_snapshot(db_path: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = record_options_scan_snapshot(db_path, payload)
    next_payload = dict(payload)
    next_payload["snapshot_id"] = snapshot["id"]
    next_payload["freshness"] = freshness_from_payload(payload, created_at=snapshot.get("created_at"))
    next_payload["provider_status"] = provider_status(payload)
    next_payload["provider_error_count"] = next_payload["provider_status"]["provider_error_count"]
    next_payload["last_good_snapshot"] = _latest_successful_scan_snapshot(db_path, symbol=None)
    return next_payload


def attach_chain_snapshot(
    db_path: str | Path,
    payload: dict[str, Any],
    *,
    scan_id: str | None = None,
) -> dict[str, Any]:
    snapshot = record_options_chain_snapshot(db_path, payload, scan_id=scan_id)
    next_payload = dict(payload)
    next_payload["snapshot_id"] = snapshot["id"]
    next_payload["scan_id"] = scan_id
    next_payload["freshness"] = freshness_from_payload(payload, created_at=snapshot.get("created_at"))
    next_payload["provider_status"] = provider_status(payload)
    next_payload["provider_error_count"] = next_payload["provider_status"]["provider_error_count"]
    underlying = payload.get("underlying") if isinstance(payload.get("underlying"), dict) else {}
    next_payload["last_good_snapshot"] = _latest_successful_chain_snapshot(
        db_path,
        symbol=str(payload.get("symbol") or underlying.get("symbol") or ""),
    )
    if next_payload["last_good_snapshot"] is None:
        next_payload["last_good_snapshot"] = _latest_successful_chain_snapshot(db_path, symbol=underlying.get("symbol"))
    return next_payload


def attach_price_history_snapshot(db_path: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = annotate_options_payload(payload)
    if _is_successful_live_price_history(payload):
        snapshot = record_options_price_history_snapshot(db_path, payload)
        next_payload["snapshot_id"] = snapshot["id"]
        next_payload["freshness"] = freshness_from_payload(payload, created_at=snapshot.get("created_at"))
    last_good = _latest_successful_price_history_snapshot(
        db_path,
        instrument_type=payload.get("instrument_type"),
        symbol=payload.get("symbol"),
        option_symbol=payload.get("option_symbol"),
        range_value=payload.get("range"),
        interval=payload.get("interval"),
    )
    next_payload["last_good_snapshot"] = last_good
    return next_payload


def annotate_options_payload(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    next_payload.setdefault("freshness", freshness_from_payload(payload))
    next_payload.setdefault("provider_status", provider_status(payload))
    next_payload.setdefault("provider_error_count", next_payload["provider_status"]["provider_error_count"])
    return next_payload


def latest_options_snapshot(
    db_path: str | Path,
    *,
    symbol: str | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    scan = _latest_scan_snapshot(db_path, symbol=symbol)
    chain = _latest_chain_snapshot(db_path, symbol=symbol) if symbol else None
    last_good_scan = _latest_successful_scan_snapshot(db_path, symbol=symbol)
    last_good_chain = _latest_successful_chain_snapshot(db_path, symbol=symbol) if symbol else None
    payload = (chain or scan or {}).get("payload") or {}
    snapshot_available = bool(scan or chain)
    return {
        "symbol": _normalize_symbol(symbol) if symbol else None,
        "scan": scan,
        "chain": chain,
        "last_good_scan": last_good_scan,
        "last_good_chain": last_good_chain,
        "snapshot_available": snapshot_available,
        "freshness": freshness_from_payload(
            payload,
            created_at=(chain or scan or {}).get("created_at"),
            max_age_seconds=max_age_seconds,
        ),
        "provider_status": provider_status(payload) if snapshot_available else _missing_provider_status(),
        "safety": (payload.get("safety") if isinstance(payload.get("safety"), dict) else _safety_payload()),
    }


def latest_options_chain_payload(db_path: str | Path, *, symbol: str | None) -> dict[str, Any]:
    normalized = _normalize_symbol(symbol)
    snapshot = _latest_successful_chain_snapshot(db_path, symbol=normalized) or _latest_chain_snapshot(
        db_path,
        symbol=normalized,
    )
    if snapshot:
        payload = dict(snapshot.get("payload") or {})
        if "fixture" in str(payload.get("source_type") or ""):
            snapshot = None
    if snapshot:
        payload = dict(snapshot.get("payload") or {})
        payload["snapshot_id"] = snapshot.get("id")
        payload["snapshot_read_mode"] = "cache_only"
        payload["snapshot_source_type"] = payload.get("source_type")
        payload["source_type"] = "stale_live_snapshot"
        payload["freshness"] = freshness_from_payload(payload, created_at=snapshot.get("created_at"))
        payload["provider_status"] = provider_status(payload)
        payload["provider_error_count"] = payload["provider_status"]["provider_error_count"]
        payload["last_good_snapshot"] = snapshot
        return payload
    return annotate_options_payload(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_type": "chain_snapshot_missing",
            "underlying": {"symbol": normalized},
            "selected_expiration": None,
            "data_quality": "snapshot_missing",
            "contracts": [],
            "expiration_groups": [],
            "chain_rows": [],
            "provider_errors": [
                {
                    "symbol": normalized,
                    "provider": "options_chain_cache",
                    "error": "No live chain snapshot is available. Run ATM Alert Scan to refresh public data.",
                }
            ],
            "safety": _safety_payload(),
        }
    )


def latest_price_history_payload(
    db_path: str | Path,
    *,
    instrument_type: Any,
    symbol: Any,
    option_symbol: Any,
    range_value: Any,
    interval: Any,
) -> dict[str, Any]:
    snapshot = _latest_successful_price_history_snapshot(
        db_path,
        instrument_type=instrument_type,
        symbol=symbol,
        option_symbol=option_symbol,
        range_value=range_value,
        interval=interval,
    )
    if snapshot:
        payload = dict(snapshot.get("payload") or {})
        if "fixture" in str(payload.get("source_type") or ""):
            snapshot = None
    if snapshot:
        payload = dict(snapshot.get("payload") or {})
        payload["snapshot_id"] = snapshot.get("id")
        payload["snapshot_read_mode"] = "cache_only"
        payload["snapshot_source_type"] = payload.get("source_type")
        payload["source_type"] = "stale_live_snapshot"
        payload["freshness"] = freshness_from_payload(payload, created_at=snapshot.get("created_at"))
        payload["provider_status"] = provider_status(payload)
        payload["provider_error_count"] = payload["provider_status"]["provider_error_count"]
        payload["last_good_snapshot"] = snapshot
        return payload
    instrument = "option" if str(instrument_type or "").lower() == "option" else "underlying"
    return annotate_options_payload(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_type": "price_history_snapshot_missing",
            "instrument_type": instrument,
            "symbol": _normalize_symbol(symbol),
            "option_symbol": _normalize_symbol(option_symbol),
            "range": str(range_value or "5d"),
            "interval": str(interval or "15m"),
            "candles": [],
            "provider_errors": [
                {
                    "symbol": _normalize_symbol(option_symbol or symbol),
                    "provider": "options_price_history_cache",
                    "error": "No live price-history snapshot is available. Run ATM Alert Scan or refresh the chart manually.",
                }
            ],
            "freshness": {
                "generated_at": None,
                "age_seconds": None,
                "max_age_seconds": DEFAULT_MAX_AGE_SECONDS,
                "is_fresh": False,
            },
            "safety": _safety_payload(),
        }
    )


def freshness_from_payload(
    payload: dict[str, Any],
    *,
    created_at: str | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    timestamp = created_at or payload.get("generated_at") or payload.get("created_at")
    parsed = _parse_time(timestamp)
    age_seconds = None
    if parsed is not None:
        age_seconds = max((datetime.now(timezone.utc) - parsed).total_seconds(), 0.0)
    return {
        "generated_at": timestamp,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "max_age_seconds": max_age_seconds,
        "is_fresh": bool(age_seconds is not None and age_seconds <= max_age_seconds),
    }


def provider_status(payload: dict[str, Any]) -> dict[str, Any]:
    provider_errors = list(payload.get("provider_errors") or [])
    source_type = str(payload.get("source_type") or "unknown")
    unavailable = source_type == "unknown" or "unavailable" in source_type or source_type.endswith("_partial")
    return {
        "source_type": source_type,
        "provider_available": bool(not provider_errors and not unavailable),
        "provider_error_count": len(provider_errors),
        "provider_errors": provider_errors,
        "decision_available": bool(
            payload.get("evaluations")
            or payload.get("candidates")
            or payload.get("daily_candidates")
            or payload.get("underlyings")
            or payload.get("contracts")
            or payload.get("chain_rows")
            or payload.get("candles")
        ),
    }


def _missing_provider_status() -> dict[str, Any]:
    return {
        "source_type": "missing_snapshot",
        "provider_available": False,
        "provider_error_count": 0,
        "provider_errors": [],
        "decision_available": False,
    }


def ensure_options_snapshot_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS options_scan_snapshots (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            source_type TEXT NOT NULL,
            symbols_json TEXT NOT NULL,
            provider_errors_json TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS options_chain_snapshots (
            id TEXT PRIMARY KEY,
            scan_id TEXT,
            symbol TEXT NOT NULL,
            expiration TEXT,
            created_at TEXT NOT NULL,
            data_quality TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS options_price_history_snapshots (
            id TEXT PRIMARY KEY,
            instrument_type TEXT NOT NULL,
            symbol TEXT,
            option_symbol TEXT,
            range_value TEXT NOT NULL,
            interval TEXT NOT NULL,
            created_at TEXT NOT NULL,
            source_type TEXT NOT NULL,
            provider_errors_json TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_options_scan_snapshots_created_at ON options_scan_snapshots(created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_options_chain_snapshots_symbol_created_at ON options_chain_snapshots(symbol, created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_options_price_history_snapshots_lookup ON options_price_history_snapshots(instrument_type, symbol, option_symbol, range_value, interval, created_at)"
    )


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    ensure_options_snapshot_schema(connection)
    return connection


def _latest_scan_snapshot(db_path: str | Path, *, symbol: str | None) -> dict[str, Any] | None:
    normalized = _normalize_symbol(symbol) if symbol else None
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM options_scan_snapshots ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    for row in rows:
        payload = _scan_row(row)
        if normalized is None or normalized in payload.get("symbols", []):
            return payload
    return None


def _latest_chain_snapshot(db_path: str | Path, *, symbol: str | None) -> dict[str, Any] | None:
    normalized = _normalize_symbol(symbol)
    if not normalized:
        return None
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT * FROM options_chain_snapshots
            WHERE symbol = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
    return _chain_row(row) if row else None


def _latest_successful_scan_snapshot(db_path: str | Path, *, symbol: str | None) -> dict[str, Any] | None:
    normalized = _normalize_symbol(symbol) if symbol else None
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM options_scan_snapshots ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    for row in rows:
        payload = _scan_row(row)
        body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        if normalized is not None and normalized not in payload.get("symbols", []):
            continue
        if _is_successful_live_scan(body):
            return payload
    return None


def _latest_successful_chain_snapshot(db_path: str | Path, *, symbol: str | None) -> dict[str, Any] | None:
    normalized = _normalize_symbol(symbol)
    if not normalized:
        return None
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT * FROM options_chain_snapshots
            WHERE symbol = ?
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (normalized,),
        ).fetchall()
    for row in rows:
        payload = _chain_row(row)
        body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        if _is_successful_live_chain(body):
            return payload
    return None


def _latest_successful_price_history_snapshot(
    db_path: str | Path,
    *,
    instrument_type: Any,
    symbol: Any,
    option_symbol: Any,
    range_value: Any,
    interval: Any,
) -> dict[str, Any] | None:
    instrument = "option" if str(instrument_type or "").lower() == "option" else "underlying"
    normalized_symbol = _normalize_symbol(symbol)
    normalized_option = _normalize_symbol(option_symbol)
    lookup_symbol = normalized_option if instrument == "option" else normalized_symbol
    if not lookup_symbol:
        return None
    with _connect(db_path) as connection:
        if instrument == "option":
            rows = connection.execute(
                """
                SELECT * FROM options_price_history_snapshots
                WHERE instrument_type = ? AND option_symbol = ? AND range_value = ? AND interval = ?
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (instrument, normalized_option, str(range_value or "5d"), str(interval or "15m")),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT * FROM options_price_history_snapshots
                WHERE instrument_type = ? AND symbol = ? AND range_value = ? AND interval = ?
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (instrument, normalized_symbol, str(range_value or "5d"), str(interval or "15m")),
            ).fetchall()
    for row in rows:
        payload = _price_history_row(row)
        body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        if _is_successful_live_price_history(body):
            return payload
    return None


def _scan_snapshot_row(db_path: str | Path, snapshot_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as connection:
        row = connection.execute("SELECT * FROM options_scan_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    return _scan_row(row) if row else None


def _chain_snapshot_row(db_path: str | Path, snapshot_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as connection:
        row = connection.execute("SELECT * FROM options_chain_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    return _chain_row(row) if row else None


def _price_history_snapshot_row(db_path: str | Path, snapshot_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as connection:
        row = connection.execute("SELECT * FROM options_price_history_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    return _price_history_row(row) if row else None


def _scan_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "source_type": row["source_type"],
        "symbols": _json_loads(row["symbols_json"], []),
        "provider_errors": _json_loads(row["provider_errors_json"], []),
        "payload": _json_loads(row["payload_json"], {}),
    }


def _chain_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "scan_id": row["scan_id"],
        "symbol": row["symbol"],
        "expiration": row["expiration"],
        "created_at": row["created_at"],
        "data_quality": row["data_quality"],
        "payload": _json_loads(row["payload_json"], {}),
    }


def _price_history_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "instrument_type": row["instrument_type"],
        "symbol": row["symbol"],
        "option_symbol": row["option_symbol"],
        "range": row["range_value"],
        "interval": row["interval"],
        "created_at": row["created_at"],
        "source_type": row["source_type"],
        "provider_errors": _json_loads(row["provider_errors_json"], []),
        "payload": _json_loads(row["payload_json"], {}),
    }


def _is_successful_live_scan(payload: dict[str, Any]) -> bool:
    source_type = str(payload.get("source_type") or "")
    if not source_type.startswith("public_live"):
        return False
    return bool(payload.get("daily_candidates") or payload.get("candidates") or payload.get("evaluations"))


def _is_successful_live_chain(payload: dict[str, Any]) -> bool:
    source_type = str(payload.get("source_type") or "")
    if source_type != "public_live_us_options":
        return False
    return bool(payload.get("contracts") or payload.get("chain_rows"))


def _is_successful_live_price_history(payload: dict[str, Any]) -> bool:
    source_type = str(payload.get("source_type") or "")
    if not source_type.startswith("public_live"):
        return False
    return bool(payload.get("candles"))


def _symbols_from_payload(payload: dict[str, Any]) -> list[str]:
    requested = payload.get("requested_symbols")
    if requested:
        return [_normalize_symbol(symbol) for symbol in requested if _normalize_symbol(symbol)]
    symbols = payload.get("symbols")
    if symbols:
        return [_normalize_symbol(symbol) for symbol in symbols if _normalize_symbol(symbol)]
    candidates = payload.get("daily_candidates") or payload.get("candidates") or []
    if isinstance(candidates, list):
        return [_normalize_symbol(item.get("symbol")) for item in candidates if isinstance(item, dict) and item.get("symbol")]
    evaluations = payload.get("evaluations") or []
    if isinstance(evaluations, list):
        return [_normalize_symbol(item.get("symbol")) for item in evaluations if isinstance(item, dict) and item.get("symbol")]
    return []


def _timestamp(payload: dict[str, Any]) -> str:
    value = payload.get("generated_at") or payload.get("created_at")
    parsed = _parse_time(value)
    return parsed.isoformat() if parsed is not None else datetime.now(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_symbol(symbol: Any) -> str:
    return "".join(ch for ch in str(symbol or "").upper() if ch.isalnum())[:12]


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _json_loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def _safety_payload() -> dict[str, Any]:
    return {
        "broker_key_required": False,
        "broker_trading_key_required": False,
        "order_submission_wired": False,
        "manual_alpaca_paper_api_available": True,
        "paper_order_submission_wired": True,
        "paper_order_requires_manual_confirmation": True,
        "live_locked": True,
        "live_order_submission_enabled": False,
    }
