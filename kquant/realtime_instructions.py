from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .operations import dispatch_personal_notification, queue_notification
from .web_push import deliver_web_push
from .stock_store import connect


TRIGGER_POLICY_VERSION = "realtime_trigger_v1.0.0"
ACTIVE_STATES = {"MONITORING", "READY", "TRIGGERED", "EXIT_REVIEW"}
TERMINAL_STATES = {"INVALIDATED", "EXPIRED"}
ALERT_SEVERITIES = {"INFO", "ACTION", "RISK", "CRITICAL"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_closed_five_minute(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    for candle in reversed(list(snapshot.get("candles_5m") or [])):
        if candle.get("bar_state") == "closed_candle":
            return candle
    return None


def evaluate_instruction_state(
    signal: dict[str, Any],
    snapshot: dict[str, Any],
    now: datetime | None = None,
    previous_state: str | None = None,
) -> dict[str, Any]:
    """Evaluate a deterministic manual-review instruction from trusted market inputs."""

    moment = now or datetime.now(UTC)
    symbol = str(signal.get("symbol") or snapshot.get("symbol") or "").upper()
    entry = dict(signal.get("entry_plan") or {})
    stop_plan = dict(signal.get("stop_plan") or {})
    target_plan = dict(signal.get("target_plan") or {})
    risk_reward = dict(signal.get("risk_reward_plan") or {})
    quote = dict(snapshot.get("quote") or {})
    price = _number(quote.get("last") or quote.get("last_done"))
    bid = _number(quote.get("bid"))
    ask = _number(quote.get("ask"))
    entry_low = _number(entry.get("entry_low"))
    entry_high = _number(entry.get("entry_high"))
    stop = _number(stop_plan.get("stop") or stop_plan.get("stop_price"))
    target_low = _number(target_plan.get("target_low") or target_plan.get("target"))
    target_high = _number(target_plan.get("target_high"))
    hard_veto = dict(signal.get("hard_veto") or {})
    closed_5m = _latest_closed_five_minute(snapshot)
    closed_5m_price = _number((closed_5m or {}).get("close"))
    bbo_valid = bid is not None and ask is not None and bid > 0 and ask >= bid
    data_eligible = bool(
        snapshot.get("provider_status") == "available"
        and snapshot.get("trust") == "live_quote"
        and snapshot.get("quote_fresh")
        and snapshot.get("session") == "regular"
        and snapshot.get("buy_actions_allowed_by_data")
        and bbo_valid
    )
    blockers = list(hard_veto.get("reasons") or [])
    if not data_eligible:
        blockers.append("Realtime Longbridge quote, valid BBO, regular session, and clean market data are required.")
    if not closed_5m:
        blockers.append("A completed 5-minute confirmation candle is required.")
    if any(value is None for value in (entry_low, entry_high, stop, target_low)):
        blockers.append("Entry, stop, and target plan must be complete.")

    state = "MONITORING"
    action = "WATCH"
    severity = "INFO"
    if price is not None and stop is not None and price <= stop:
        state, action, severity = "INVALIDATED", "DO_NOT_ENTER", "CRITICAL"
        blockers.append("Observed price reached or crossed the recorded stop.")
    elif hard_veto.get("active") or not data_eligible:
        state, action, severity = "INVALIDATED", "DO_NOT_ENTER", "RISK"
    elif price is not None and target_low is not None and price >= target_low:
        state, action, severity = "EXIT_REVIEW", "REVIEW_EXIT", "ACTION"
    elif (
        price is not None and entry_low is not None and entry_high is not None
        and entry_low <= price <= entry_high
    ):
        state, action, severity = "READY", "PREPARE_REVIEW", "INFO"
        if closed_5m_price is not None and closed_5m_price >= entry_low:
            state, action, severity = "TRIGGERED", "BUY_REVIEW", "ACTION"
    if previous_state == "TRIGGERED" and state in {"MONITORING", "READY"}:
        state, action, severity = "TRIGGERED", "HOLD_REVIEW", "INFO"

    material = {
        "symbol": symbol,
        "strategy_version": signal.get("strategy_version"),
        "trigger_version": TRIGGER_POLICY_VERSION,
        "state": state,
        "entry": [entry_low, entry_high],
        "stop": stop,
        "target": [target_low, target_high],
        "closed_5m_confirmed": bool(closed_5m_price is not None and entry_low is not None and closed_5m_price >= entry_low),
        "hard_veto": bool(hard_veto.get("active")),
        "trust": snapshot.get("trust"),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    material_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    expires_at = (moment + timedelta(days=1)).isoformat()
    return {
        "symbol": symbol,
        "strategy_version": str(signal.get("strategy_version") or "swing_long_v1.1.0"),
        "trigger_version": TRIGGER_POLICY_VERSION,
        "state": state,
        "action": action,
        "severity": severity,
        "material_state_hash": material_hash,
        "quote_time": quote.get("quote_time"),
        "data_source": str(snapshot.get("trust") or "unavailable"),
        "expires_at": expires_at,
        "plan": {
            "observed_price": price,
            "bid": bid,
            "ask": ask,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop": stop,
            "target_low": target_low,
            "target_high": target_high,
            "risk_reward": risk_reward.get("risk_reward"),
            "risk_reward_value": risk_reward.get("risk_reward_value"),
            "confirmation": "latest closed 5m close is at or above entry_low",
            "manual_confirmation_required": True,
        },
        "evidence": {
            "factor_snapshot_hash": (signal.get("factor_snapshot") or {}).get("factor_snapshot_hash"),
            "closed_5m": closed_5m,
            "data_eligible": data_eligible,
            "bbo_valid": bbo_valid,
            "hard_veto": hard_veto,
            "blockers": list(dict.fromkeys(blockers)),
        },
        "read_only_research": True,
        "order_submission_enabled": False,
    }


def evaluate_early_trend_instruction(snapshot: dict[str, Any], previous_state: str | None = None) -> dict[str, Any] | None:
    stage = str(snapshot.get("strategy_stage") or "NOT_READY")
    if stage == "NOT_READY":
        return None
    state_map = {
        "EARLY_WATCH": ("MONITORING", "EARLY_WATCH", "INFO"),
        "ARMED": ("READY", "WAIT_FOR_TRIGGER", "INFO"),
        "BUY_REVIEW": ("TRIGGERED", "PAPER_BUY_REVIEW", "ACTION"),
        "LATE_WAIT_PULLBACK": ("MONITORING", "WAIT_PULLBACK", "INFO"),
        "INVALIDATED": ("INVALIDATED", "DO_NOT_ENTER", "RISK"),
    }
    state, action, severity = state_map.get(stage, ("MONITORING", "OBSERVE", "INFO"))
    if previous_state == "TRIGGERED" and state in {"MONITORING", "READY"}:
        state, action, severity = "TRIGGERED", "HOLD_REVIEW", "INFO"
    realtime = dict(snapshot.get("realtime_snapshot") or {})
    quote = dict(realtime.get("quote") or {})
    pullback = list(snapshot.get("pullback_zone") or [])
    execution = dict(snapshot.get("execution_eligibility") or {})
    material = {
        "symbol": snapshot.get("symbol"),
        "strategy_version": snapshot.get("strategy_version"),
        "stage": stage,
        "setup_score": snapshot.get("setup_score"),
        "trigger_score": snapshot.get("trigger_score"),
        "pullback_zone": pullback,
        "invalidation": snapshot.get("invalidation_price"),
        "blockers": execution.get("blockers"),
    }
    material_hash = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()[:24]
    return {
        "symbol": str(snapshot.get("symbol") or "").upper(),
        "strategy_version": str(snapshot.get("strategy_version") or "early_trend_3_15d_v1.0.0"),
        "trigger_version": str(snapshot.get("trigger_policy_version") or "early_trend_trigger_v1.0.0"),
        "state": state,
        "action": action,
        "severity": severity,
        "material_state_hash": material_hash,
        "quote_time": quote.get("quote_time"),
        "data_source": str(realtime.get("trust") or "unavailable"),
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "plan": {
            "observed_price": quote.get("last"),
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "entry_low": pullback[0] if len(pullback) == 2 else None,
            "entry_high": pullback[1] if len(pullback) == 2 else None,
            "stop": snapshot.get("invalidation_price"),
            "target_low": None,
            "target_high": None,
            "risk_reward": "pending trigger",
            "risk_reward_value": None,
            "confirmation": "closed 1H trigger plus closed 5m confirmation",
            "manual_confirmation_required": True,
            "paper_only": True,
        },
        "evidence": {
            "strategy_stage": stage,
            "setup_score": snapshot.get("setup_score"),
            "trigger_score": snapshot.get("trigger_score"),
            "execution_eligibility": execution,
            "lead_time_evidence": snapshot.get("lead_time_evidence"),
            "factor_snapshot_hash": snapshot.get("factor_snapshot_hash"),
            "blockers": execution.get("blockers") or [],
        },
        "read_only_research": True,
        "order_submission_enabled": False,
    }
class AlertEventHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        channel: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add(channel)
        return channel

    def unsubscribe(self, channel: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(channel)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)
        for channel in subscribers:
            try:
                channel.put_nowait(event)
            except queue.Full:
                try:
                    channel.get_nowait()
                    channel.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass


def persist_instruction(db_path: Path, instruction: dict[str, Any], hub: AlertEventHub | None = None) -> dict[str, Any]:
    dedupe_key = hashlib.sha256(
        f"{instruction['symbol']}|{instruction['strategy_version']}|{instruction['trigger_version']}|{instruction['material_state_hash']}".encode("utf-8")
    ).hexdigest()[:32]
    now = _now()
    with connect(db_path) as conn:
        existing = conn.execute("SELECT instruction_id FROM trade_instructions WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
        if existing:
            row = conn.execute("SELECT * FROM trade_instructions WHERE instruction_id = ?", (existing["instruction_id"],)).fetchone()
            return _instruction_row(row, duplicate=True)
        instruction_id = f"instruction-{uuid.uuid4().hex[:20]}"
        conn.execute(
            """
            INSERT INTO trade_instructions(
              instruction_id, dedupe_key, symbol, strategy_version, trigger_version,
              state, action, severity, material_state_hash, quote_time, data_source,
              expires_at, plan_json, evidence_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instruction_id, dedupe_key, instruction["symbol"], instruction["strategy_version"],
                instruction["trigger_version"], instruction["state"], instruction["action"], instruction["severity"],
                instruction["material_state_hash"], instruction.get("quote_time"), instruction["data_source"],
                instruction.get("expires_at"), json.dumps(instruction["plan"], ensure_ascii=True),
                json.dumps(instruction["evidence"], ensure_ascii=True), now, now,
            ),
        )
        conn.commit()
    stored = get_instruction(db_path, instruction_id)
    alert = create_alert_for_instruction(db_path, stored)
    if alert and hub:
        hub.publish(alert)
    return {**stored, "duplicate": False, "alert": alert}


def _instruction_row(row: Any, *, duplicate: bool = False) -> dict[str, Any]:
    item = dict(row)
    item["plan"] = json.loads(item.pop("plan_json"))
    item["evidence"] = json.loads(item.pop("evidence_json"))
    item["strategy_stage"] = item["evidence"].get("strategy_stage")
    item["setup_score"] = item["evidence"].get("setup_score")
    item["trigger_score"] = item["evidence"].get("trigger_score")
    item["execution_eligibility"] = item["evidence"].get("execution_eligibility")
    item["lead_time_evidence"] = item["evidence"].get("lead_time_evidence")
    item["duplicate"] = duplicate
    item["read_only_research"] = True
    item["order_submission_enabled"] = False
    return item


def get_instruction(db_path: Path, instruction_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM trade_instructions WHERE instruction_id = ?", (instruction_id,)).fetchone()
    if not row:
        raise ValueError("Unknown instruction.")
    return _instruction_row(row)


def list_instructions(db_path: Path, *, current_only: bool = False, symbol: str | None = None, limit: int = 100) -> dict[str, Any]:
    clauses: list[str] = []
    values: list[Any] = []
    if current_only:
        clauses.append("state IN ('MONITORING','READY','TRIGGERED','EXIT_REVIEW')")
    if symbol:
        clauses.append("symbol = ?")
        values.append(symbol.upper())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.append(max(1, min(int(limit), 500)))
    with connect(db_path) as conn:
        rows = conn.execute(f"SELECT * FROM trade_instructions {where} ORDER BY updated_at DESC LIMIT ?", values).fetchall()
    return {
        "instructions": [_instruction_row(row) for row in rows],
        "trigger_version": TRIGGER_POLICY_VERSION,
        "read_only_research": True,
        "order_submission_enabled": False,
    }


def latest_instruction(db_path: Path, symbol: str) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM trade_instructions WHERE symbol = ? ORDER BY updated_at DESC LIMIT 1",
            (symbol.upper(),),
        ).fetchone()
    return _instruction_row(row) if row else None


def create_alert_for_instruction(db_path: Path, instruction: dict[str, Any]) -> dict[str, Any] | None:
    state = instruction["state"]
    severity = instruction["severity"] if instruction["severity"] in ALERT_SEVERITIES else "INFO"
    dedupe_key = f"instruction:{instruction['instruction_id']}:{state}"
    alert_id = f"alert-{uuid.uuid4().hex[:20]}"
    now = _now()
    title_by_state = {
        "MONITORING": "进入实时观察",
        "READY": "进入计划区间",
        "TRIGGERED": "满足人工复核条件",
        "INVALIDATED": "交易计划已失效",
        "EXPIRED": "交易计划已过期",
        "EXIT_REVIEW": "需要退出复核",
    }
    message = f"{instruction['symbol']} · {title_by_state.get(state, state)} · {instruction['action']}"
    payload = {
        "instruction_id": instruction["instruction_id"],
        "symbol": instruction["symbol"],
        "state": state,
        "action": instruction["action"],
        "plan": instruction["plan"],
        "read_only_research": True,
    }
    with connect(db_path) as conn:
        existing = conn.execute("SELECT alert_id FROM alert_events WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
        if existing:
            return None
        conn.execute(
            """
            INSERT INTO alert_events(
              alert_id, instruction_id, dedupe_key, symbol, severity, event_type,
              title, message, payload_json, delivery_status, acknowledged_at,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (alert_id, instruction["instruction_id"], dedupe_key, instruction["symbol"], severity,
             f"instruction_{state.lower()}", title_by_state.get(state, state), message,
             json.dumps(payload, ensure_ascii=True), "web_queued", None, now, now),
        )
        conn.commit()
    alert = get_alert(db_path, alert_id)
    push_result = deliver_web_push(
        db_path,
        alert_id=alert_id,
        severity=severity,
        payload={
            "title": title_by_state.get(state, state),
            "body": message,
            "symbol": instruction["symbol"],
            "state": state,
            "price": instruction.get("plan", {}).get("observed_price"),
            "entry_low": instruction.get("plan", {}).get("entry_low"),
            "entry_high": instruction.get("plan", {}).get("entry_high"),
            "stop": instruction.get("plan", {}).get("stop"),
            "invalidation": (instruction.get("evidence") or {}).get("blockers"),
            "data_time": instruction.get("quote_time"),
            "url": f"/?symbol={instruction['symbol']}&workspace=today",
            "tag": dedupe_key,
            "severity": severity,
        },
    )
    alert["web_push"] = push_result
    if os.getenv("KQUANT_ENABLE_NOTIFICATIONS", "false").lower() == "true":
        queued = queue_notification(db_path, event_type=_legacy_notification_type(state), payload=payload, channel="telegram")
        result = dispatch_personal_notification(db_path, event_id=queued["event_id"])
        with connect(db_path) as conn:
            conn.execute("UPDATE alert_events SET delivery_status = ?, updated_at = ? WHERE alert_id = ?", (result["status"], _now(), alert_id))
            conn.commit()
        alert["delivery_status"] = result["status"]
    return alert


def _legacy_notification_type(state: str) -> str:
    if state == "TRIGGERED":
        return "watch_entry_zone"
    if state in {"INVALIDATED", "EXPIRED"}:
        return "manual_plan_invalidation"
    if state == "EXIT_REVIEW":
        return "hard_veto"
    return "new_buy_setup"


def get_alert(db_path: Path, alert_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM alert_events WHERE alert_id = ?", (alert_id,)).fetchone()
    if not row:
        raise ValueError("Unknown alert.")
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    return item


def list_alerts(db_path: Path, *, unread_only: bool = False, limit: int = 100) -> dict[str, Any]:
    where = "WHERE acknowledged_at IS NULL" if unread_only else ""
    with connect(db_path) as conn:
        rows = conn.execute(f"SELECT * FROM alert_events {where} ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
        unread = conn.execute("SELECT COUNT(*) FROM alert_events WHERE acknowledged_at IS NULL").fetchone()[0]
    events = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        events.append(item)
    return {"alerts": events, "unread_count": int(unread), "read_only_research": True}


def acknowledge_alert(db_path: Path, alert_id: str) -> dict[str, Any]:
    now = _now()
    with connect(db_path) as conn:
        updated = conn.execute(
            "UPDATE alert_events SET acknowledged_at = COALESCE(acknowledged_at, ?), updated_at = ? WHERE alert_id = ?",
            (now, now, alert_id),
        ).rowcount
        conn.commit()
    if not updated:
        raise ValueError("Unknown alert.")
    return get_alert(db_path, alert_id)
