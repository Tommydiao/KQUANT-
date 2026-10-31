from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, UTC
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .options_signal_copilot import DEFAULT_STORE_PATH, content_hash, utc_now


BUDGET_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_budget_days (
  budget_date TEXT NOT NULL,
  timezone TEXT NOT NULL,
  daily_limit_usd TEXT NOT NULL,
  settled_usd TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(budget_date, timezone)
);
CREATE TABLE IF NOT EXISTS llm_budget_reservations (
  reservation_id TEXT PRIMARY KEY,
  scan_id TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL DEFAULT 'ASTRA',
  candidate_id TEXT NOT NULL DEFAULT '',
  purpose TEXT NOT NULL DEFAULT 'research',
  notification_key TEXT NOT NULL DEFAULT '',
  budget_date TEXT NOT NULL,
  timezone TEXT NOT NULL,
  reserved_usd TEXT NOT NULL,
  actual_cost_usd TEXT,
  state TEXT NOT NULL,
  request_sent INTEGER NOT NULL,
  provider_request_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_budget_reservations_day ON llm_budget_reservations(budget_date, timezone, state);
CREATE TABLE IF NOT EXISTS llm_work_queue (
  work_id TEXT PRIMARY KEY,
  role TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  notification_key TEXT NOT NULL DEFAULT '',
  priority INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL,
  deferred_reason TEXT,
  enqueued_at TEXT NOT NULL,
  leased_at TEXT,
  completed_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_work_queue_state ON llm_work_queue(state,priority DESC,enqueued_at);
"""


class ClosingConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=.2, factory=ClosingConnection)
    try:
        connection.row_factory = sqlite3.Row
        connection.executescript(BUDGET_SCHEMA)
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(llm_budget_reservations)")}
        additions = {
            "approval_id": "TEXT NOT NULL DEFAULT ''",
            "role": "TEXT NOT NULL DEFAULT 'ASTRA'",
            "candidate_id": "TEXT NOT NULL DEFAULT ''",
            "purpose": "TEXT NOT NULL DEFAULT 'research'",
            "notification_key": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE llm_budget_reservations ADD COLUMN {name} {definition}")
        connection.commit()
        return connection
    except Exception:
        connection.close()
        raise


def initialize_api_budget_store(*, store_path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    with _connect(store_path) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    return {"status": "INITIALIZED", "path": str(store_path.resolve()), "integrity_check": integrity}


def _money(value: Any) -> Decimal:
    return Decimal(str(value))


def _day(timezone: str) -> str:
    return datetime.now(ZoneInfo(timezone)).date().isoformat()


def enqueue_model_work(
    *,
    role: str,
    candidate_id: str,
    purpose: str,
    notification_key: str = "",
    priority: int = 0,
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    normalized_role = role.strip().upper()
    if normalized_role not in {"SOL", "ASTRA", "LUNA"}:
        raise ValueError("UNKNOWN_MODEL_ROLE")
    now = utc_now()
    material = {
        "role": normalized_role,
        "candidate_id": candidate_id,
        "purpose": purpose,
        "notification_key": notification_key,
    }
    work_id = f"lmw_{content_hash(material)[:24]}"
    with _connect(store_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if notification_key:
            prior = connection.execute(
                "SELECT * FROM llm_work_queue WHERE notification_key=? ORDER BY enqueued_at LIMIT 1",
                (notification_key,),
            ).fetchone()
            if prior:
                return {
                    "status": "NOTIFICATION_REUSES_PRIOR_ASSESSMENT",
                    "work_id": prior["work_id"],
                    "state": prior["state"],
                    "queued": False,
                }
        prior = connection.execute("SELECT * FROM llm_work_queue WHERE work_id=?", (work_id,)).fetchone()
        if prior:
            return {"status": "IDEMPOTENT_REPLAY", "work_id": work_id, "state": prior["state"], "queued": False}
        connection.execute(
            "INSERT INTO llm_work_queue VALUES (?,?,?,?,?,?,'QUEUED',NULL,?,NULL,NULL,?)",
            (work_id, normalized_role, candidate_id, purpose, notification_key, int(priority), now, now),
        )
        connection.commit()
    return {"status": "QUEUED", "work_id": work_id, "role": normalized_role, "queued": True}


def claim_next_model_work(
    *,
    approved_execution: bool,
    max_parallel: int = 2,
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    if not approved_execution:
        return {"status": "EXECUTION_NOT_APPROVED", "claimed": False, "paid_call_allowed": False}
    if max_parallel < 1:
        raise ValueError("POSITIVE_PARALLEL_LIMIT_REQUIRED")
    roles = ("SOL", "ASTRA", "LUNA")
    with _connect(store_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        active = int(connection.execute("SELECT COUNT(*) FROM llm_work_queue WHERE state='LEASED'").fetchone()[0])
        if active >= max_parallel:
            return {"status": "PARALLEL_LIMIT_REACHED", "claimed": False, "paid_call_allowed": False}
        last = connection.execute(
            "SELECT role FROM llm_work_queue WHERE state IN ('LEASED','COMPLETED') ORDER BY COALESCE(leased_at,completed_at,updated_at) DESC LIMIT 1"
        ).fetchone()
        start = (roles.index(str(last["role"])) + 1) % len(roles) if last and str(last["role"]) in roles else 0
        row = None
        for offset in range(len(roles)):
            role = roles[(start + offset) % len(roles)]
            row = connection.execute(
                "SELECT * FROM llm_work_queue WHERE state='QUEUED' AND role=? ORDER BY priority DESC,enqueued_at,work_id LIMIT 1",
                (role,),
            ).fetchone()
            if row:
                break
        if not row:
            return {"status": "QUEUE_EMPTY", "claimed": False, "paid_call_allowed": False}
        now = utc_now()
        changed = connection.execute(
            "UPDATE llm_work_queue SET state='LEASED',leased_at=?,updated_at=? WHERE work_id=? AND state='QUEUED'",
            (now, now, row["work_id"]),
        ).rowcount
        if changed != 1:
            connection.rollback()
            return {"status": "CLAIM_RACE_RETRY", "claimed": False, "paid_call_allowed": False}
        connection.commit()
    return {"status": "LEASED", "claimed": True, "work_id": row["work_id"], "role": row["role"], "candidate_id": row["candidate_id"], "purpose": row["purpose"], "paid_call_allowed": False}


def finish_model_work(
    work_id: str,
    *,
    state: str,
    deferred_reason: str = "",
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    normalized = state.strip().upper()
    if normalized not in {"COMPLETED", "DEFERRED", "REJECTED"}:
        raise ValueError("INVALID_MODEL_WORK_STATE")
    now = utc_now()
    with _connect(store_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM llm_work_queue WHERE work_id=?", (work_id,)).fetchone()
        if not row:
            raise KeyError(work_id)
        if row["state"] in {"COMPLETED", "DEFERRED", "REJECTED"}:
            return {"status": "IDEMPOTENT_REPLAY", "work_id": work_id, "state": row["state"]}
        connection.execute(
            "UPDATE llm_work_queue SET state=?,deferred_reason=?,completed_at=?,updated_at=? WHERE work_id=?",
            (normalized, deferred_reason or None, now, now, work_id),
        )
        connection.commit()
    return {"status": normalized, "work_id": work_id}


def reserve_api_budget(
    *,
    scan_id: str,
    worst_case_usd: Any,
    daily_limit_usd: Any,
    timezone: str,
    approved: bool,
    role: str = "ASTRA",
    candidate_id: str = "",
    purpose: str = "research",
    notification_key: str = "",
    store_path: Path = DEFAULT_STORE_PATH,
    max_parallel: int | None = None,
    role_day_limit: int | None = None,
    role_candidate_limit: int | None = None,
    approval_id: str = "",
    approval_total_usd: Any | None = None,
) -> dict[str, Any]:
    if not approved:
        return {"status": "BUDGET_NOT_APPROVED", "reserved": False, "paid_call_allowed": False}
    amount = _money(worst_case_usd)
    limit = _money(daily_limit_usd)
    normalized_role = role.strip().upper()
    if normalized_role not in {"SOL", "ASTRA", "LUNA"}:
        raise ValueError("UNKNOWN_MODEL_ROLE")
    if amount <= 0 or limit <= 0:
        raise ValueError("POSITIVE_BUDGET_VALUES_REQUIRED")
    if approval_total_usd is not None and (not approval_id or _money(approval_total_usd) <= 0):
        raise ValueError("APPROVAL_ID_AND_POSITIVE_TOTAL_REQUIRED")
    budget_date = _day(timezone)
    reservation_id = f"lbr_{content_hash({'scan': scan_id, 'date': budget_date, 'timezone': timezone})[:24]}"
    now = utc_now()
    with _connect(store_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT * FROM llm_budget_reservations WHERE scan_id=?", (scan_id,)).fetchone()
        if existing:
            return {"status": "IDEMPOTENT_REPLAY", "reservation_id": existing["reservation_id"], "state": existing["state"], "role": existing["role"], "reserved": existing["state"] in {"RESERVED", "USAGE_UNKNOWN"}}
        if notification_key:
            duplicate = connection.execute(
                "SELECT * FROM llm_budget_reservations WHERE notification_key=? ORDER BY created_at LIMIT 1",
                (notification_key,),
            ).fetchone()
            if duplicate:
                return {
                    "status": "NOTIFICATION_REUSES_PRIOR_ASSESSMENT",
                    "reservation_id": duplicate["reservation_id"],
                    "state": duplicate["state"],
                    "role": duplicate["role"],
                    "reserved": False,
                    "paid_call_allowed": False,
                }
        if approval_total_usd is not None:
            approved_rows = connection.execute(
                "SELECT state, reserved_usd, actual_cost_usd FROM llm_budget_reservations WHERE approval_id=?",
                (approval_id,),
            ).fetchall()
            committed = sum((
                _money(item["actual_cost_usd"]) if item["state"] == "SETTLED"
                else _money(item["reserved_usd"]) if item["state"] in {"RESERVED", "USAGE_UNKNOWN"}
                else Decimal("0") for item in approved_rows
            ), Decimal("0"))
            if committed + amount > _money(approval_total_usd):
                return {"status": "APPROVAL_TOTAL_EXHAUSTED", "reserved": False, "paid_call_allowed": False,
                        "committed_usd": str(committed), "approval_total_usd": str(_money(approval_total_usd))}
        if max_parallel is not None:
            active_count = connection.execute("SELECT COUNT(*) FROM llm_budget_reservations WHERE state='RESERVED'").fetchone()[0]
            if active_count >= max_parallel:
                return {"status": "PARALLEL_LIMIT_REACHED", "reserved": False, "paid_call_allowed": False}
        if role_candidate_limit is not None:
            count = connection.execute("SELECT COUNT(*) FROM llm_budget_reservations WHERE role=? AND candidate_id=? AND state!='RELEASED_NO_REQUEST'", (normalized_role, candidate_id)).fetchone()[0]
            if count >= role_candidate_limit:
                return {"status": "ROLE_CANDIDATE_LIMIT_REACHED", "paid_call_allowed": False, "reserved": False}
        if role_day_limit is not None:
            start = datetime.now(ZoneInfo("America/New_York")).replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            count = connection.execute("SELECT COUNT(*) FROM llm_budget_reservations WHERE role=? AND created_at>=? AND created_at<? AND state!='RELEASED_NO_REQUEST'", (normalized_role, start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat())).fetchone()[0]
            if count >= role_day_limit:
                return {"status": "ROLE_MARKET_DAY_LIMIT_REACHED", "paid_call_allowed": False, "reserved": False}
        row = connection.execute("SELECT * FROM llm_budget_days WHERE budget_date=? AND timezone=?", (budget_date, timezone)).fetchone()
        settled = _money(row["settled_usd"]) if row else Decimal("0")
        active = sum(
            (_money(item[0]) for item in connection.execute(
                "SELECT reserved_usd FROM llm_budget_reservations WHERE budget_date=? AND timezone=? AND state IN ('RESERVED','USAGE_UNKNOWN')",
                (budget_date, timezone),
            )),
            Decimal("0"),
        )
        if settled + active + amount > limit:
            return {"status": "BUDGET_EXHAUSTED", "reserved": False, "paid_call_allowed": False,
                    "settled_usd": str(settled), "active_reserved_usd": str(active), "requested_usd": str(amount), "daily_limit_usd": str(limit)}
        connection.execute(
            "INSERT OR REPLACE INTO llm_budget_days VALUES (?,?,?,?,?)",
            (budget_date, timezone, str(limit), str(settled), now),
        )
        connection.execute(
            """INSERT INTO llm_budget_reservations(
                 reservation_id,scan_id,role,candidate_id,purpose,notification_key,approval_id,
                 budget_date,timezone,reserved_usd,actual_cost_usd,state,request_sent,
                 provider_request_id,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                reservation_id, scan_id, normalized_role, candidate_id, purpose,
                notification_key, approval_id, budget_date, timezone, str(amount), None,
                "RESERVED", 0, None, now, now,
            ),
        )
        connection.commit()
    return {"status": "RESERVED", "reservation_id": reservation_id, "role": normalized_role, "reserved": True, "paid_call_allowed": True,
            "budget_date": budget_date, "timezone": timezone, "reserved_usd": str(amount)}


def mark_api_request_sent(
    reservation_id: str,
    *,
    provider_request_id: str | None = None,
    store_path: Path = DEFAULT_STORE_PATH,
) -> None:
    with _connect(store_path) as connection:
        connection.execute(
            "UPDATE llm_budget_reservations SET request_sent=1,provider_request_id=COALESCE(?,provider_request_id),updated_at=? WHERE reservation_id=? AND state='RESERVED'",
            (provider_request_id, utc_now(), reservation_id),
        )
        connection.commit()


def settle_api_budget(
    reservation_id: str,
    *,
    actual_cost_usd: Any | None,
    request_sent: bool,
    provider_request_id: str | None = None,
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    with _connect(store_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM llm_budget_reservations WHERE reservation_id=?", (reservation_id,)).fetchone()
        if not row:
            raise KeyError(reservation_id)
        if row["state"] not in {"RESERVED", "USAGE_UNKNOWN"}:
            return {"status": "IDEMPOTENT_REPLAY", "state": row["state"], "reservation_id": reservation_id}
        now = utc_now()
        if actual_cost_usd is None and request_sent:
            connection.execute(
                "UPDATE llm_budget_reservations SET state='USAGE_UNKNOWN',request_sent=1,provider_request_id=COALESCE(?,provider_request_id),updated_at=? WHERE reservation_id=?",
                (provider_request_id, now, reservation_id),
            )
            connection.commit()
            return {"status": "USAGE_UNKNOWN", "reservation_id": reservation_id, "reservation_retained": True}
        if actual_cost_usd is None:
            state = "RELEASED_NO_REQUEST"
            actual = Decimal("0")
        else:
            state = "SETTLED"
            actual = _money(actual_cost_usd)
            if actual < 0 or actual > _money(row["reserved_usd"]):
                raise ValueError("ACTUAL_COST_OUTSIDE_RESERVATION")
        connection.execute(
            "UPDATE llm_budget_reservations SET state=?,actual_cost_usd=?,request_sent=?,provider_request_id=COALESCE(?,provider_request_id),updated_at=? WHERE reservation_id=?",
            (state, str(actual), int(request_sent), provider_request_id, now, reservation_id),
        )
        if state == "SETTLED":
            day = connection.execute("SELECT * FROM llm_budget_days WHERE budget_date=? AND timezone=?", (row["budget_date"], row["timezone"])).fetchone()
            settled = _money(day["settled_usd"]) + actual
            connection.execute(
                "UPDATE llm_budget_days SET settled_usd=?,updated_at=? WHERE budget_date=? AND timezone=?",
                (str(settled), now, row["budget_date"], row["timezone"]),
            )
        connection.commit()
    return {"status": state, "reservation_id": reservation_id, "actual_cost_usd": str(actual), "reservation_retained": False}


def api_budget_status(*, store_path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    if not store_path.exists():
        return {"status": "NOT_INITIALIZED", "days": [], "reservations": []}
    with sqlite3.connect(f"file:{store_path.resolve().as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"llm_budget_days", "llm_budget_reservations"}.issubset(tables):
            return {"status": "NOT_INITIALIZED", "days": [], "reservations": []}
        days = [dict(row) for row in connection.execute("SELECT * FROM llm_budget_days ORDER BY budget_date DESC,timezone")]
        reservations = [dict(row) for row in connection.execute("SELECT * FROM llm_budget_reservations ORDER BY created_at DESC LIMIT 200")]
        queue = [dict(row) for row in connection.execute("SELECT * FROM llm_work_queue ORDER BY enqueued_at,work_id LIMIT 500")] if "llm_work_queue" in tables else []
    by_role: dict[str, dict[str, Any]] = {}
    for row in reservations:
        role = str(row.get("role") or "UNKNOWN")
        target = by_role.setdefault(role, {"reservations": 0, "settled_usd": "0", "active_or_unknown": 0})
        target["reservations"] += 1
        if row.get("state") == "SETTLED" and row.get("actual_cost_usd") is not None:
            target["settled_usd"] = str(_money(target["settled_usd"]) + _money(row["actual_cost_usd"]))
        if row.get("state") in {"RESERVED", "USAGE_UNKNOWN"}:
            target["active_or_unknown"] += 1
    queue_counts: dict[str, int] = {}
    for row in queue:
        key = str(row.get("state") or "UNKNOWN")
        queue_counts[key] = queue_counts.get(key, 0) + 1
    return {"status": "AVAILABLE", "days": days, "reservations": reservations, "by_role": by_role, "shared_global_ledger": True,
            "work_queue": queue, "work_queue_counts": queue_counts, "fair_role_order": ["SOL", "ASTRA", "LUNA"]}


__all__ = ["api_budget_status", "claim_next_model_work", "enqueue_model_work", "finish_model_work", "initialize_api_budget_store", "mark_api_request_sent", "reserve_api_budget", "settle_api_budget"]
