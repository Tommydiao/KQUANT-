from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PILOT_STATUSES = {"reviewed", "skipped", "paper-observed"}
JOURNAL_FILE = "options-pilot-journal.json"
JOURNAL_TABLE = "options_pilot_journal_entries"


def load_pilot_journal(outputs_dir: str | Path = "outputs", db_path: str | Path | None = None) -> dict[str, Any]:
    legacy_path = _journal_path(outputs_dir)
    journal_db_path = _journal_db_path(outputs_dir, db_path)
    entries = _read_entries(journal_db_path, legacy_path)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "journal_path": str(journal_db_path),
        "legacy_journal_path": str(legacy_path),
        "storage": "sqlite",
        "entries": sorted(entries, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True),
        "summary": _journal_summary(entries),
        "allowed_statuses": sorted(PILOT_STATUSES),
        "safety": _journal_safety(),
    }


def record_pilot_journal_entry(
    outputs_dir: str | Path,
    payload: dict[str, Any],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    legacy_path = _journal_path(outputs_dir)
    journal_db_path = _journal_db_path(outputs_dir, db_path)
    entries = _read_entries(journal_db_path, legacy_path)
    now = datetime.now(timezone.utc).isoformat()
    market_date = _market_date(payload)
    option_symbol = _clean_symbol(payload.get("option_symbol") or payload.get("contract") or "")
    symbol = _clean_symbol(payload.get("symbol") or "")
    if not option_symbol:
        raise ValueError("option_symbol is required.")
    if not symbol:
        symbol = _underlying_from_option_symbol(option_symbol)
    status = str(payload.get("status") or "reviewed").strip().lower()
    if status not in PILOT_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(PILOT_STATUSES))}.")
    source_type = _clean_text(payload.get("source_type") or payload.get("source") or "live", 80)
    profile_id = _clean_text(payload.get("profile_id") or payload.get("profile") or "strict_local_v1", 80)
    entry_id = _clean_text(payload.get("entry_id") or f"{market_date}:{profile_id}:{source_type}:{option_symbol}", 180)
    existing = next((item for item in entries if item.get("entry_id") == entry_id), None)
    entry = {
        **(existing or {}),
        "entry_id": entry_id,
        "market_date": market_date,
        "symbol": symbol,
        "option_symbol": option_symbol,
        "status": status,
        "notes": _clean_text(payload.get("notes") or "", 1200),
        "outcome": _clean_text(payload.get("outcome") or "", 1200),
        "run_id": _clean_text(payload.get("run_id") or "", 180),
        "source_type": source_type,
        "profile_id": profile_id,
        "universe": _clean_text(payload.get("universe") or "", 40),
        "alert_level": _clean_text(payload.get("alert_level") or "", 40),
        "alert_score": _safe_number(payload.get("alert_score")),
        "stock_kline_checked": _safe_bool(payload.get("stock_kline_checked")),
        "option_kline_checked": _safe_bool(payload.get("option_kline_checked")),
        "lens_checked": _safe_bool(payload.get("lens_checked")),
        "reviewed_at": now,
        "updated_at": now,
        "safety": _journal_safety(),
    }
    entry["review_step_complete"] = bool(
        _safe_bool(payload.get("review_step_complete"))
        or (
            entry["stock_kline_checked"]
            and entry["option_kline_checked"]
            and entry["lens_checked"]
        )
    )
    if "created_at" not in entry:
        entry["created_at"] = now
    if existing:
        entries = [entry if item.get("entry_id") == entry_id else item for item in entries]
    else:
        entries.append(entry)
    _write_entry(journal_db_path, entry)
    _write_legacy_mirror(legacy_path, entries)
    return {
        "entry": entry,
        "journal": load_pilot_journal(outputs_dir, db_path=journal_db_path),
    }


