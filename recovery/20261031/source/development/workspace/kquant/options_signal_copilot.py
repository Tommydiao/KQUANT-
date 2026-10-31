from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo
from .options_data_paths import connect_store, resolve_stores
from .policy_availability import PolicyConfigUnavailable, read_policy


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "options_signal_copilot_v1.json"
_STORE_PATHS = resolve_stores(REPO_ROOT)
DEFAULT_STORE_PATH = _STORE_PATHS["signal_copilot"]
MAIN_STORE_PATH = _STORE_PATHS["main"]
TWO_HOUR_APPROVAL_PATH = REPO_ROOT / "config" / "review_acceptances" / "options_two_hour_manual_paper_o_setup.json"
V2_CAPITAL_PROPOSAL_PATH = REPO_ROOT / "config" / "options_manual_paper_capital_proposal_v2.json"
ENGINE_VERSION = "options-signal-copilot-v1.3.0-loss-pause"
LEGACY_PAPER_TERMS = {"capital_policy_id": "PAPER-RISK-10000-V1", "per_position": Decimal("50"),
                      "total_open": Decimal("150"), "max_positions": 3, "one_contract": False}
V2_PAPER_TERMS = {"capital_policy_id": "PAPER-RISK-10000-ONE-CONTRACT-RESEARCH-V2", "per_position": Decimal("3000"),
                  "total_open": Decimal("3000"), "max_positions": 1, "one_contract": True,
                  "exit_fee_reserve": Decimal("1"), "daily_realized_loss_pause": Decimal("100"),
                  "cumulative_drawdown_pause": Decimal("500")}
RECEIPT_PROXY_MAX_AGE_SECONDS = 3

