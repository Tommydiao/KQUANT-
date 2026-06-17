from __future__ import annotations

import sqlite3
import json
from datetime import UTC, datetime
from pathlib import Path

from btc_eth_15m.data import connect


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def dashboard_connection(db_path: Path) -> sqlite3.Connection:
    connection = connect(db_path)
    ensure_dashboard_schema(connection)
    return connection


def ensure_dashboard_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_orders (
            id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            leverage INTEGER NOT NULL,
            margin_usdt REAL NOT NULL,
            notional_usdt REAL NOT NULL,
            quantity REAL NOT NULL,
            entry_price REAL NOT NULL,
            stop_price REAL NOT NULL,
            target_price REAL NOT NULL,
            status TEXT NOT NULL,
            source_draft_id TEXT NOT NULL,
            explanation_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_positions (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            leverage INTEGER NOT NULL,
            margin_usdt REAL NOT NULL,
            notional_usdt REAL NOT NULL,
            quantity REAL NOT NULL,
            entry_price REAL NOT NULL,
            mark_price REAL NOT NULL,
            unrealized_pnl REAL NOT NULL,
            status TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_exchange_syncs (
            mode TEXT PRIMARY KEY,
            passed INTEGER NOT NULL,
            synced_at TEXT NOT NULL,
            checks_json TEXT NOT NULL,
            account_summary_json TEXT NOT NULL,
            positions_json TEXT NOT NULL,
            orders_json TEXT NOT NULL,
            symbol_rules_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_exchange_self_checks (
            mode TEXT PRIMARY KEY,
            passed INTEGER NOT NULL,
            checked_at TEXT NOT NULL,
            checks_json TEXT NOT NULL,
            symbol_rules_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        UPDATE dashboard_orders
        SET margin_usdt = 0
        WHERE id LIKE 'paper-close-%' OR source_draft_id LIKE 'pos-%'
        """
    )
    connection.commit()


def rows_to_dicts(cursor: sqlite3.Cursor) -> list[dict]:
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def latest_orders(db_path: Path, limit: int = 50) -> list[dict]:
    with dashboard_connection(db_path) as connection:
        return rows_to_dicts(
            connection.execute(
                """
                SELECT id, mode, symbol, side, leverage, margin_usdt, notional_usdt,
                       quantity, entry_price, stop_price, target_price, status,
                       source_draft_id, created_at, updated_at
                FROM dashboard_orders
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        )


def open_positions(db_path: Path) -> list[dict]:
    with dashboard_connection(db_path) as connection:
        return rows_to_dicts(
            connection.execute(
                """
                SELECT id, order_id, mode, symbol, side, leverage, margin_usdt,
                       notional_usdt, quantity, entry_price, mark_price,
                       unrealized_pnl, status, opened_at, updated_at
                FROM dashboard_positions
                WHERE status = 'OPEN'
                ORDER BY opened_at DESC
                """
            )
        )


def open_position_count(db_path: Path, mode: str, symbol: str) -> int:
    with dashboard_connection(db_path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM dashboard_positions
            WHERE status = 'OPEN' AND mode = ? AND symbol = ?
            """,
            (mode, symbol),
        ).fetchone()
    return int(row[0] or 0)


def latest_events(db_path: Path, limit: int = 80) -> list[dict]:
    with dashboard_connection(db_path) as connection:
        return rows_to_dicts(
            connection.execute(
                """
                SELECT id, level, message, payload_json, created_at
                FROM dashboard_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
        )


def record_event(db_path: Path, level: str, message: str, payload: dict | None = None) -> None:
    created_at = now_iso()
    with dashboard_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO dashboard_events (level, message, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (level, message, json.dumps(payload or {}, ensure_ascii=False), created_at),
        )
        connection.commit()


def record_exchange_sync(db_path: Path, payload: dict) -> dict:
    mode = str(payload.get("mode", ""))
    if mode not in {"paper", "testnet", "live"}:
        raise ValueError(f"Unsupported exchange sync mode: {mode}")
    synced_at = str(payload.get("synced_at") or now_iso())
    updated_at = now_iso()
    row = {
        "mode": mode,
        "passed": bool(payload.get("passed")),
        "synced_at": synced_at,
        "checks": payload.get("checks", []),
        "account_summary": payload.get("account_summary"),
        "positions": payload.get("positions", []),
        "orders": payload.get("orders", []),
        "symbol_rules": payload.get("symbol_rules", []),
        "updated_at": updated_at,
    }
    with dashboard_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO dashboard_exchange_syncs (
                mode, passed, synced_at, checks_json, account_summary_json,
                positions_json, orders_json, symbol_rules_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mode) DO UPDATE SET
                passed = excluded.passed,
                synced_at = excluded.synced_at,
                checks_json = excluded.checks_json,
                account_summary_json = excluded.account_summary_json,
                positions_json = excluded.positions_json,
                orders_json = excluded.orders_json,
                symbol_rules_json = excluded.symbol_rules_json,
                updated_at = excluded.updated_at
            """,
            (
                mode,
                1 if row["passed"] else 0,
                synced_at,
                json.dumps(row["checks"], ensure_ascii=False),
                json.dumps(row["account_summary"], ensure_ascii=False),
                json.dumps(row["positions"], ensure_ascii=False),
                json.dumps(row["orders"], ensure_ascii=False),
                json.dumps(row["symbol_rules"], ensure_ascii=False),
                updated_at,
            ),
        )
        connection.commit()
    return row


def record_exchange_self_check(db_path: Path, payload: dict) -> dict:
    mode = str(payload.get("mode", ""))
    if mode not in {"paper", "testnet", "live"}:
        raise ValueError(f"Unsupported exchange self-check mode: {mode}")
    checked_at = str(payload.get("checked_at") or now_iso())
    updated_at = now_iso()
    row = {
        "mode": mode,
        "passed": bool(payload.get("passed")),
        "checked_at": checked_at,
        "checks": payload.get("checks", []),
        "symbol_rules": payload.get("symbol_rules", []),
        "updated_at": updated_at,
    }
    with dashboard_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO dashboard_exchange_self_checks (
                mode, passed, checked_at, checks_json, symbol_rules_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(mode) DO UPDATE SET
                passed = excluded.passed,
                checked_at = excluded.checked_at,
                checks_json = excluded.checks_json,
                symbol_rules_json = excluded.symbol_rules_json,
                updated_at = excluded.updated_at
            """,
            (
                mode,
                1 if row["passed"] else 0,
                checked_at,
                json.dumps(row["checks"], ensure_ascii=False),
                json.dumps(row["symbol_rules"], ensure_ascii=False),
                updated_at,
            ),
        )
        connection.commit()
    return row


def latest_exchange_self_check(db_path: Path, mode: str) -> dict | None:
    with dashboard_connection(db_path) as connection:
        row = connection.execute(
            """
            SELECT mode, passed, checked_at, checks_json, symbol_rules_json, updated_at
            FROM dashboard_exchange_self_checks
            WHERE mode = ?
            """,
            (mode,),
        ).fetchone()
    if row is None:
        return None
    return {
        "mode": row[0],
        "passed": bool(row[1]),
        "checked_at": row[2],
        "checks": _json_value(row[3], []),
        "symbol_rules": _json_value(row[4], []),
        "updated_at": row[5],
    }


def latest_exchange_self_check_summary(db_path: Path, mode: str, *, max_age_seconds: int | None = None) -> dict | None:
    payload = latest_exchange_self_check(db_path, mode)
    if payload is None:
        return None
    checks = payload.get("checks", [])
    failed_checks = [str(check.get("name")) for check in checks if isinstance(check, dict) and not check.get("passed")]
    age_seconds = _age_seconds(payload.get("checked_at"))
    is_fresh = True if max_age_seconds is None else bool(age_seconds is not None and age_seconds <= max_age_seconds)
    return {
        "mode": payload["mode"],
        "passed": payload["passed"],
        "checked_at": payload["checked_at"],
        "updated_at": payload["updated_at"],
        "age_seconds": age_seconds,
        "max_age_seconds": max_age_seconds,
        "is_fresh": is_fresh,
        "symbol_rule_count": len(payload.get("symbol_rules", [])),
        "failed_checks": failed_checks,
    }


def latest_exchange_sync(db_path: Path, mode: str) -> dict | None:
    with dashboard_connection(db_path) as connection:
        row = connection.execute(
            """
            SELECT mode, passed, synced_at, checks_json, account_summary_json,
                   positions_json, orders_json, symbol_rules_json, updated_at
            FROM dashboard_exchange_syncs
            WHERE mode = ?
            """,
            (mode,),
        ).fetchone()
    if row is None:
        return None
    return {
        "mode": row[0],
        "passed": bool(row[1]),
        "synced_at": row[2],
        "checks": _json_value(row[3], []),
        "account_summary": _json_value(row[4], None),
        "positions": _json_value(row[5], []),
        "orders": _json_value(row[6], []),
        "symbol_rules": _json_value(row[7], []),
        "updated_at": row[8],
    }


def latest_exchange_sync_summary(db_path: Path, mode: str, *, max_age_seconds: int | None = None) -> dict | None:
    payload = latest_exchange_sync(db_path, mode)
    if payload is None:
        return None
    checks = payload.get("checks", [])
    failed_checks = [str(check.get("name")) for check in checks if isinstance(check, dict) and not check.get("passed")]
    age_seconds = _age_seconds(payload.get("synced_at"))
    is_fresh = True if max_age_seconds is None else bool(age_seconds is not None and age_seconds <= max_age_seconds)
    return {
        "mode": payload["mode"],
        "passed": payload["passed"],
        "synced_at": payload["synced_at"],
        "updated_at": payload["updated_at"],
        "age_seconds": age_seconds,
        "max_age_seconds": max_age_seconds,
        "is_fresh": is_fresh,
        "position_count": len(payload.get("positions", [])),
        "order_count": len(payload.get("orders", [])),
        "symbol_rule_count": len(payload.get("symbol_rules", [])),
        "failed_checks": failed_checks,
    }


def open_margin(db_path: Path, mode: str | None = None) -> float:
    where = "WHERE status = 'OPEN'"
    params: tuple = ()
    if mode:
        where += " AND mode = ?"
        params = (mode,)
    with dashboard_connection(db_path) as connection:
        row = connection.execute(
            f"SELECT COALESCE(SUM(margin_usdt), 0) FROM dashboard_positions {where}",
            params,
        ).fetchone()
    return float(row[0] or 0.0)


def daily_margin_used(db_path: Path, mode: str | None = None) -> float:
    start = datetime.now(tz=UTC).date().isoformat()
    where = """
    WHERE created_at >= ?
      AND status IN ('FILLED', 'NEW', 'SUBMITTED')
      AND id NOT LIKE 'paper-close-%'
      AND source_draft_id NOT LIKE 'pos-%'
    """
    params: tuple = (start,)
    if mode:
        where += " AND mode = ?"
        params = (start, mode)
    with dashboard_connection(db_path) as connection:
        row = connection.execute(
            f"SELECT COALESCE(SUM(margin_usdt), 0) FROM dashboard_orders {where}",
            params,
        ).fetchone()
    return float(row[0] or 0.0)


def daily_realized_pnl(db_path: Path, mode: str | None = None) -> float:
    start = datetime.now(tz=UTC).date().isoformat()
    where = "WHERE updated_at >= ? AND status = 'CLOSED'"
    params: tuple = (start,)
    if mode:
        where += " AND mode = ?"
        params = (start, mode)
    with dashboard_connection(db_path) as connection:
        row = connection.execute(
            f"SELECT COALESCE(SUM(unrealized_pnl), 0) FROM dashboard_positions {where}",
            params,
        ).fetchone()
    return float(row[0] or 0.0)


def daily_loss_used(db_path: Path, mode: str | None = None) -> float:
    loss = max(-daily_realized_pnl(db_path, mode), 0.0)
    return 0.0 if abs(loss) < 1e-9 else loss


def kill_switch_enabled(db_path: Path) -> bool:
    with dashboard_connection(db_path) as connection:
        row = connection.execute(
            "SELECT value FROM dashboard_settings WHERE key = 'kill_switch'"
        ).fetchone()
    return bool(row and row[0] == "true")


def set_kill_switch(db_path: Path, enabled: bool, *, reason: str = "") -> bool:
    created_at = now_iso()
    value = "true" if enabled else "false"
    with dashboard_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO dashboard_settings (key, value, updated_at)
            VALUES ('kill_switch', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (value, created_at),
        )
        connection.execute(
            """
            INSERT INTO dashboard_events (level, message, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "risk",
                "Kill switch enabled." if enabled else "Kill switch disabled.",
                json.dumps({"enabled": enabled, "reason": reason}, ensure_ascii=False),
                created_at,
            ),
        )
        connection.commit()
    return enabled


def _json_value(value: str, fallback):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _age_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max((datetime.now(tz=UTC) - parsed.astimezone(UTC)).total_seconds(), 0.0)