def journal_summary_for_alerts(
    outputs_dir: str | Path,
    alerts: list[dict[str, Any]],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    journal = load_pilot_journal(outputs_dir, db_path=db_path)
    entries = journal.get("entries") or []
    option_symbols = {str(item.get("option_symbol") or "") for item in alerts}
    matching = [item for item in entries if item.get("option_symbol") in option_symbols]
    return {
        "journal_path": journal.get("journal_path"),
        "matching_entry_count": len(matching),
        "reviewed_count": sum(1 for item in matching if item.get("status") == "reviewed"),
        "skipped_count": sum(1 for item in matching if item.get("status") == "skipped"),
        "paper_observed_count": sum(1 for item in matching if item.get("status") == "paper-observed"),
        "stock_kline_checked_count": sum(1 for item in matching if item.get("stock_kline_checked")),
        "option_kline_checked_count": sum(1 for item in matching if item.get("option_kline_checked")),
        "lens_checked_count": sum(1 for item in matching if item.get("lens_checked")),
        "review_step_complete_count": sum(1 for item in matching if item.get("review_step_complete")),
        "latest_entries": matching[:20],
    }


def journal_entry_complete_for_option(
    outputs_dir: str | Path,
    option_symbol: str,
    *,
    db_path: str | Path | None = None,
    market_date: str | None = None,
) -> dict[str, Any] | None:
    normalized = _clean_symbol(option_symbol)
    if not normalized:
        return None
    entries = load_pilot_journal(outputs_dir, db_path=db_path).get("entries") or []
    for entry in entries:
        if entry.get("option_symbol") != normalized:
            continue
        if market_date and entry.get("market_date") != market_date:
            continue
        if entry.get("review_step_complete"):
            return entry
    return None


def _journal_path(outputs_dir: str | Path) -> Path:
    path = Path(outputs_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path / JOURNAL_FILE


def _journal_db_path(outputs_dir: str | Path, db_path: str | Path | None = None) -> Path:
    if db_path is not None:
        path = Path(db_path)
    else:
        outputs_path = Path(outputs_dir)
        root = outputs_path.parent if outputs_path.parent != Path("") else Path.cwd()
        sibling = root / "market.sqlite3"
        path = sibling if sibling.exists() else root / "work" / "market.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_entries(db_path: Path, legacy_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as connection:
        _ensure_schema(connection)
        legacy_entries = _read_legacy_entries(legacy_path)
        if legacy_entries:
            _upsert_entries(connection, legacy_entries)
        rows = connection.execute(
            f"""
            SELECT payload_json
            FROM {JOURNAL_TABLE}
            ORDER BY updated_at DESC, created_at DESC
            """
        ).fetchall()
    entries: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def _read_legacy_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    entries = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []
    return [item for item in entries if isinstance(item, dict)]


def _write_entry(db_path: Path, entry: dict[str, Any]) -> None:
    with _connect(db_path) as connection:
        _ensure_schema(connection)
        _upsert_entries(connection, [entry])


def _write_legacy_mirror(path: Path, entries: list[dict[str, Any]]) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
        "summary": _journal_summary(entries),
        "safety": _journal_safety(),
        "storage": "sqlite_mirror",
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {JOURNAL_TABLE} (
            entry_id TEXT PRIMARY KEY,
            market_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            option_symbol TEXT NOT NULL,
            status TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{JOURNAL_TABLE}_option_symbol ON {JOURNAL_TABLE}(option_symbol)"
    )
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{JOURNAL_TABLE}_market_date ON {JOURNAL_TABLE}(market_date)"
    )
    connection.commit()


def _upsert_entries(connection: sqlite3.Connection, entries: list[dict[str, Any]]) -> None:
    for item in entries:
        if not isinstance(item, dict):
            continue
        entry_id = _clean_text(item.get("entry_id") or "", 180)
        option_symbol = _clean_symbol(item.get("option_symbol") or item.get("contract") or "")
        if not entry_id or not option_symbol:
            continue
        market_date = _clean_text(item.get("market_date") or "", 20)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", market_date):
            market_date = _market_date(item)
        status = str(item.get("status") or "reviewed").strip().lower()
        if status not in PILOT_STATUSES:
            continue
        payload = dict(item)
        payload["entry_id"] = entry_id
        payload["market_date"] = market_date
        payload["option_symbol"] = option_symbol
        payload["symbol"] = _clean_symbol(payload.get("symbol") or _underlying_from_option_symbol(option_symbol))
        payload["status"] = status
        payload["source_type"] = _clean_text(payload.get("source_type") or payload.get("source") or "live", 80)
        payload["profile_id"] = _clean_text(payload.get("profile_id") or payload.get("profile") or "strict_local_v1", 80)
        payload["created_at"] = _clean_text(payload.get("created_at") or payload.get("updated_at") or datetime.now(timezone.utc).isoformat(), 80)
        payload["updated_at"] = _clean_text(payload.get("updated_at") or payload["created_at"], 80)
        payload["stock_kline_checked"] = _safe_bool(payload.get("stock_kline_checked"))
        payload["option_kline_checked"] = _safe_bool(payload.get("option_kline_checked"))
        payload["lens_checked"] = _safe_bool(payload.get("lens_checked"))
        payload["review_step_complete"] = bool(
            _safe_bool(payload.get("review_step_complete"))
            or (payload["stock_kline_checked"] and payload["option_kline_checked"] and payload["lens_checked"])
        )
        payload["safety"] = _journal_safety()
        connection.execute(
            f"""
            INSERT INTO {JOURNAL_TABLE} (
                entry_id, market_date, symbol, option_symbol, status, profile_id,
                source_type, created_at, updated_at, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entry_id) DO UPDATE SET
                market_date = excluded.market_date,
                symbol = excluded.symbol,
                option_symbol = excluded.option_symbol,
                status = excluded.status,
                profile_id = excluded.profile_id,
                source_type = excluded.source_type,
                updated_at = excluded.updated_at,
                payload_json = excluded.payload_json
            """,
            (
                payload["entry_id"],
                payload["market_date"],
                payload["symbol"],
                payload["option_symbol"],
                payload["status"],
                payload["profile_id"],
                payload["source_type"],
                payload["created_at"],
                payload["updated_at"],
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
    connection.commit()


def _journal_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total_entries": len(entries),
        "reviewed_count": sum(1 for item in entries if item.get("status") == "reviewed"),
        "skipped_count": sum(1 for item in entries if item.get("status") == "skipped"),
        "paper_observed_count": sum(1 for item in entries if item.get("status") == "paper-observed"),
        "stock_kline_checked_count": sum(1 for item in entries if item.get("stock_kline_checked")),
        "option_kline_checked_count": sum(1 for item in entries if item.get("option_kline_checked")),
        "lens_checked_count": sum(1 for item in entries if item.get("lens_checked")),
        "review_step_complete_count": sum(1 for item in entries if item.get("review_step_complete")),
        "market_dates": sorted({str(item.get("market_date")) for item in entries if item.get("market_date")}, reverse=True)[:10],
    }


def _market_date(payload: dict[str, Any]) -> str:
    explicit = _clean_text(payload.get("market_date") or "", 20)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", explicit):
        return explicit
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def _clean_symbol(value: Any) -> str:
    return re.sub(r"[^A-Z0-9._-]", "", str(value or "").upper())[:48]


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit]


def _safe_number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "checked", "on"}


def _underlying_from_option_symbol(option_symbol: str) -> str:
    match = re.match(r"^([A-Z.]+)\d{6}[CP]\d{8}$", option_symbol)
    return match.group(1) if match else option_symbol[:6]


def _journal_safety() -> dict[str, bool]:
    return {
        "live_locked": True,
        "broker_key_required": False,
        "broker_trading_key_required": False,
        "order_submission_wired": False,
        "manual_alpaca_paper_api_available": True,
        "paper_order_submission_wired": True,
        "paper_order_requires_manual_confirmation": True,
        "live_order_submission_enabled": False,
    }