SIGNAL_STATES = (
    "DRAFT",
    "WATCH",
    "TRIGGERED",
    "REVIEW_READY",
    "INVALIDATED",
    "EXPIRED",
    "REJECTED",
)
AI_STATES = (
    "NOT_REQUESTED",
    "RUNNING",
    "COMPLETED",
    "PARTIAL",
    "TIMEOUT",
    "BUDGET_BLOCKED",
    "FAILED",
)
NOTIFICATION_STATES = (
    "QUEUED",
    "DELIVERED_TO_CHANNEL",
    "ACKNOWLEDGED",
    "SNOOZED",
    "DISMISSED",
    "REVOKED",
)
PAPER_STATES = (
    "INTENT",
    "PENDING_QUOTE",
    "OPEN",
    "EXIT_PENDING_DATA",
    "CLOSED",
    "CANCELLED",
    "EXPIRED_UNRESOLVED",
)


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS copilot_meta (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
  signal_id TEXT PRIMARY KEY,
  economic_opportunity_id TEXT NOT NULL,
  evaluation_id TEXT NOT NULL,
  source TEXT NOT NULL,
  state TEXT NOT NULL,
  strategy_hash TEXT NOT NULL,
  material_state_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(economic_opportunity_id, evaluation_id)
);
CREATE TABLE IF NOT EXISTS ai_assessments (
  assessment_id TEXT PRIMARY KEY,
  signal_id TEXT NOT NULL,
  material_state_hash TEXT NOT NULL,
  model_id TEXT NOT NULL,
  state TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(signal_id, material_state_hash, model_id)
);
CREATE TABLE IF NOT EXISTS copilot_notifications (
  notification_id TEXT PRIMARY KEY,
  signal_id TEXT NOT NULL,
  dedupe_key TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_accounts (
  account_id TEXT PRIMARY KEY,
  initial_cash TEXT NOT NULL,
  cash TEXT NOT NULL,
  version INTEGER NOT NULL,
  synthetic INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_intents (
  intent_id TEXT PRIMARY KEY,
  signal_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  action TEXT NOT NULL,
  state TEXT NOT NULL,
  confirmation_id TEXT NOT NULL UNIQUE,
  confirmed_at TEXT NOT NULL,
  expected_account_version INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_reservations (
  reservation_id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL UNIQUE,
  account_id TEXT NOT NULL,
  amount TEXT NOT NULL,
  state TEXT NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_positions (
  position_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  signal_id TEXT NOT NULL,
  contract_id TEXT NOT NULL,
  state TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  multiplier INTEGER NOT NULL,
  entry_price TEXT NOT NULL,
  entry_fees TEXT NOT NULL,
  entry_time TEXT NOT NULL,
  exit_price TEXT,
  exit_fees TEXT,
  exit_time TEXT,
  realized_pnl TEXT,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_events (
  event_id TEXT PRIMARY KEY,
  aggregate_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_copilot_signals_state_time ON signals(state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_copilot_paper_positions_state ON paper_positions(state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_copilot_paper_reservations_state ON paper_reservations(account_id, state, updated_at DESC);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def load_copilot_config(path: Path | None = None) -> dict[str, Any]:
    payload = read_policy(path if path is not None else CONFIG_PATH, capability="signal_copilot")
    if payload.get("safety", {}).get("real_order_enabled"):
        raise RuntimeError("REAL_ORDER_PERMISSION_FORBIDDEN")
    if payload.get("safety", {}).get("real_account_access_enabled"):
        raise RuntimeError("REAL_ACCOUNT_PERMISSION_FORBIDDEN")
    if payload.get("effective") and payload.get("review", {}).get("gate") != "SC-R1":
        raise RuntimeError("COPILOT_ACTIVATION_REQUIRES_SC_R1")
    payload["config_hash"] = content_hash({key: value for key, value in payload.items() if key != "config_hash"})
    return payload


def initialize_copilot_store(path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    from .signal_eligibility import SCHEMA as ELIGIBILITY_SCHEMA
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect_store(path) as connection:
        connection.executescript(SCHEMA)
        connection.executescript(ELIGIBILITY_SCHEMA)
        now = utc_now()
        connection.execute("INSERT OR REPLACE INTO copilot_meta VALUES (?,?,?)", ("schema_version", canonical(2), now))
        connection.execute("INSERT OR REPLACE INTO copilot_meta VALUES (?,?,?)", ("engine_version", canonical(ENGINE_VERSION), now))
        connection.commit()
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    return {"path": str(path.resolve()), "schema_version": 2, "integrity_check": integrity}


def _connect(path: Path = DEFAULT_STORE_PATH) -> sqlite3.Connection:
    initialize_copilot_store(path)
    connection = connect_store(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _read_connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def create_signal(payload: dict[str, Any], *, store_path: Path = DEFAULT_STORE_PATH, synthetic: bool = False) -> dict[str, Any]:
    source = str(payload.get("source") or "").upper()
    if source not in {"FROZEN_RULE", "LLM_RESEARCH", "USER_RESEARCH", "SYNTHETIC_TEST"}:
        raise ValueError("SIGNAL_SOURCE_NOT_ALLOWED")
    if source == "SYNTHETIC_TEST" and not synthetic:
        raise ValueError("SYNTHETIC_SIGNAL_REQUIRES_EXPLICIT_FLAG")
    state = str(payload.get("state") or "DRAFT").upper()
    if state not in SIGNAL_STATES:
        raise ValueError("SIGNAL_STATE_NOT_ALLOWED")
    config = load_copilot_config()
    strategy_hash = str(payload.get("strategy_hash") or config["strategy_baseline"]["forward_policy_runtime_hash"])
    material = {
        "source": source,
        "symbol": str(payload.get("symbol") or "").upper(),
        "right": str(payload.get("right") or "").upper(),
        "contract_id": payload.get("contract_id"),
        "observed_at": payload.get("observed_at"),
        "strategy_hash": strategy_hash,
        "evidence_refs": payload.get("evidence_refs") or [],
    }
    material_hash = content_hash(material)
    economic_id = str(payload.get("economic_opportunity_id") or f"eco_{content_hash({key: material[key] for key in ('symbol', 'right', 'observed_at', 'strategy_hash')})[:24]}")
    evaluation_id = str(payload.get("evaluation_id") or f"eval_{material_hash[:24]}")
    signal_id = str(payload.get("signal_id") or f"sig_{content_hash({'economic': economic_id, 'evaluation': evaluation_id})[:24]}")
    record = {
        **payload,
        "signal_id": signal_id,
        "economic_opportunity_id": economic_id,
        "evaluation_id": evaluation_id,
        "source": source,
        "state": state,
        "strategy_hash": strategy_hash,
        "material_state_hash": material_hash,
        "synthetic": bool(synthetic),
        "real_order_path": False,
    }
    now = utc_now()
    with _connect(store_path) as connection:
        existing = connection.execute("SELECT payload_json FROM signals WHERE signal_id=?", (signal_id,)).fetchone()
        if existing:
            stored = json.loads(existing["payload_json"])
            if stored != record:
                raise RuntimeError("IMMUTABLE_SIGNAL_IDENTITY_COLLISION")
            return stored
        connection.execute(
            "INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?,?)",
            (signal_id, economic_id, evaluation_id, source, state, strategy_hash, material_hash, canonical(record), now, now),
        )
        connection.commit()
    return record


def list_signals(*, store_path: Path = DEFAULT_STORE_PATH, limit: int = 100) -> dict[str, Any]:
    if not store_path.exists():
        return {"status": "NOT_INITIALIZED", "signals": [], "count": None}
    with _read_connect(store_path) as connection:
        rows = connection.execute("SELECT payload_json,created_at,updated_at FROM signals ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 500)),)).fetchall()
    items = []
    for row in rows:
        item = json.loads(row["payload_json"])
        item.update({"created_at": row["created_at"], "updated_at": row["updated_at"]})
        items.append(item)
    return {"status": "available", "signals": items, "count": len(items)}


def signal_detail(signal_id: str, *, store_path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    with _read_connect(store_path) as connection:
        signal = connection.execute("SELECT * FROM signals WHERE signal_id=?", (signal_id,)).fetchone()
        if not signal:
            raise KeyError(signal_id)
        assessments = [dict(row) for row in connection.execute("SELECT * FROM ai_assessments WHERE signal_id=? ORDER BY created_at", (signal_id,))]
        notifications = [dict(row) for row in connection.execute("SELECT * FROM copilot_notifications WHERE signal_id=? ORDER BY created_at", (signal_id,))]
        intents = [dict(row) for row in connection.execute("SELECT * FROM paper_intents WHERE signal_id=? ORDER BY created_at", (signal_id,))]
    return {
        "signal": json.loads(signal["payload_json"]),
        "ai_assessments": [{**item, "payload": json.loads(item.pop("payload_json"))} for item in assessments],
        "notifications": [{**item, "payload": json.loads(item.pop("payload_json"))} for item in notifications],
        "paper_intents": [{**item, "payload": json.loads(item.pop("payload_json"))} for item in intents],
    }


def queue_notification(
    signal_id: str,
    payload: dict[str, Any],
    *,
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    material_version = str(payload.get("material_state_hash") or signal_detail(signal_id, store_path=store_path)["signal"]["material_state_hash"])
    channel = str(payload.get("channel") or "desktop_web_push")
    event = str(payload.get("event") or "SIGNAL_REVIEW_READY")
    dedupe = content_hash({"signal_id": signal_id, "material": material_version, "channel": channel, "event": event})
    notification_id = f"ntf_{dedupe[:24]}"
    record = {**payload, "signal_id": signal_id, "channel": channel, "event": event, "real_order_path": False}
    now = utc_now()
    with _connect(store_path) as connection:
        existing = connection.execute("SELECT * FROM copilot_notifications WHERE dedupe_key=?", (dedupe,)).fetchone()
        if existing:
            return {"status": "IDEMPOTENT_REPLAY", "notification_id": existing["notification_id"], "llm_reinvoked": False}
        connection.execute("INSERT INTO copilot_notifications VALUES (?,?,?,?,?,?,?)", (notification_id, signal_id, dedupe, "QUEUED", canonical(record), now, now))
        connection.commit()
    return {"status": "QUEUED", "notification_id": notification_id, "llm_reinvoked": False}


def deliver_notification(
    notification_id: str,
    *,
    main_db_path: Path,
    store_path: Path = DEFAULT_STORE_PATH,
    deliverer: Callable[..., dict[str, Any]] | None = None,
    synthetic: bool = False,
) -> dict[str, Any]:
    config = load_copilot_config()
    with _connect(store_path) as connection:
        notification = connection.execute(
            "SELECT * FROM copilot_notifications WHERE notification_id=?",
            (notification_id,),
        ).fetchone()
        if not notification:
            raise KeyError(notification_id)
        signal_row = connection.execute(
            "SELECT payload_json,state FROM signals WHERE signal_id=?",
            (notification["signal_id"],),
        ).fetchone()
        signal = json.loads(signal_row["payload_json"])
        notification_payload = json.loads(notification["payload_json"])
        if notification["state"] == "DELIVERED_TO_CHANNEL":
            return {"status": "IDEMPOTENT_REPLAY", "notification_id": notification_id, "llm_reinvoked": False}
        now = datetime.now(UTC)
        valid_until = notification_payload.get("valid_until")
        if valid_until and _valid_time(str(valid_until)) <= now:
            connection.execute(
                "UPDATE copilot_notifications SET state='REVOKED',updated_at=? WHERE notification_id=?",
                (utc_now(), notification_id),
            )
            connection.commit()
            return {"status": "REVOKED", "reason": "NOTIFICATION_EXPIRED", "notification_id": notification_id, "llm_reinvoked": False}
        snoozed_until = notification_payload.get("snoozed_until")
        if notification["state"] == "SNOOZED" and snoozed_until and _valid_time(str(snoozed_until)) > now:
            return {"status": "SNOOZED", "snoozed_until": snoozed_until, "notification_id": notification_id, "llm_reinvoked": False}
        event_kind = str(notification_payload.get("event") or "")
        position_risk = event_kind in {"POSITION_RISK", "EXIT_REVIEW", "EXIT_PENDING_DATA"}
        if signal_row["state"] in {"INVALIDATED", "EXPIRED", "REJECTED"} and not position_risk:
            connection.execute(
                "UPDATE copilot_notifications SET state='REVOKED',updated_at=? WHERE notification_id=?",
                (utc_now(), notification_id),
            )
            connection.commit()
            return {"status": "REVOKED", "notification_id": notification_id, "llm_reinvoked": False}
    if not synthetic and not bool(config.get("effective")):
        return {"status": "REVIEW_REQUIRED", "gate": "SC-R1", "delivered": False, "llm_reinvoked": False}
    if synthetic and not bool(signal.get("synthetic")):
        raise ValueError("SYNTHETIC_DELIVERY_REQUIRES_SYNTHETIC_SIGNAL")

    if deliverer is None:
        from .web_push import deliver_web_push

        deliverer = deliver_web_push
    payload = notification_payload
    severity = str(payload.get("severity") or "ACTION").upper()
    push_payload = {
        "title": str(payload.get("title") or ("KQUANT TEST_ONLY" if synthetic else "KQUANT Signal")),
        "body": str(payload.get("body") or f"{signal.get('symbol', '')} {signal.get('right', '')} requires review."),
        "url": str(payload.get("url") or f"/?workspace=options&view=signals&symbol={signal.get('symbol', '')}&signal={signal['signal_id']}"),
        "signal_id": signal["signal_id"],
        "event": payload.get("event"),
        "test_only": bool(synthetic),
        "paper_action": False,
        "real_order": False,
    }
    result = deliverer(
        main_db_path,
        alert_id=notification_id,
        severity=severity,
        payload=push_payload,
    )
    next_state = "DELIVERED_TO_CHANNEL" if result.get("status") in {"sent", "partial"} and int(result.get("sent") or 0) > 0 else "QUEUED"
    with _connect(store_path) as connection:
        stored_payload = {**payload, "last_delivery_result": result, "last_delivery_at": utc_now()}
        connection.execute(
            "UPDATE copilot_notifications SET state=?,payload_json=?,updated_at=? WHERE notification_id=?",
            (next_state, canonical(stored_payload), utc_now(), notification_id),
        )
        connection.commit()
    return {
        "status": next_state,
        "notification_id": notification_id,
        "delivery": result,
        "llm_reinvoked": False,
        "test_only": bool(synthetic),
    }


def update_notification_state(
    notification_id: str,
    state: str,
    *,
    snoozed_until: str | None = None,
    reason: str | None = None,
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    state = state.upper()
    if state not in {"ACKNOWLEDGED", "SNOOZED", "DISMISSED", "REVOKED"}:
        raise ValueError("NOTIFICATION_STATE_TRANSITION_NOT_ALLOWED")
    with _connect(store_path) as connection:
        row = connection.execute(
            "SELECT * FROM copilot_notifications WHERE notification_id=?",
            (notification_id,),
        ).fetchone()
        if not row:
            raise KeyError(notification_id)
        payload = json.loads(row["payload_json"])
        if state == "SNOOZED":
            if snoozed_until is None or _valid_time(snoozed_until) <= datetime.now(UTC):
                raise ValueError("FUTURE_SNOOZE_TIME_REQUIRED")
            payload["snoozed_until"] = _valid_time(snoozed_until).isoformat()
        payload.setdefault("lifecycle", []).append({"state": state, "reason": reason, "at": utc_now()})
        connection.execute(
            "UPDATE copilot_notifications SET state=?,payload_json=?,updated_at=? WHERE notification_id=?",
            (state, canonical(payload), utc_now(), notification_id),
        )
        connection.commit()
    return {"status": state, "notification_id": notification_id, "snoozed_until": payload.get("snoozed_until"),
            "signal_state_changed": False, "paper_position_state_changed": False, "llm_reinvoked": False}


def update_signal_state(
    signal_id: str,
    state: str,
    *,
    reason: str,
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    state = state.upper()
    if state not in SIGNAL_STATES:
        raise ValueError("SIGNAL_STATE_NOT_ALLOWED")
    with _connect(store_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM signals WHERE signal_id=?", (signal_id,)).fetchone()
        if not row:
            raise KeyError(signal_id)
        payload = json.loads(row["payload_json"])
        payload["state"] = state
        payload.setdefault("lifecycle", []).append({"state": state, "reason": reason, "at": utc_now()})
        now = utc_now()
        connection.execute(
            "UPDATE signals SET state=?,payload_json=?,updated_at=? WHERE signal_id=?",
            (state, canonical(payload), now, signal_id),
        )
        revoked = 0
        if state in {"INVALIDATED", "EXPIRED", "REJECTED"}:
            notifications = connection.execute(
                "SELECT * FROM copilot_notifications WHERE signal_id=? AND state NOT IN ('REVOKED','DISMISSED')",
                (signal_id,),
            ).fetchall()
            for notification in notifications:
                notice_payload = json.loads(notification["payload_json"])
                if str(notice_payload.get("event") or "") in {"POSITION_RISK", "EXIT_REVIEW", "EXIT_PENDING_DATA"}:
                    continue
                notice_payload.setdefault("lifecycle", []).append({"state": "REVOKED", "reason": f"SIGNAL_{state}:{reason}", "at": now})
                connection.execute(
                    "UPDATE copilot_notifications SET state='REVOKED',payload_json=?,updated_at=? WHERE notification_id=?",
                    (canonical(notice_payload), now, notification["notification_id"]),
                )
                revoked += 1
        connection.commit()
    return {"status": state, "signal_id": signal_id, "reason": reason, "opportunity_notifications_revoked": revoked,
            "open_positions_closed": 0, "acknowledgement_implies_fill": False}


def _event(connection: sqlite3.Connection, aggregate_id: str, event_type: str, payload: dict[str, Any]) -> str:
    event_id = f"pev_{content_hash({'aggregate': aggregate_id, 'type': event_type, 'payload': payload})[:24]}"
    connection.execute("INSERT OR IGNORE INTO paper_events VALUES (?,?,?,?,?)", (event_id, aggregate_id, event_type, canonical(payload), utc_now()))
    return event_id


def _transition_intent(
    connection: sqlite3.Connection,
    intent: sqlite3.Row,
    *,
    state: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist every terminal/pending rejection before returning it."""
    now = utc_now()
    payload = json.loads(intent["payload_json"])
    rejection = {"reason": reason, "state": state, "recorded_at": now, **(details or {})}
    payload.setdefault("decisions", []).append(rejection)
    connection.execute(
        "UPDATE paper_intents SET state=?,payload_json=?,updated_at=? WHERE intent_id=?",
        (state, canonical(payload), now, intent["intent_id"]),
    )
    _release_reservation(connection, intent["intent_id"], state="RELEASED", reason=reason)
    _event(connection, intent["intent_id"], state, rejection)
    connection.commit()
    return {"status": state, "intent_id": intent["intent_id"], "reason": reason, "persisted": True}


def _release_reservation(
    connection: sqlite3.Connection,
    intent_id: str,
    *,
    state: str,
    reason: str,
) -> None:
    connection.execute(
        "UPDATE paper_reservations SET state=?,reason=?,updated_at=? WHERE intent_id=? AND state='RESERVED'",
        (state, reason, utc_now(), intent_id),
    )


def _reserved_cash(connection: sqlite3.Connection, account_id: str, *, excluding_intent: str | None = None) -> Decimal:
    query = "SELECT amount FROM paper_reservations WHERE account_id=? AND state='RESERVED'"
    values: list[Any] = [account_id]
    if excluding_intent is not None:
        query += " AND intent_id<>?"
        values.append(excluding_intent)
    return sum((_decimal(row[0]) for row in connection.execute(query, values)), Decimal("0"))


def _ensure_account(connection: sqlite3.Connection, account_id: str, *, synthetic: bool) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM paper_accounts WHERE account_id=?", (account_id,)).fetchone()
    if row:
        if bool(row["synthetic"]) != bool(synthetic):
            raise RuntimeError("ACCOUNT_EVIDENCE_CLASS_MISMATCH")
        return row
    now = utc_now()
    connection.execute("INSERT INTO paper_accounts VALUES (?,?,?,?,?,?)", (account_id, "10000.00", "10000.00", 0, int(synthetic), now))
    return connection.execute("SELECT * FROM paper_accounts WHERE account_id=?", (account_id,)).fetchone()


def _valid_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def two_hour_paper_terms(signal: dict[str, Any], *, approval_path: Path = TWO_HOUR_APPROVAL_PATH) -> dict[str, Any] | None:
    """Read a separate owner decision; a proposal or stale manifest never enables Paper."""
    if not approval_path.is_file():
        return None
    try:
        approval_bytes = approval_path.read_bytes()
        approval = json.loads(approval_bytes.decode("utf-8-sig"))
        from .options_two_hour import load_policy
        from .options_two_hour_data import universe
        current_policy = load_policy()
        current_scope = universe(MAIN_STORE_PATH)["scope_hash"]
        accepted = (approval.get("gate") == "O-SETUP" and approval.get("status") == "APPROVED"
                    and approval.get("approved_by") == "OWNER" and approval.get("manual_only") is True
                    and approval.get("automatic_paper_enabled") is False and approval.get("real_orders_enabled") is False
                    and approval.get("strict_bbo_unchanged") is True
                    and approval.get("execution_proxy") == "RECEIPT_L1_PROXY"
                    and approval.get("fee_policy_id") == "COST-OPTIONS-CONSERVATIVE-V1"
                    and approval.get("strategy_id") == "STRAT-SHORT-ATM-RANGE-EXPANSION-2H-V1"
                    and approval.get("policy_hash") == signal.get("strategy_hash") == current_policy["policy_hash"]
                    and approval.get("scope_hash") == signal.get("scope_hash") == current_scope)
        if not accepted or _valid_time(approval["approved_at"]) > datetime.now(UTC):
            return None
        if _valid_time(str(signal["observed_at"])) < _valid_time(approval["approved_at"]):
            return None
        choice = approval.get("capital_choice")
        if choice == "MANUAL_ONLY_50_PER_POSITION_150_TOTAL":
            return {**LEGACY_PAPER_TERMS, "approval_hash": hashlib.sha256(approval_bytes).hexdigest()}
        if choice == "MANUAL_ONLY_EXISTING_V2_3000_ONE_CONTRACT_PROPOSAL":
            if (approval.get("capital_policy_id") != V2_PAPER_TERMS["capital_policy_id"]
                    or approval.get("capital_policy_sha256") != hashlib.sha256(V2_CAPITAL_PROPOSAL_PATH.read_bytes()).hexdigest()):
                return None
            return {**V2_PAPER_TERMS, "approval_hash": hashlib.sha256(approval_bytes).hexdigest(),
                    "capital_policy_sha256": approval["capital_policy_sha256"]}
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, IndexError):
        return None
    return None


def _capital_snapshot(terms: dict[str, Any]) -> dict[str, Any]:
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in terms.items()}


def _intent_capital_terms(payload: dict[str, Any]) -> dict[str, Any] | None:
    saved = payload.get("capital_terms")
    if saved is None:
        return LEGACY_PAPER_TERMS if payload.get("synthetic") or not payload.get("two_hour_schedule") else None
    if not isinstance(saved, dict) or saved.get("capital_policy_id") not in {
        "PAPER-RISK-10000-V1", "PAPER-RISK-10000-ONE-CONTRACT-RESEARCH-V2"
    }:
        return None
    try:
        terms = {"capital_policy_id": saved["capital_policy_id"],
                 "per_position": _decimal(saved["per_position"]), "total_open": _decimal(saved["total_open"]),
                 "max_positions": int(saved["max_positions"]), "one_contract": saved["one_contract"]}
        if terms["capital_policy_id"] == V2_PAPER_TERMS["capital_policy_id"]:
            terms.update(exit_fee_reserve=_decimal(saved["exit_fee_reserve"]),
                         daily_realized_loss_pause=_decimal(saved["daily_realized_loss_pause"]),
                         cumulative_drawdown_pause=_decimal(saved["cumulative_drawdown_pause"]),
                         capital_policy_sha256=saved["capital_policy_sha256"])
    except (KeyError, TypeError, ValueError):
        return None
    expected = V2_PAPER_TERMS if terms["capital_policy_id"] == V2_PAPER_TERMS["capital_policy_id"] else LEGACY_PAPER_TERMS
    if any(terms.get(key) != value for key, value in expected.items()):
        return None
    if terms["capital_policy_id"] == V2_PAPER_TERMS["capital_policy_id"] and terms["capital_policy_sha256"] != hashlib.sha256(V2_CAPITAL_PROPOSAL_PATH.read_bytes()).hexdigest():
        return None
    if payload.get("two_hour_schedule") and not payload.get("synthetic"):
        if not isinstance(saved.get("approval_hash"), str) or len(saved["approval_hash"]) != 64:
            return None
        terms["approval_hash"] = saved["approval_hash"]
    return terms


def _loss_pause_state(connection: sqlite3.Connection, account_id: str, at: datetime,
                      terms: dict[str, Any]) -> dict[str, Any] | None:
    if terms["capital_policy_id"] != V2_PAPER_TERMS["capital_policy_id"]:
        return None
    if connection.execute("SELECT 1 FROM paper_events WHERE aggregate_id=? AND event_type='PAPER_LOSS_PAUSE' LIMIT 1", (account_id,)).fetchone():
        return {"reason": "PAPER_LOSS_PAUSE_REQUIRES_OWNER_REENABLE"}
    local_day = at.astimezone(ZoneInfo("America/New_York")).date()
    daily, cumulative, peak, drawdown = Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
    rows = connection.execute("SELECT exit_time,realized_pnl FROM paper_positions WHERE account_id=? AND state='CLOSED' AND realized_pnl IS NOT NULL ORDER BY exit_time,position_id", (account_id,)).fetchall()
    for row in rows:
        realized = _decimal(row["realized_pnl"])
        cumulative += realized
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
        if _valid_time(row["exit_time"]).astimezone(ZoneInfo("America/New_York")).date() == local_day:
            daily += realized
    if daily <= -terms["daily_realized_loss_pause"] or drawdown >= terms["cumulative_drawdown_pause"]:
        return {"reason": "PAPER_REALIZED_LOSS_PAUSE", "daily_realized": str(daily),
                "cumulative_drawdown": str(drawdown), "as_of": at.isoformat()}
    return None


def confirm_paper_intent(
    *,
    signal_id: str,
    action: str,
    confirmation_id: str,
    confirmation_text: str,
    contract: dict[str, Any],
    quote_fetcher: Callable[[], dict[str, Any] | None],
    limit_price: str | None = None,
    requested_quantity: int | None = None,
    account_id: str = "paper-manual-10000-v1",
    store_path: Path = DEFAULT_STORE_PATH,
    synthetic: bool = False,
) -> dict[str, Any]:
    config = load_copilot_config()
    action = action.upper()
    expected_text = f"CONFIRM PAPER {action}"
    if action not in {"ENTRY", "EXIT"} or confirmation_text != expected_text:
        raise ValueError("EXPLICIT_PAPER_CONFIRMATION_REQUIRED")
    signal = signal_detail(signal_id, store_path=store_path)["signal"]
    two_hour = signal.get("strategy_id") == "STRAT-SHORT-ATM-RANGE-EXPANSION-2H-V1"
    if not synthetic and not two_hour and not bool(config.get("effective")):
        return {"status": "REVIEW_REQUIRED", "gate": "SC-R1", "quote_requested": False}
    if not synthetic and limit_price is None:
        raise ValueError("LIMIT_PRICE_REQUIRED")
    if requested_quantity is not None and int(requested_quantity) < 1:
        raise ValueError("REQUESTED_QUANTITY_MUST_BE_POSITIVE")
    if synthetic and not bool(signal.get("synthetic")):
        raise ValueError("SYNTHETIC_INTENT_REQUIRES_SYNTHETIC_SIGNAL")
    if not synthetic and two_hour and action == "ENTRY":
        if signal.get("source") != "FROZEN_RULE" or signal.get("state") != "REVIEW_READY":
            raise ValueError("TWO_HOUR_QUALIFIED_SIGNAL_REQUIRED")
        if not signal.get("contract_id") or signal["contract_id"] != contract.get("contract_id"):
            raise ValueError("TWO_HOUR_SIGNAL_CONTRACT_MISMATCH")
    confirmed_at = utc_now()
    intent_id = f"pit_{content_hash({'signal': signal_id, 'action': action, 'confirmation': confirmation_id})[:24]}"
    with _connect(store_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT * FROM paper_intents WHERE confirmation_id=?", (confirmation_id,)).fetchone()
        if existing:
            return {"status": "IDEMPOTENT_REPLAY", "intent_id": existing["intent_id"], "quote_requested": False}
        two_hour_schedule = signal.get("market_schedule") if two_hour else None
        two_hour_terms = two_hour_paper_terms(signal) if two_hour and not synthetic else None
        capital_terms = two_hour_terms or LEGACY_PAPER_TERMS
        timing_reason = None
        if two_hour and action == "ENTRY":
            if not synthetic and two_hour_terms is None:
                timing_reason = "TWO_HOUR_O_SETUP_APPROVAL_REQUIRED"
            elif not two_hour_schedule:
                timing_reason = "TWO_HOUR_MARKET_SCHEDULE_MISSING"
            else:
                from .options_two_hour import entry_window_gate
                timing_reason = entry_window_gate(action=action, confirmed_at=confirmed_at,
                                                  quote_received_at=None, schedule=two_hour_schedule)
        if timing_reason:
            payload = {"contract": contract, "synthetic": synthetic, "two_hour_schedule": two_hour_schedule,
                       "decisions": [{"reason": timing_reason, "state": "CANCELLED", "recorded_at": confirmed_at}]}
            connection.execute("INSERT INTO paper_intents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (intent_id, signal_id, account_id, action, "CANCELLED", confirmation_id, confirmed_at,
                 0, canonical(payload), confirmed_at, confirmed_at))
            _event(connection, intent_id, "CANCELLED", payload["decisions"][-1])
            connection.commit()
            return {"status": "CANCELLED", "reason": timing_reason, "intent_id": intent_id, "persisted": True, "quote_requested": False}
        account = _ensure_account(connection, account_id, synthetic=synthetic)
        if action == "ENTRY" and two_hour_terms:
            paused = _loss_pause_state(connection, account_id, _valid_time(confirmed_at), two_hour_terms)
            if paused:
                payload = {"contract": contract, "synthetic": synthetic, "two_hour_schedule": two_hour_schedule,
                           "capital_terms": _capital_snapshot(two_hour_terms),
                           "decisions": [{**paused, "state": "CANCELLED", "recorded_at": confirmed_at}]}
                connection.execute("INSERT INTO paper_intents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (intent_id, signal_id, account_id, action, "CANCELLED", confirmation_id, confirmed_at,
                     int(account["version"]), canonical(payload), confirmed_at, confirmed_at))
                _event(connection, intent_id, "CANCELLED", payload["decisions"][-1])
                connection.commit()
                return {"status": "CANCELLED", "reason": paused["reason"], "intent_id": intent_id,
                        "persisted": True, "quote_requested": False}
        reservation_amount = Decimal("0")
        normalized_quantity = int(requested_quantity or 1)
        if action == "ENTRY":
            if two_hour_terms and two_hour_terms["one_contract"] and normalized_quantity != 1:
                raise ValueError("APPROVED_ONE_CONTRACT_LIMIT")
            multiplier = int(contract.get("multiplier") or 0)
            if multiplier <= 0:
                raise ValueError("UNKNOWN_CONTRACT_MULTIPLIER")
            if limit_price is None:
                if not synthetic:
                    raise ValueError("LIMIT_PRICE_REQUIRED")
                reservation_amount = Decimal("50.00")
            else:
                reservation_amount = _decimal(limit_price) * multiplier * normalized_quantity + Decimal("1.00") * normalized_quantity
            if reservation_amount > (two_hour_terms["per_position"] if two_hour_terms else Decimal("50.00")):
                payload = {
                    "contract": contract,
                    "signal_material_state_hash": signal["material_state_hash"],
                    "synthetic": synthetic,
                    "limit_price": limit_price,
                    "requested_quantity": normalized_quantity,
                    "reservation_required": str(reservation_amount),
                    "decisions": [{"reason": "LIMIT_EXCEEDS_FROZEN_POSITION_CAP", "state": "CANCELLED", "recorded_at": confirmed_at}],
                }
                connection.execute(
                    "INSERT INTO paper_intents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (intent_id, signal_id, account_id, action, "CANCELLED", confirmation_id, confirmed_at, int(account["version"]), canonical(payload), confirmed_at, confirmed_at),
                )
                _event(connection, intent_id, "CANCELLED", payload["decisions"][-1])
                connection.commit()
                return {"status": "CANCELLED", "intent_id": intent_id, "reason": "LIMIT_EXCEEDS_FROZEN_POSITION_CAP", "quote_requested": False, "persisted": True}
            open_cost = sum(
                _decimal(row["entry_price"]) * int(row["multiplier"]) * int(row["quantity"]) + _decimal(row["entry_fees"])
                for row in connection.execute("SELECT * FROM paper_positions WHERE account_id=? AND state='OPEN'", (account_id,)).fetchall()
            )
            other_reserved = _reserved_cash(connection, account_id)
            if two_hour_terms:
                open_positions = connection.execute("SELECT COUNT(*) FROM paper_positions WHERE account_id=? AND state='OPEN'", (account_id,)).fetchone()[0]
                pending_entries = connection.execute("SELECT COUNT(*) FROM paper_intents WHERE account_id=? AND action='ENTRY' AND state='PENDING_QUOTE'", (account_id,)).fetchone()[0]
                if open_positions + pending_entries >= two_hour_terms["max_positions"]:
                    raise RuntimeError("APPROVED_OPEN_POSITION_COUNT_LIMIT_REACHED")
            if open_cost + other_reserved + reservation_amount > (two_hour_terms["total_open"] if two_hour_terms else Decimal("150.00")):
                raise RuntimeError("TOTAL_OPEN_AND_RESERVED_PREMIUM_LIMIT_REACHED")
            exit_reserve = two_hour_terms.get("exit_fee_reserve", Decimal("0")) if two_hour_terms else Decimal("0")
            if _decimal(account["cash"]) - other_reserved < reservation_amount + exit_reserve:
                raise RuntimeError("INSUFFICIENT_UNRESERVED_PAPER_CASH")
        payload = {
            "contract": contract,
            "signal_material_state_hash": signal["material_state_hash"],
            "synthetic": synthetic,
            "limit_price": limit_price,
            "requested_quantity": normalized_quantity if action == "ENTRY" else requested_quantity,
            "reservation_amount": str(reservation_amount) if action == "ENTRY" else None,
            "two_hour_schedule": two_hour_schedule,
            "capital_terms": _capital_snapshot(capital_terms),
        }
        connection.execute(
            "INSERT INTO paper_intents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (intent_id, signal_id, account_id, action, "PENDING_QUOTE", confirmation_id, confirmed_at, int(account["version"]), canonical(payload), confirmed_at, confirmed_at),
        )
        _event(connection, intent_id, "OWNER_CONFIRMATION_COMMITTED", {"confirmation_id": confirmation_id, "confirmed_at": confirmed_at, "action": action})
        if action == "ENTRY":
            reservation_id = f"prv_{content_hash({'intent': intent_id, 'account': account_id})[:24]}"
            connection.execute(
                "INSERT INTO paper_reservations VALUES (?,?,?,?,?,?,?,?)",
                (reservation_id, intent_id, account_id, str(reservation_amount), "RESERVED", None, confirmed_at, confirmed_at),
            )
            _event(connection, intent_id, "PAPER_CASH_RESERVED", {"reservation_id": reservation_id, "amount": str(reservation_amount)})
        connection.commit()

    quote = quote_fetcher()
    if quote is None:
        state = "EXIT_PENDING_DATA" if action == "EXIT" else "EXPIRED_UNRESOLVED"
        with _connect(store_path) as connection:
            intent = connection.execute("SELECT * FROM paper_intents WHERE intent_id=?", (intent_id,)).fetchone()
            result = _transition_intent(connection, intent, state=state, reason="NO_POST_CONFIRMATION_QUOTE")
        return {**result, "quote_requested": True}
    return _apply_post_confirmation_quote(intent_id, quote, store_path=store_path)


def _apply_post_confirmation_quote(intent_id: str, quote: dict[str, Any], *, store_path: Path) -> dict[str, Any]:
    with _connect(store_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        intent = connection.execute("SELECT * FROM paper_intents WHERE intent_id=?", (intent_id,)).fetchone()
        if not intent:
            raise KeyError(intent_id)
        if intent["state"] not in {"PENDING_QUOTE", "EXIT_PENDING_DATA"}:
            return {"status": "IDEMPOTENT_REPLAY", "intent_id": intent_id, "state": intent["state"]}
        account = connection.execute("SELECT * FROM paper_accounts WHERE account_id=?", (intent["account_id"],)).fetchone()
        confirmed_at = _valid_time(intent["confirmed_at"])
        try:
            request_started_at = _valid_time(str(quote.get("request_started_at") or ""))
            received_at = _valid_time(str(quote.get("received_at") or ""))
        except (TypeError, ValueError):
            return _transition_intent(connection, intent, state="CANCELLED", reason="INVALID_QUOTE_TIME")
        if request_started_at < confirmed_at or received_at < request_started_at:
            return _transition_intent(connection, intent, state="CANCELLED", reason="QUOTE_NOT_POST_CONFIRMATION")
        payload = json.loads(intent["payload_json"])
        capital_terms = _intent_capital_terms(payload)
        if capital_terms is None:
            return _transition_intent(connection, intent, state="CANCELLED", reason="PAPER_CAPITAL_POLICY_SNAPSHOT_MISSING")
        if intent["action"] == "ENTRY" and payload.get("two_hour_schedule") and not payload.get("synthetic"):
            signal_row = connection.execute("SELECT payload_json FROM signals WHERE signal_id=?", (intent["signal_id"],)).fetchone()
            signal = json.loads(signal_row[0]) if signal_row else {}
            current_terms = two_hour_paper_terms(signal)
            if current_terms is None or current_terms.get("approval_hash") != capital_terms.get("approval_hash"):
                return _transition_intent(connection, intent, state="CANCELLED", reason="TWO_HOUR_APPROVAL_CHANGED")
        if intent["action"] == "ENTRY" and payload.get("two_hour_schedule"):
            from .options_two_hour import entry_window_gate
            timing_reason = entry_window_gate(action="ENTRY", confirmed_at=intent["confirmed_at"],
                quote_received_at=received_at.isoformat(), schedule=payload["two_hour_schedule"])
            if timing_reason:
                return _transition_intent(connection, intent, state="CANCELLED", reason=timing_reason)
        contract = payload["contract"]
        contract_id = str(contract.get("contract_id") or "")
        if not contract_id:
            return _transition_intent(connection, intent, state="CANCELLED", reason="MISSING_CONTRACT_ID")
        quote_contract = str(quote.get("contract_id") or quote.get("contract_symbol") or "")
        if quote_contract and quote_contract != contract_id:
            return _transition_intent(connection, intent, state="CANCELLED", reason="QUOTE_CONTRACT_MISMATCH")
        multiplier = int(contract.get("multiplier") or 0)
        if multiplier <= 0:
            return _transition_intent(connection, intent, state="CANCELLED", reason="UNKNOWN_CONTRACT_MULTIPLIER")
        quote_multiplier = int(quote.get("contract_multiplier") or 0)
        if quote_multiplier and quote_multiplier != multiplier:
            return _transition_intent(connection, intent, state="CANCELLED", reason="CONTRACT_MULTIPLIER_MISMATCH",
                                      details={"confirmed_multiplier": multiplier, "provider_multiplier": quote_multiplier})
        bid = _decimal(quote.get("bid")) if quote.get("bid") is not None else None
        ask = _decimal(quote.get("ask")) if quote.get("ask") is not None else None
        bid_size = int(quote.get("bid_size") or 0)
        ask_size = int(quote.get("ask_size") or 0)
        if bid is None or ask is None or bid < 0 or ask <= 0 or ask < bid:
            state = "EXIT_PENDING_DATA" if intent["action"] == "EXIT" else "EXPIRED_UNRESOLVED"
            return _transition_intent(connection, intent, state=state, reason="INVALID_RECEIPT_L1_QUOTE")
        spread = ask - bid
        slippage = max(Decimal("0.01"), spread * Decimal("0.10"))
        commission = Decimal("1.00")
        now = utc_now()
        if received_at > _valid_time(now) or (received_at - request_started_at).total_seconds() > RECEIPT_PROXY_MAX_AGE_SECONDS or (_valid_time(now) - received_at).total_seconds() > RECEIPT_PROXY_MAX_AGE_SECONDS:
            state = "EXIT_PENDING_DATA" if intent["action"] == "EXIT" else "EXPIRED_UNRESOLVED"
            return _transition_intent(connection, intent, state=state, reason="RECEIPT_PROXY_QUOTE_STALE")
        if not payload.get("synthetic") and quote.get("contract_validity") != "UNEXPIRED":
            state = "EXIT_PENDING_DATA" if intent["action"] == "EXIT" else "EXPIRED_UNRESOLVED"
            return _transition_intent(connection, intent, state=state, reason="CONTRACT_NOT_CONFIRMED_TRADABLE")
        if intent["action"] == "ENTRY":
            if ask_size < 1:
                return _transition_intent(connection, intent, state="EXPIRED_UNRESOLVED", reason="DISPLAYED_ASK_SIZE_ZERO")
            fill = ask + slippage
            limit = _decimal(payload["limit_price"]) if payload.get("limit_price") is not None else None
            if limit is not None and fill > limit:
                return _transition_intent(connection, intent, state="EXPIRED_UNRESOLVED", reason="ENTRY_LIMIT_NOT_MET",
                                          details={"computed_proxy": str(fill), "limit_price": str(limit)})
            unit_cash = fill * multiplier + commission
            affordable = min(int((capital_terms["per_position"] / unit_cash).to_integral_value(rounding=ROUND_FLOOR)), ask_size)
            requested = int(payload["requested_quantity"]) if payload.get("requested_quantity") is not None else affordable
            if affordable < 1:
                return _transition_intent(connection, intent, state="EXPIRED_UNRESOLVED", reason="MINIMUM_CONTRACT_EXCEEDS_FROZEN_RISK_BUDGET")
            if requested > affordable:
                return _transition_intent(connection, intent, state="CANCELLED", reason="REQUESTED_QUANTITY_EXCEEDS_FROZEN_LIMIT",
                                          details={"requested_quantity": requested, "maximum_quantity": affordable})
            quantity = requested
            total = fill * multiplier * quantity + commission * quantity
            reservation = connection.execute(
                "SELECT * FROM paper_reservations WHERE intent_id=? AND state='RESERVED'",
                (intent_id,),
            ).fetchone()
            if not reservation:
                return _transition_intent(connection, intent, state="CANCELLED", reason="ENTRY_RESERVATION_MISSING")
            if total > _decimal(reservation["amount"]):
                return _transition_intent(connection, intent, state="CANCELLED", reason="FILL_EXCEEDS_RESERVED_LIMIT",
                                          details={"fill_total": str(total), "reserved": reservation["amount"]})
            open_positions = connection.execute(
                "SELECT * FROM paper_positions WHERE account_id=? AND state='OPEN'", (intent["account_id"],)
            ).fetchall()
            if len(open_positions) >= capital_terms["max_positions"]:
                return _transition_intent(connection, intent, state="CANCELLED", reason="MAXIMUM_OPEN_POSITIONS_REACHED")
            signal_payload = json.loads(connection.execute("SELECT payload_json FROM signals WHERE signal_id=?", (intent["signal_id"],)).fetchone()[0])
            symbol = str(signal_payload.get("symbol") or contract.get("underlying") or "").upper()
            for open_position in open_positions:
                open_signal = connection.execute("SELECT payload_json FROM signals WHERE signal_id=?", (open_position["signal_id"],)).fetchone()
                if open_signal and str(json.loads(open_signal[0]).get("symbol") or "").upper() == symbol:
                    return _transition_intent(connection, intent, state="CANCELLED", reason="MAXIMUM_ONE_POSITION_PER_UNDERLYING")
            open_cost = sum(
                _decimal(row["entry_price"]) * int(row["multiplier"]) * int(row["quantity"]) + _decimal(row["entry_fees"])
                for row in open_positions
            )
            if open_cost + total > capital_terms["total_open"]:
                return _transition_intent(connection, intent, state="CANCELLED", reason="TOTAL_OPEN_PREMIUM_LIMIT_REACHED")
            other_reserved = _reserved_cash(connection, intent["account_id"], excluding_intent=intent_id)
            if open_cost + other_reserved + total > capital_terms["total_open"]:
                return _transition_intent(connection, intent, state="CANCELLED", reason="TOTAL_OPEN_AND_RESERVED_PREMIUM_LIMIT_REACHED")
            if Decimal(account["cash"]) - other_reserved < total + capital_terms.get("exit_fee_reserve", Decimal("0")):
                return _transition_intent(connection, intent, state="CANCELLED", reason="INSUFFICIENT_PAPER_CASH")
            position_id = f"pps_{content_hash({'intent': intent_id, 'contract': contract.get('contract_id')})[:24]}"
            connection.execute(
                "INSERT INTO paper_positions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (position_id, intent["account_id"], intent["signal_id"], str(contract.get("contract_id") or ""), "OPEN", quantity, multiplier, str(fill), str(commission * quantity), received_at.isoformat(), None, None, None, None, canonical({"entry_intent_id": intent_id, "quote": quote, "capital_terms": _capital_snapshot(capital_terms), "evidence_class": "RECEIPT_L1_PROXY"}), now),
            )
            connection.execute("UPDATE paper_accounts SET cash=?,version=version+1,updated_at=? WHERE account_id=?", (str(Decimal(account["cash"]) - total), now, intent["account_id"]))
            connection.execute("UPDATE paper_intents SET state='OPEN',updated_at=? WHERE intent_id=?", (now, intent_id))
            _release_reservation(connection, intent_id, state="CONSUMED", reason="PAPER_ENTRY_RECORDED")
            _event(connection, position_id, "PAPER_ENTRY_RECORDED", {"fill_price": str(fill), "quantity": quantity, "fees": str(commission * quantity), "quote_received_at": received_at.isoformat()})
            connection.commit()
            return {"status": "OPEN", "intent_id": intent_id, "position_id": position_id, "quantity": quantity, "fill_price": str(fill), "fees": str(commission * quantity), "quote_requested": True}

        position = connection.execute("SELECT * FROM paper_positions WHERE account_id=? AND signal_id=? AND state='OPEN' ORDER BY entry_time LIMIT 1", (intent["account_id"], intent["signal_id"])).fetchone()
        if not position:
            return _transition_intent(connection, intent, state="CANCELLED", reason="NO_OPEN_POSITION")
        if contract_id != str(position["contract_id"]):
            return _transition_intent(connection, intent, state="CANCELLED", reason="EXIT_CONTRACT_MISMATCH",
                                      details={"requested_contract_id": contract_id, "position_contract_id": position["contract_id"]})
        requested_exit = int(payload["requested_quantity"]) if payload.get("requested_quantity") is not None else int(position["quantity"])
        if requested_exit != int(position["quantity"]):
            return _transition_intent(connection, intent, state="CANCELLED", reason="PARTIAL_EXIT_NOT_SUPPORTED")
        if bid_size < int(position["quantity"]):
            connection.execute("UPDATE paper_intents SET state='EXIT_PENDING_DATA',updated_at=? WHERE intent_id=?", (now, intent_id))
            _event(connection, intent_id, "EXIT_PENDING_DATA", {"reason": "INSUFFICIENT_DISPLAYED_BID_SIZE"})
            connection.commit()
            return {"status": "EXIT_PENDING_DATA", "intent_id": intent_id, "reason": "INSUFFICIENT_DISPLAYED_BID_SIZE"}
        fill = max(Decimal("0"), bid - slippage)
        limit = _decimal(payload["limit_price"]) if payload.get("limit_price") is not None else None
        if limit is not None and fill < limit:
            return _transition_intent(connection, intent, state="EXIT_PENDING_DATA", reason="EXIT_LIMIT_NOT_MET",
                                      details={"computed_proxy": str(fill), "limit_price": str(limit)})
        quantity = int(position["quantity"])
        exit_fees = commission * quantity
        proceeds = fill * int(position["multiplier"]) * quantity - exit_fees
        entry_total = _decimal(position["entry_price"]) * int(position["multiplier"]) * quantity + _decimal(position["entry_fees"])
        realized = proceeds - entry_total
        connection.execute(
            "UPDATE paper_positions SET state='CLOSED',exit_price=?,exit_fees=?,exit_time=?,realized_pnl=?,payload_json=?,updated_at=? WHERE position_id=?",
            (str(fill), str(exit_fees), received_at.isoformat(), str(realized), canonical({**json.loads(position["payload_json"]), "exit_intent_id": intent_id, "exit_quote": quote}), now, position["position_id"]),
        )
        connection.execute("UPDATE paper_accounts SET cash=?,version=version+1,updated_at=? WHERE account_id=?", (str(Decimal(account["cash"]) + proceeds), now, intent["account_id"]))
        connection.execute("UPDATE paper_intents SET state='CLOSED',updated_at=? WHERE intent_id=?", (now, intent_id))
        _event(connection, position["position_id"], "PAPER_EXIT_RECORDED", {"fill_price": str(fill), "quantity": quantity, "fees": str(exit_fees), "realized_pnl": str(realized), "quote_received_at": received_at.isoformat()})
        position_terms = _intent_capital_terms(json.loads(position["payload_json"]))
        pause = _loss_pause_state(connection, intent["account_id"], _valid_time(now), position_terms) if position_terms else None
        if pause:
            _event(connection, intent["account_id"], "PAPER_LOSS_PAUSE", pause)
        connection.commit()
        return {"status": "CLOSED", "intent_id": intent_id, "position_id": position["position_id"], "quantity": quantity, "fill_price": str(fill), "fees": str(exit_fees), "realized_pnl": str(realized), "quote_requested": True}


def expire_two_hour_entry_intents(*, now: datetime, store_path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    """Cancel only pending entries carrying the independent two-hour contract."""
    from .options_two_hour import timestamp
    if not store_path.exists():
        return {"count": 0, "cancelled": []}
    cancelled = []
    with _connect(store_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute("SELECT * FROM paper_intents WHERE action='ENTRY' AND state='PENDING_QUOTE'").fetchall()
        for row in rows:
            row = connection.execute("SELECT * FROM paper_intents WHERE intent_id=? AND action='ENTRY' AND state='PENDING_QUOTE'", (row["intent_id"],)).fetchone()
            if row is None:
                continue
            schedule = json.loads(row["payload_json"]).get("two_hour_schedule")
            if not schedule:
                continue
            cutoff = min(timestamp(schedule["regular_open_utc"]) + timedelta(hours=2), timestamp(schedule["regular_close_utc"]))
            if timestamp(now) >= cutoff:
                cancelled.append(_transition_intent(connection, row, state="CANCELLED", reason="TWO_HOUR_ENTRY_WINDOW_ENDED"))
                # The transition commits; reacquire before inspecting the next intent.
                connection.execute("BEGIN IMMEDIATE")
        connection.commit()
    return {"count": len(cancelled), "cancelled": cancelled}


def recover_paper_intents(*, store_path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    """Make crash-left confirmations explicit; never re-request a quote silently."""
    recovered = []
    with _connect(store_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute("SELECT * FROM paper_intents WHERE state='PENDING_QUOTE' ORDER BY created_at").fetchall()
        for row in rows:
            next_state = "EXIT_PENDING_DATA" if row["action"] == "EXIT" else "EXPIRED_UNRESOLVED"
            result = _transition_intent(connection, row, state=next_state, reason="RECOVERED_AFTER_INTERRUPTION_NO_QUOTE_REPLAY")
            recovered.append(result)
    return {"status": "RECOVERED", "count": len(recovered), "intents": recovered, "quote_requests_replayed": 0}


def audit_paper_reservations(*, store_path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    """Read-only reconciliation; never spend or release money as a side effect."""
    if not store_path.exists():
        return {"status": "NOT_INITIALIZED", "reserved_by_account": {}, "orphan_reservations": []}
    reserved: dict[str, Decimal] = {}
    orphans = []
    with _read_connect(store_path) as connection:
        rows = connection.execute("""SELECT r.reservation_id,r.account_id,r.amount,i.state AS intent_state
            FROM paper_reservations r LEFT JOIN paper_intents i ON i.intent_id=r.intent_id
            WHERE r.state='RESERVED'""").fetchall()
        for row in rows:
            reserved[row["account_id"]] = reserved.get(row["account_id"], Decimal("0")) + _decimal(row["amount"])
            if row["intent_state"] != "PENDING_QUOTE":
                orphans.append(row["reservation_id"])
    return {"status": "REVIEW_REQUIRED" if orphans else "RECONCILED", "reserved_by_account":
            {key: str(value) for key, value in reserved.items()}, "orphan_reservations": orphans}


def paper_state(*, store_path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    if not store_path.exists():
        return {"status": "NOT_INITIALIZED", "accounts": [], "intents": [], "positions": [], "real_orders_enabled": False}
    with _read_connect(store_path) as connection:
        accounts = [dict(row) for row in connection.execute("SELECT * FROM paper_accounts ORDER BY account_id")]
        intents = [dict(row) for row in connection.execute("SELECT * FROM paper_intents ORDER BY created_at DESC LIMIT 200")]
        positions = [dict(row) for row in connection.execute("SELECT * FROM paper_positions ORDER BY updated_at DESC LIMIT 200")]
        reservations = [dict(row) for row in connection.execute("SELECT * FROM paper_reservations ORDER BY updated_at DESC LIMIT 200")]
    for row in intents + positions:
        row["payload"] = json.loads(row.pop("payload_json"))
    reserved_by_account: dict[str, str] = {}
    for row in reservations:
        if row["state"] == "RESERVED":
            reserved_by_account[row["account_id"]] = str(_decimal(reserved_by_account.get(row["account_id"], "0")) + _decimal(row["amount"]))
    return {"status": "AVAILABLE", "accounts": accounts, "intents": intents, "positions": positions,
            "reservations": reservations, "reserved_cash_by_account": reserved_by_account,
            "real_orders_enabled": False, "automatic_entry_enabled": False, "automatic_exit_enabled": False}


def store_ai_assessment(
    *,
    signal_id: str,
    material_state_hash: str,
    model_id: str,
    state: str,
    payload: dict[str, Any],
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    if state not in AI_STATES:
        raise ValueError("AI_STATE_NOT_ALLOWED")
    assessment_id = f"aia_{content_hash({'signal': signal_id, 'material': material_state_hash, 'model': model_id})[:24]}"
    with _connect(store_path) as connection:
        existing = connection.execute("SELECT * FROM ai_assessments WHERE assessment_id=?", (assessment_id,)).fetchone()
        if existing:
            return {"assessment_id": assessment_id, "state": existing["state"], "payload": json.loads(existing["payload_json"]), "cache_hit": True}
        connection.execute("INSERT INTO ai_assessments VALUES (?,?,?,?,?,?,?)", (assessment_id, signal_id, material_state_hash, model_id, state, canonical(payload), utc_now()))
        connection.commit()
    return {"assessment_id": assessment_id, "state": state, "payload": payload, "cache_hit": False}


def get_ai_assessment(signal_id: str, material_state_hash: str, model_id: str, *, store_path: Path = DEFAULT_STORE_PATH) -> dict[str, Any] | None:
    with _connect(store_path) as connection:
        row = connection.execute("SELECT * FROM ai_assessments WHERE signal_id=? AND material_state_hash=? AND model_id=?", (signal_id, material_state_hash, model_id)).fetchone()
    if not row:
        return None
    return {"assessment_id": row["assessment_id"], "state": row["state"], "payload": json.loads(row["payload_json"]), "cache_hit": True}


def copilot_status(*, store_path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    try:
        config = load_copilot_config()
    except PolicyConfigUnavailable as exc:
        return {**exc.status(), "engine_version": ENGINE_VERSION,
                "paper_execution": {"enabled": False, "reason": exc.reason},
                "two_hour_paper_execution": {"enabled": False, "reason": exc.reason},
                "llm": {"enabled": False}, "state_dimensions": {
                    "POLICY": exc.reason, "SIGNALS": "UNAVAILABLE", "PAPER_ENGINE": "DISABLED",
                    "PERFORMANCE": "INCONCLUSIVE", "LIVE_DISABLED": True}}
    if not store_path.exists():
        return {"status": "NOT_INITIALIZED", "orders_enabled": False, "account_access_enabled": False}
    initialized = {"path": str(store_path.resolve()), "read_only": True}
    with _read_connect(store_path) as connection:
        counts = {
            "signals": int(connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0]),
            "ai_assessments": int(connection.execute("SELECT COUNT(*) FROM ai_assessments").fetchone()[0]),
            "notifications": int(connection.execute("SELECT COUNT(*) FROM copilot_notifications").fetchone()[0]),
            "paper_intents": int(connection.execute("SELECT COUNT(*) FROM paper_intents").fetchone()[0]),
            "open_positions": int(connection.execute("SELECT COUNT(*) FROM paper_positions WHERE state='OPEN'").fetchone()[0]),
            "closed_positions": int(connection.execute("SELECT COUNT(*) FROM paper_positions WHERE state='CLOSED'").fetchone()[0]),
        }
    approved_two_hour = None
    if TWO_HOUR_APPROVAL_PATH.is_file():
        from .options_two_hour import load_policy
        from .options_two_hour_data import universe
        try:
            approved_two_hour = two_hour_paper_terms({"strategy_hash": load_policy()["policy_hash"],
                "scope_hash": universe(MAIN_STORE_PATH)["scope_hash"],
                "observed_at": utc_now()})
        except (OSError, sqlite3.Error, ValueError, KeyError):
            approved_two_hour = None
    return {
        "status": "WAIT_REVIEW" if not config.get("effective") else "READY",
        "current_policy_available": True,
        "engine_version": ENGINE_VERSION,
        "config_id": config["config_id"],
        "config_hash": config["config_hash"],
        "strategy": config["strategy_baseline"],
        "paper_execution": config["paper_execution_overlay"],
        "two_hour_paper_execution": {"enabled": approved_two_hour is not None,
            "capital_policy_id": approved_two_hour["capital_policy_id"] if approved_two_hour else None,
            "approval_gate": "O-SETUP"},
        "llm": config["llm_runtime"],
        "tool_policy": config["tool_policy"],
        "safety": config["safety"],
        "state_dimensions": {
            "DATA_DISPLAY": "AVAILABLE_REFERENCE_ONLY",
            "LIVE_SESSION_OBSERVATION": "WAIT_MARKET",
            "POLICY": "APPROVED_STRATEGY_MANUAL_OVERLAY_WAIT_SC_R1",
            "MATH_TOOLS": "ENGINEERING_READY",
            "LLM": "BUDGET_BLOCKED",
            "SIGNALS": "ENGINEERING_READY_NOT_ACTIVATED",
            "NOTIFICATIONS": "ENGINEERING_READY_DEVICE_NOT_VALIDATED",
            "PAPER_ENGINE": "SYNTHETIC_ONLY_WAIT_SC_R1",
            "PAPER_RUN": "NOT_STARTED",
            "PERFORMANCE": "INCONCLUSIVE",
            "LIVE_DISABLED": True,
        },
        "counts": counts,
        "store": initialized,
        "orders_enabled": False,
        "account_access_enabled": False,
    }


def synthetic_round_trip(*, store_path: Path) -> dict[str, Any]:
    signal = create_signal(
        {
            "source": "SYNTHETIC_TEST",
            "state": "REVIEW_READY",
            "symbol": "NVDA",
            "right": "CALL",
            "contract_id": "NVDA-SYNTHETIC-CALL",
            "observed_at": "2026-09-20T00:00:00+00:00",
            "evidence_refs": ["SYNTHETIC_FIXTURE_NOT_MARKET_EVIDENCE"],
        },
        store_path=store_path,
        synthetic=True,
    )
    contract = {"contract_id": "NVDA-SYNTHETIC-CALL", "multiplier": 100}

    def quote(bid: str, ask: str) -> Callable[[], dict[str, Any]]:
        def fetch() -> dict[str, Any]:
            now = utc_now()
            return {"bid": bid, "ask": ask, "bid_size": 5, "ask_size": 5, "request_started_at": now, "received_at": utc_now(), "source_bbo_time": None, "synthetic": True}
        return fetch

    entry = confirm_paper_intent(
        signal_id=signal["signal_id"],
        action="ENTRY",
        confirmation_id="synthetic-entry-v1",
        confirmation_text="CONFIRM PAPER ENTRY",
        contract=contract,
        quote_fetcher=quote("0.39", "0.40"),
        account_id="synthetic-paper-10000-v1",
        store_path=store_path,
        synthetic=True,
    )
    exit_result = confirm_paper_intent(
        signal_id=signal["signal_id"],
        action="EXIT",
        confirmation_id="synthetic-exit-v1",
        confirmation_text="CONFIRM PAPER EXIT",
        contract=contract,
        quote_fetcher=quote("0.55", "0.56"),
        account_id="synthetic-paper-10000-v1",
        store_path=store_path,
        synthetic=True,
    )
    return {"signal": signal, "entry": entry, "exit": exit_result, "status": copilot_status(store_path=store_path), "not_market_evidence": True}


__all__ = [
    "AI_STATES",
    "CONFIG_PATH",
    "DEFAULT_STORE_PATH",
    "ENGINE_VERSION",
    "NOTIFICATION_STATES",
    "PAPER_STATES",
    "SIGNAL_STATES",
    "confirm_paper_intent",
    "copilot_status",
    "create_signal",
    "deliver_notification",
    "get_ai_assessment",
    "initialize_copilot_store",
    "list_signals",
    "load_copilot_config",
    "paper_state",
    "queue_notification",
    "recover_paper_intents",
    "signal_detail",
    "store_ai_assessment",
    "synthetic_round_trip",
    "update_notification_state",
    "update_signal_state",
]
