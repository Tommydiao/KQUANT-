"""Self-reported option trades and deterministic exit reviews; no execution ledger."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from time import monotonic
from .options_data_paths import connect_store
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import options_one_minute as rules
from .market_clock import session_bounds_utc


CONTRACT = re.compile(r"^[A-Za-z0-9.^:-]{5,48}$")
LONG_BRIDGE_OPTION = re.compile(r"^([A-Z][A-Z.]{0,9})([0-9]{6})([CP])([0-9]+)\.US$")
OPERATION = re.compile(r"^[A-Za-z0-9_-]{8,100}$")


def _positive(value) -> bool:
    return rules.finite(value) and value > 0


def _nonnegative(value) -> bool:
    return rules.finite(value) and value >= 0


def _request_fingerprint(event_type, report):
    fields = ("evaluation_id", "contract_id", "quantity", "multiplier", "entry_price",
              "underlying_entry_price", "entry_fees", "exit_fee_estimate") if event_type == "OPEN_REPORTED" else (
              "position_id", "quantity", "exit_price", "exit_fees")
    request = {name: report.get(name) for name in fields}
    for name in ("entry_price", "underlying_entry_price", "entry_fees", "exit_fee_estimate", "exit_price", "exit_fees"):
        if name in request and request[name] is not None:
            request[name] = float(request[name])
    request["reported_execution_at"] = rules.timestamp(report["reported_execution_at"]).isoformat()
    return rules.digest({"event_type": event_type, "reviewer": report["reviewer"], "request": request})


def _idempotent_report(connection, key, event_type, request):
    old = connection.execute("SELECT event_type,payload_json FROM one_minute_manual_events WHERE operation_key=?",
                             (key,)).fetchone()
    if old is None:
        return None
    saved = json.loads(old[1])
    if old[0] != event_type or saved.get("reviewer") != request["reviewer"]:
        raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
    # Old events remain immutable; derive their fingerprint only for this comparison.
    expected = saved.get("request_fingerprint") or _request_fingerprint(event_type, saved)
    if expected != _request_fingerprint(event_type, request):
        raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
    return saved


def open_report(payload: dict, *, reviewer: str, path: Path = rules.STORE,
                now: datetime | None = None, trend_path: Path | None = None) -> dict:
    current = rules.timestamp(now or datetime.now(UTC))
    key = str(payload.get("operation_key") or "")
    if not reviewer or reviewer == "local@kquant.local":
        raise PermissionError("AUTHENTICATED_LOCAL_OWNER_REQUIRED")
    if not OPERATION.fullmatch(key):
        raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
    evaluation_id = str(payload.get("evaluation_id") or "")
    contract_id = str(payload.get("contract_id") or "").upper()
    quantity = payload.get("quantity")
    multiplier = payload.get("multiplier")
    price = payload.get("entry_price")
    underlying = payload.get("underlying_entry_price")
    entry_fees = payload.get("entry_fees")
    exit_fee_estimate = payload.get("exit_fee_estimate")
    if not CONTRACT.fullmatch(contract_id) or type(quantity) is not int or quantity <= 0:
        raise ValueError("CONTRACT_OR_QUANTITY_INVALID")
    if type(multiplier) is not int or multiplier <= 0 or not _positive(price):
        raise ValueError("MULTIPLIER_OR_PREMIUM_INVALID")
    if underlying is not None and not _positive(underlying):
        raise ValueError("UNDERLYING_REFERENCE_INVALID")
    if entry_fees is not None and not _nonnegative(entry_fees):
        raise ValueError("ENTRY_FEES_INVALID")
    if exit_fee_estimate is not None and not _nonnegative(exit_fee_estimate):
        raise ValueError("EXIT_FEE_ESTIMATE_INVALID")
    executed_at = rules.timestamp(payload["executed_at"])
    if executed_at > current + timedelta(seconds=60):
        raise ValueError("FUTURE_EXECUTION_TIME")
    request = {"evaluation_id": evaluation_id, "contract_id": contract_id, "quantity": quantity,
               "multiplier": multiplier, "entry_price": price, "underlying_entry_price": underlying,
               "entry_fees": entry_fees, "exit_fee_estimate": exit_fee_estimate,
               "reported_execution_at": executed_at.isoformat(), "reviewer": reviewer}
    position_id = rules.digest([evaluation_id, contract_id, key])
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.1)) as connection:
        connection.row_factory = sqlite3.Row
        old = _idempotent_report(connection, key, "OPEN_REPORTED", request)
        if old is not None:
            return old
        row = connection.execute("SELECT payload_json FROM one_minute_evaluations WHERE evaluation_id=?", (evaluation_id,)).fetchone()
        from . import options_opening_trend as trend
        from . import options_opening_trend_store as trend_store
        evaluation = json.loads(row[0]) if row else trend_store.detail(evaluation_id, trend_path or trend_store.STORE)
        if not evaluation:
            raise ValueError("ONE_MINUTE_EVALUATION_NOT_FOUND")
        from .options_opening_momentum import POLICY_ID as MOMENTUM_ID
        if evaluation.get("policy_id") not in {rules.load_policy()["policy_id"], trend.POLICY_ID, MOMENTUM_ID}:
            raise ValueError("STRATEGY_VERSION_MISMATCH")
        policy = evaluation.get("policy_snapshot") or rules.load_policy()
        if evaluation["policy_id"] in {trend.POLICY_ID, MOMENTUM_ID} and (
                policy.get("policy_id") != evaluation["policy_id"] or rules.digest(
                {k: v for k, v in policy.items() if k != "policy_hash"}) != evaluation["policy_hash"]):
            raise ValueError("POSITION_POLICY_HASH_MISMATCH")
        if evaluation.get("contract_id") and evaluation["contract_id"] != contract_id:
            raise ValueError("REPORTED_CONTRACT_DIFFERS_FROM_SIGNAL")
        identity = LONG_BRIDGE_OPTION.fullmatch(contract_id)
        if not identity:
            raise ValueError("REPORTED_CONTRACT_IDENTITY_UNVERIFIED")
        underlying_symbol, expiry, right_code, strike = identity.groups()
        try:
            datetime.strptime("20" + expiry, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("REPORTED_CONTRACT_IDENTITY_UNVERIFIED") from exc
        if (underlying_symbol != evaluation["symbol"].removesuffix(".US")
                or {"C": "CALL", "P": "PUT"}[right_code] != evaluation["right"]
                or int(strike) <= 0):
            raise ValueError("REPORTED_CONTRACT_IDENTITY_MISMATCH")
        # A user may report an independently placed trade for risk tracking; it is not a qualified signal.
        signal_link = "QUALIFIED_SIGNAL" if evaluation.get("state") == "QUALIFIED_SIGNAL" or evaluation.get("published_candidate") else "RESEARCH_OBSERVATION_ONLY"
        report = {"position_id": position_id, "operation_key": key,
            "request_fingerprint": _request_fingerprint("OPEN_REPORTED", request),
            "evaluation_id": evaluation_id, "economic_event_id": evaluation["event_id"],
            "strategy_hash": evaluation["policy_hash"], "scope_hash": evaluation["scope_hash"],
            "strategy_id": evaluation["policy_id"], "policy_snapshot": policy,
            "symbol": evaluation["symbol"], "right": evaluation["right"], "contract_id": contract_id,
            "quantity": quantity, "open_quantity": quantity, "multiplier": multiplier,
            "entry_price": float(price), "underlying_entry_price": float(underlying) if underlying is not None else None,
            "entry_fees": float(entry_fees) if entry_fees is not None else None,
            "exit_fee_estimate": float(exit_fee_estimate) if exit_fee_estimate is not None else None,
            "trigger_low": evaluation.get("bar_evidence", {}).get("low"),
            "trigger_high": evaluation.get("bar_evidence", {}).get("high"),
            "reported_execution_at": executed_at.isoformat(), "recorded_at": current.isoformat(),
            "reviewer": reviewer, "state": "OPEN_REPORTED", "signal_link": signal_link,
            "identity_basis": "LONGBRIDGE_SYMBOL_ENCODING_NOT_BROKER_VERIFIED",
            "evidence_class": "USER_REPORTED_NOT_BROKER_VERIFIED", "broker_verified": False,
            "paper_fill": False, "real_order_created": False}
    event_id = rules.digest([position_id, key, "OPEN_REPORTED"])
    with closing(connect_store(path, timeout=.1)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        old = _idempotent_report(connection, key, "OPEN_REPORTED", request)
        if old is not None:
            return old
        connection.execute("INSERT INTO one_minute_manual_positions VALUES (?,?,?,?,?,?,?,?,?)",
            (position_id, evaluation_id, report["symbol"], report["right"], contract_id,
             executed_at.isoformat(), quantity, "OPEN_REPORTED", rules.canonical(report)))
        connection.execute("INSERT INTO one_minute_manual_events VALUES (?,?,?,?,?,?)",
            (event_id, position_id, key, "OPEN_REPORTED", current.isoformat(), rules.canonical(report)))
    return report


def exit_report(payload: dict, *, reviewer: str, path: Path = rules.STORE,
                now: datetime | None = None) -> dict:
    current = rules.timestamp(now or datetime.now(UTC))
    key = str(payload.get("operation_key") or "")
    position_id = str(payload.get("position_id") or "")
    quantity = payload.get("quantity")
    price = payload.get("exit_price")
    fees = payload.get("exit_fees")
    if not reviewer or reviewer == "local@kquant.local":
        raise PermissionError("AUTHENTICATED_LOCAL_OWNER_REQUIRED")
    if not OPERATION.fullmatch(key) or len(position_id) != 64:
        raise ValueError("IDEMPOTENCY_OR_POSITION_INVALID")
    if type(quantity) is not int or quantity <= 0 or not _nonnegative(price):
        raise ValueError("EXIT_QUANTITY_OR_PRICE_INVALID")
    if fees is not None and not _nonnegative(fees):
        raise ValueError("EXIT_FEES_INVALID")
    executed_at = rules.timestamp(payload["executed_at"])
    if executed_at > current + timedelta(seconds=60):
        raise ValueError("FUTURE_EXECUTION_TIME")
    request = {"position_id": position_id, "quantity": quantity, "exit_price": price, "exit_fees": fees,
               "reported_execution_at": executed_at.isoformat(), "reviewer": reviewer}
    with closing(connect_store(path, timeout=.1)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        old = _idempotent_report(connection, key, "EXIT_REPORTED", request)
        if old is not None:
            return old
        row = connection.execute("SELECT payload_json FROM one_minute_manual_positions WHERE position_id=?", (position_id,)).fetchone()
        if not row:
            raise ValueError("POSITION_NOT_FOUND")
        position = json.loads(row[0])
        if position["open_quantity"] < quantity or position["open_quantity"] <= 0:
            raise ValueError("EXIT_EXCEEDS_REPORTED_OPEN_QUANTITY")
        if executed_at < rules.timestamp(position["reported_execution_at"]):
            raise ValueError("EXIT_BEFORE_REPORTED_ENTRY")
        remaining = position["open_quantity"] - quantity
        report = {"position_id": position_id, "operation_key": key, "event_type": "EXIT_REPORTED",
            "request_fingerprint": _request_fingerprint("EXIT_REPORTED", request),
            "contract_id": position["contract_id"], "quantity": quantity, "exit_price": float(price),
            "exit_fees": float(fees) if fees is not None else None, "remaining_quantity": remaining,
            "reported_execution_at": executed_at.isoformat(), "recorded_at": current.isoformat(),
            "reviewer": reviewer, "evidence_class": "USER_REPORTED_NOT_BROKER_VERIFIED",
            "broker_verified": False, "paper_fill": False, "real_order_created": False}
        event_id = rules.digest([position_id, key, "EXIT_REPORTED"])
        connection.execute("INSERT INTO one_minute_manual_events VALUES (?,?,?,?,?,?)",
            (event_id, position_id, key, "EXIT_REPORTED", current.isoformat(), rules.canonical(report)))
        position["open_quantity"] = remaining
        position["state"] = "OPEN_REPORTED" if remaining else "CLOSED_REPORTED"
        position["updated_at"] = current.isoformat()
        connection.execute("UPDATE one_minute_manual_positions SET open_quantity=?,state=?,payload_json=? WHERE position_id=?",
            (remaining, position["state"], rules.canonical(position), position_id))
    return report


def operation_status(key: str, *, reviewer: str, path: Path = rules.STORE) -> dict:
    if not reviewer or reviewer == "local@kquant.local":
        raise PermissionError("AUTHENTICATED_LOCAL_OWNER_REQUIRED")
    if not OPERATION.fullmatch(key):
        raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
    deadline = monotonic() + .5
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.1)) as connection:
        connection.set_progress_handler(lambda: int(monotonic() >= deadline), 100)
        # One read snapshot keeps the immutable operation and current balance consistent.
        row = connection.execute(
            "SELECT e.payload_json,p.payload_json FROM one_minute_manual_events e "
            "LEFT JOIN one_minute_manual_positions p ON p.position_id=e.position_id "
            "WHERE e.operation_key=?", (key,)).fetchone()
        report = json.loads(row[0]) if row else None
    # Do not disclose another user's operation or confuse a failed read with NOT_FOUND.
    if not report or report.get("reviewer") != reviewer:
        return {"operation_key": key, "operation_status": "NOT_FOUND"}
    position = json.loads(row[1]) if row[1] else None
    if position and (position.get("position_id") != report.get("position_id")
                     or position.get("reviewer") != reviewer):
        position = None
    return {"operation_key": key, "operation_status": "COMMITTED", "report": report,
            "current_position": position, "position_snapshot_state": "AVAILABLE" if position else "UNAVAILABLE"}


def manual_status(path: Path = rules.STORE, *, limit: int = 100) -> dict:
    if not path.exists():
        return {"positions": [], "alerts": [], "record_kind": "USER_REPORTED_NOT_BROKER_VERIFIED",
                "status": "UNAVAILABLE", "position_records_complete": False,
                "old_position_continuity": "UNKNOWN", "continuity_reason": "MANUAL_STORE_MISSING",
                "paper_enabled": False, "real_orders_enabled": False}
    deadline = monotonic() + .5
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.1)) as connection:
        connection.set_progress_handler(lambda: int(monotonic() >= deadline), 100)
        connection.execute("PRAGMA query_only=ON")
        boundary = None
        boundary_error = None
        has_boundary = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='data_epoch_boundary'").fetchone()
        if has_boundary:
            saved = connection.execute("SELECT payload_json FROM data_epoch_boundary WHERE id=1").fetchone()
            try:
                boundary = json.loads(saved[0]) if saved else None
                if (not isinstance(boundary, dict)
                        or boundary.get("schema") != "KQUANT_NEW_MINUTE_EPOCH_V1"
                        or boundary.get("record_kind") != "NEW_DATA_NOT_OLD_RECOVERY"
                        or boundary.get("old_position_continuity") != "UNKNOWN"
                        or boundary.get("complete_restoration_claimed") is not False
                        or "manual_position_revisions" not in boundary.get("unresolved_old_records", [])
                        or not boundary.get("epoch_id") or not boundary.get("session")):
                    raise ValueError("INVALID_EPOCH_BOUNDARY")
            except (ValueError, TypeError):
                boundary = None
                boundary_error = "EPOCH_BOUNDARY_INVALID"
        elif re.fullmatch(r"options_one_minute-epoch-[0-9]{8}", path.parent.name):
            boundary_error = "EPOCH_BOUNDARY_MISSING"
        positions = [json.loads(row[0]) for row in connection.execute(
            "SELECT payload_json FROM one_minute_manual_positions ORDER BY opened_at DESC LIMIT ?", (limit,))]
        alerts = [json.loads(row[0]) for row in connection.execute(
            "SELECT payload_json FROM one_minute_exit_alerts ORDER BY created_at DESC LIMIT ?", (limit,))]
    continuity = ({"status": "CURRENT_EPOCH_ONLY", "position_records_complete": False,
                   "old_position_continuity": "UNKNOWN", "continuity_reason": "OLD_MINUTE_BUSINESS_NOT_RESTORED",
                   "data_epoch": {"epoch_id": boundary["epoch_id"], "session": boundary["session"],
                                  "record_kind": boundary["record_kind"]}}
                  if boundary else {"status": "AVAILABLE", "record_scope": "CURRENT_STORE_ONLY"})
    if boundary_error:
        continuity = {"status": "UNAVAILABLE", "position_records_complete": False,
                      "old_position_continuity": "UNKNOWN", "continuity_reason": boundary_error}
    return {"positions": positions, "alerts": alerts, **continuity,
            "record_kind": "USER_REPORTED_NOT_BROKER_VERIFIED", "paper_enabled": False,
            "real_orders_enabled": False}


def exit_reasons(position: dict, bars: list[dict], *, now: datetime,
                 quote: dict | None = None, underlying_quote: dict | None = None,
                 monitor_updates: list | None = None) -> list[dict]:
    """Return review reasons only; no exit is inferred to have executed."""
    current = rules.timestamp(now)
    policy = position.get("policy_snapshot") or rules.load_policy()
    from .options_opening_trend import POLICY_ID
    from .options_opening_momentum import POLICY_ID as MOMENTUM_ID
    if position.get("strategy_id") in {POLICY_ID, MOMENTUM_ID}:
        from .options_opening_trend_risk import exit_reasons as trend_exit_reasons
        if not position.get("open_quantity"):
            return []
        reasons = trend_exit_reasons(position, bars, now=current, underlying_quote=underlying_quote,
                                    monitor_updates=monitor_updates)
        if any(row["reason"] == "POSITION_POLICY_HASH_MISMATCH" for row in reasons):
            return reasons
        return reasons + _reference_loss_reasons(position, quote, current, policy)
    start = rules.timestamp(position["reported_execution_at"])
    session_day = start.astimezone(rules.NY).date()
    if not position.get("open_quantity"):
        return []
    if current.astimezone(rules.NY).date() > session_day:
        return [{"reason": "UNCONFIRMED_OVERNIGHT_POSITION", "at": current.isoformat(),
                 "reported_entry_session": session_day.isoformat()}]
    if not is_same_session(current, session_day):
        return []
    _, closing = session_bounds_utc(session_day)
    planned = closing - timedelta(minutes=policy["planned_exit_minutes_before_close"])
    reasons = []
    if current >= closing - timedelta(minutes=policy["exit_reminder_minutes_before_close"]):
        reasons.append({"reason": "SESSION_WIND_DOWN_REVIEW", "at": current.isoformat(),
                        "planned_exit_at": planned.isoformat()})
    if current >= min(start + timedelta(minutes=policy["holding_max_minutes"]), planned):
        reasons.append({"reason": "MAX_HOLD_OR_PLANNED_EXIT", "at": current.isoformat(),
                        "max_hold_at": (start + timedelta(minutes=policy["holding_max_minutes"])).isoformat(),
                        "planned_exit_at": planned.isoformat()})
    valid = []
    for bar in bars:
        try:
            available, received = rules.timestamp(bar["available_at"]), rules.timestamp(bar["received_at"])
            if (bar.get("symbol") == position["symbol"] and bar.get("interval") == "1m"
                    and bar.get("closed") and available <= current and received >= available
                    and received <= current and rules.finite(bar.get("close"))
                    and rules.finite(bar.get("high")) and rules.finite(bar.get("low"))):
                valid.append(bar)
        except (ValueError, KeyError, TypeError):
            continue
    valid = [bar for bar in valid if rules.timestamp(bar["available_at"]) >= start]
    valid.sort(key=lambda bar: bar["open_at"])
    latest = valid[-1] if valid else None
    fresh = bool(latest and current - rules.timestamp(latest["available_at"]) <= timedelta(minutes=2))
    if not fresh:
        reasons.append({"reason": "UNDERLYING_BAR_STALE_EXIT_UNVERIFIED", "at": current.isoformat(),
                        "last_bar_at": latest["available_at"] if latest else None})
    entry = position.get("underlying_entry_price")
    initial_line = position.get("trigger_low") if position["right"] == "CALL" else position.get("trigger_high")
    r = (entry - initial_line if position["right"] == "CALL" else initial_line - entry
         ) if _positive(entry) and _positive(initial_line) else None
    if r is not None and r > 0 and latest and fresh:
        direction = 1 if position["right"] == "CALL" else -1
        favorable = direction * (latest["close"] - entry)
        line = initial_line
        activation = next((rules.timestamp(bar["available_at"]) for bar in valid
                           if direction * (bar["close"] - entry) >= r), None)
        if activation is not None:
            groups: dict[datetime, dict[datetime, dict]] = {}
            for bar in valid:
                opened = rules.timestamp(bar["open_at"])
                group = opened.replace(minute=opened.minute - opened.minute % 5, second=0, microsecond=0)
                groups.setdefault(group, {})[opened] = bar
            complete = []
            for group, rows in sorted(groups.items()):
                expected = {group + timedelta(minutes=offset) for offset in range(5)}
                if set(rows) != expected or group + timedelta(minutes=5) < activation:
                    continue
                complete.append({"low": min(row["low"] for row in rows.values()),
                                 "high": max(row["high"] for row in rows.values()),
                                 "end": group + timedelta(minutes=5)})
            for older, newer in zip(complete, complete[1:]):
                if newer["end"] - older["end"] != timedelta(minutes=5):
                    continue
                if direction == 1:
                    line = max(line, min(older["low"], newer["low"]))
                else:
                    line = min(line, max(older["high"], newer["high"]))
        if direction * (latest["close"] - line) < 0:
            reasons.append({"reason": "ONE_MINUTE_STRUCTURE_BREAK", "at": latest["available_at"],
                            "line": line, "close": latest["close"], "r": r,
                            "trailing_activated_at": activation.isoformat() if activation else None})
        if current >= start + timedelta(minutes=policy["holding_review_minutes"]) and favorable < .5 * r:
            reasons.append({"reason": "THIRTY_MINUTE_PROGRESS_BELOW_HALF_R", "at": current.isoformat(),
                            "favorable": favorable, "required": .5 * r, "r": r})
    return reasons + _reference_loss_reasons(position, quote, current, policy)


def _reference_loss_reasons(position, quote, current, policy):
    reasons = []
    fees_unknown = position.get("entry_fees") is None or position.get("exit_fee_estimate") is None
    if fees_unknown:
        reasons.append({"reason": "REFERENCE_LOSS_FEES_UNKNOWN", "at": current.isoformat()})
    if not quote:
        reasons.append({"reason": "OPTION_QUOTE_STALE_EXIT_UNVERIFIED", "at": current.isoformat()})
        return reasons
    if quote:
        try:
            quote_time = rules.timestamp(quote["bbo_received_at"])
            bid = quote["bid"]
            if (quote["contract_id"] == position["contract_id"]
                    and rules.finite(quote["multiplier"]) and quote["multiplier"] == position["multiplier"]
                    and quote.get("depth_status") == "available" and _nonnegative(bid)
                    and timedelta(0) <= current - quote_time <= timedelta(seconds=3)):
                if fees_unknown:
                    return reasons
                quantity = position["open_quantity"]
                cost = quantity * position["multiplier"] * position["entry_price"]
                cost += position["entry_fees"] * quantity / position["quantity"]
                liquidation = quantity * position["multiplier"] * bid - position["exit_fee_estimate"]
                loss_fraction = (cost - liquidation) / cost if cost > 0 else None
                if loss_fraction is not None and loss_fraction >= policy["premium_loss_review_fraction"]:
                    reasons.append({"reason": "NET_REFERENCE_PREMIUM_LOSS_REVIEW", "at": current.isoformat(),
                                    "quote_received_at": quote_time.isoformat(), "loss_fraction": loss_fraction,
                                    "quote_evidence_class": "RECEIPT_TIME_REFERENCE_NOT_EXCHANGE_FILL"})
            else:
                reasons.append({"reason": "OPTION_QUOTE_STALE_EXIT_UNVERIFIED", "at": current.isoformat()})
        except (KeyError, TypeError, ValueError, OverflowError):
            reasons.append({"reason": "OPTION_QUOTE_STALE_EXIT_UNVERIFIED", "at": current.isoformat()})
    return reasons


def is_same_session(now: datetime, session_day) -> bool:
    return now.astimezone(rules.NY).date() == session_day


def persist_monitor_state(position: dict, update: dict, *, path: Path = rules.STORE) -> bool:
    """Append monitoring evidence in the existing store without changing any trade."""
    with connect_store(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT payload_json,open_quantity FROM one_minute_manual_positions WHERE position_id=?",
                                 (position["position_id"],)).fetchone()
        if not row or row[1] <= 0 or row[1] != position.get("open_quantity"):
            return False
        current = json.loads(row[0])
        if current["contract_id"] != position["contract_id"] or current["strategy_hash"] != update.get("policy_hash"):
            return False
        old = current.get("trend_monitor") or {}
        if old.get("checked_at") and rules.timestamp(update["checked_at"]) <= rules.timestamp(old["checked_at"]):
            return False
        merged = dict(update)
        if old.get("activated_at"):
            merged["activated_at"] = old["activated_at"]
        if rules.finite(old.get("structure_line")):
            merged["structure_line"] = (max if current["right"] == "CALL" else min)(old["structure_line"], merged["structure_line"])
        current["trend_monitor"] = merged
        connection.execute("UPDATE one_minute_manual_positions SET payload_json=? WHERE position_id=?",
                           (rules.canonical(current), position["position_id"]))
        key = "monitor-" + rules.digest([position["position_id"], merged])
        connection.execute("INSERT OR IGNORE INTO one_minute_manual_events VALUES (?,?,?,?,?,?)",
            (rules.digest(key), position["position_id"], key, "TREND_MONITOR_UPDATED", merged["checked_at"], rules.canonical(merged)))
        return True


def persist_exit_alert(position: dict, reason: dict, *, path: Path = rules.STORE,
                       now: datetime | None = None) -> bool:
    current = rules.timestamp(now or datetime.now(UTC))
    alert_id = rules.digest([position["position_id"], reason["reason"]])
    payload = {"alert_id": alert_id, "position_id": position["position_id"],
               "contract_id": position["contract_id"], "symbol": position["symbol"],
               "right": position["right"], "reason": reason["reason"], "evidence": reason,
               "created_at": current.isoformat(), "exit_confirmed": False,
               "real_order_created": False}
    with connect_store(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        current_position = connection.execute(
            "SELECT contract_id,open_quantity FROM one_minute_manual_positions WHERE position_id=?",
            (position["position_id"],)).fetchone()
        if (current_position is None or current_position[0] != position["contract_id"]
                or current_position[1] <= 0 or current_position[1] != position.get("open_quantity")):
            return False
        return bool(connection.execute("INSERT OR IGNORE INTO one_minute_exit_alerts VALUES (?,?,?,?,?)",
            (alert_id, position["position_id"], reason["reason"], current.isoformat(), rules.canonical(payload))).rowcount)
