from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .stock_store import connect


PREFERENCE_ID = "local-user"
ROUTINE_SEVERITIES = {"INFO", "ACTION"}
RISK_SEVERITIES = {"RISK", "CRITICAL"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _configured() -> bool:
    return bool(os.getenv("KQUANT_WEB_PUSH_PUBLIC_KEY") and os.getenv("KQUANT_WEB_PUSH_PRIVATE_KEY"))


def _enabled() -> bool:
    return os.getenv("KQUANT_WEB_PUSH_ENABLED", "false").lower() == "true"


def notification_preferences(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO notification_preferences(
              preference_id, web_push_enabled, quiet_start, quiet_end, timezone,
              daily_routine_limit, updated_at
            ) VALUES (?, 1, '22:30', '08:00', 'Asia/Shanghai', 5, ?)
            """,
            (PREFERENCE_ID, _now()),
        )
        row = conn.execute("SELECT * FROM notification_preferences WHERE preference_id = ?", (PREFERENCE_ID,)).fetchone()
        conn.commit()
    payload = dict(row)
    payload["web_push_enabled"] = bool(payload["web_push_enabled"])
    return payload


def update_notification_preferences(db_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    current = notification_preferences(db_path)
    quiet_start = str(payload.get("quiet_start", current["quiet_start"]))
    quiet_end = str(payload.get("quiet_end", current["quiet_end"]))
    timezone = str(payload.get("timezone", current["timezone"]))
    daily_limit = max(1, min(20, int(payload.get("daily_routine_limit", current["daily_routine_limit"]))))
    for value in (quiet_start, quiet_end):
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise ValueError("Quiet hours must use HH:MM.") from exc
    try:
        ZoneInfo(timezone)
    except Exception as exc:  # noqa: BLE001 - platform timezone data may vary.
        raise ValueError("Unknown timezone.") from exc
    enabled = bool(payload.get("web_push_enabled", current["web_push_enabled"]))
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE notification_preferences
            SET web_push_enabled=?, quiet_start=?, quiet_end=?, timezone=?, daily_routine_limit=?, updated_at=?
            WHERE preference_id=?
            """,
            (int(enabled), quiet_start, quiet_end, timezone, daily_limit, _now(), PREFERENCE_ID),
        )
        conn.commit()
    return notification_preferences(db_path)


def web_push_status(db_path: Path) -> dict[str, Any]:
    preferences = notification_preferences(db_path)
    with connect(db_path) as conn:
        active = int(conn.execute("SELECT COUNT(*) FROM web_push_subscriptions WHERE enabled=1").fetchone()[0])
        total = int(conn.execute("SELECT COUNT(*) FROM web_push_subscriptions").fetchone()[0])
        latest = conn.execute(
            "SELECT status, created_at FROM alert_delivery_attempts WHERE channel='web_push' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return {
        "channel": "web_push",
        "enabled": _enabled() and bool(preferences["web_push_enabled"]),
        "configured": _configured(),
        "active_subscriptions": active,
        "total_subscriptions": total,
        "latest_delivery": dict(latest) if latest else None,
        "preferences": preferences,
        "ios_requirement": "iOS/iPadOS 16.4+ and KQUANT added to the Home Screen",
        "private_key_exposed": False,
    }


def public_key() -> dict[str, Any]:
    return {
        "configured": _configured(),
        "public_key": os.getenv("KQUANT_WEB_PUSH_PUBLIC_KEY", "") if _configured() else "",
        "private_key_exposed": False,
    }


def subscribe(db_path: Path, subscription: dict[str, Any], user_agent: str = "") -> dict[str, Any]:
    endpoint = str(subscription.get("endpoint") or "").strip()
    keys = dict(subscription.get("keys") or {})
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or not p256dh or not auth:
        raise ValueError("A valid HTTPS Push subscription is required.")
    endpoint_hash = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
    subscription_id = f"push-{endpoint_hash[:24]}"
    now = _now()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO web_push_subscriptions(
              subscription_id, endpoint, endpoint_hash, p256dh, auth, user_agent,
              enabled, failure_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
              p256dh=excluded.p256dh, auth=excluded.auth, user_agent=excluded.user_agent,
              enabled=1, failure_count=0, updated_at=excluded.updated_at
            """,
            (subscription_id, endpoint, endpoint_hash, p256dh, auth, user_agent[:500], now, now),
        )
        conn.commit()
    return {"subscription_id": subscription_id, "status": "active", "endpoint_stored": True, "secret_values_exposed": False}


def unsubscribe(db_path: Path, endpoint: str) -> dict[str, Any]:
    endpoint_hash = hashlib.sha256(str(endpoint).encode("utf-8")).hexdigest()
    with connect(db_path) as conn:
        updated = conn.execute(
            "UPDATE web_push_subscriptions SET enabled=0, updated_at=? WHERE endpoint_hash=?",
            (_now(), endpoint_hash),
        ).rowcount
        conn.commit()
    return {"status": "disabled" if updated else "not_found", "endpoint_exposed": False}


def _in_quiet_hours(preferences: dict[str, Any], moment: datetime | None = None) -> bool:
    local = (moment or datetime.now(UTC)).astimezone(ZoneInfo(str(preferences["timezone"])))
    current = local.strftime("%H:%M")
    start, end = str(preferences["quiet_start"]), str(preferences["quiet_end"])
    return start <= current < end if start < end else current >= start or current < end


def _routine_deliveries_today(db_path: Path, preferences: dict[str, Any]) -> int:
    local = datetime.now(UTC).astimezone(ZoneInfo(str(preferences["timezone"])))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC).isoformat()
    with connect(db_path) as conn:
        return int(conn.execute(
            """
            SELECT COUNT(DISTINCT COALESCE(alert_id, attempt_id))
            FROM alert_delivery_attempts
            WHERE channel='web_push' AND status='sent' AND severity IN ('INFO','ACTION') AND created_at >= ?
            """,
            (start,),
        ).fetchone()[0])


def deliver_web_push(
    db_path: Path,
    *,
    alert_id: str | None,
    severity: str,
    payload: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    severity = severity.upper() if severity.upper() in ROUTINE_SEVERITIES | RISK_SEVERITIES else "INFO"
    preferences = notification_preferences(db_path)
    if not force and (not _enabled() or not preferences["web_push_enabled"]):
        return {"status": "disabled", "reason": "web_push_not_enabled", "sent": 0}
    if not _configured():
        return {"status": "disabled", "reason": "vapid_not_configured", "sent": 0}
    if not force and severity in ROUTINE_SEVERITIES:
        if _in_quiet_hours(preferences):
            return {"status": "deferred", "reason": "quiet_hours", "sent": 0}
        if _routine_deliveries_today(db_path, preferences) >= int(preferences["daily_routine_limit"]):
            return {"status": "deferred", "reason": "daily_limit", "sent": 0}
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return {"status": "failed", "reason": "pywebpush_not_installed", "sent": 0}
    with connect(db_path) as conn:
        subscriptions = [dict(row) for row in conn.execute("SELECT * FROM web_push_subscriptions WHERE enabled=1").fetchall()]
    sent = 0
    failed = 0
    for subscription in subscriptions:
        delivered = False
        expired = False
        for attempt in range(1, 4):
            status = "failed"
            reason = "delivery_failed"
            try:
                webpush(
                    subscription_info={
                        "endpoint": subscription["endpoint"],
                        "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
                    },
                    data=json.dumps(payload, ensure_ascii=False),
                    vapid_private_key=os.environ["KQUANT_WEB_PUSH_PRIVATE_KEY"],
                    vapid_claims={"sub": os.getenv("KQUANT_WEB_PUSH_SUBJECT", "mailto:local@kquant.invalid")},
                    ttl=300 if severity in RISK_SEVERITIES else 1800,
                )
                status, reason, delivered = "sent", "delivered", True
            except WebPushException as exc:
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None)
                reason = f"push_http_{status_code}" if status_code else "push_delivery_error"
                if status_code in {404, 410}:
                    with connect(db_path) as conn:
                        conn.execute("UPDATE web_push_subscriptions SET enabled=0, last_failure_at=?, updated_at=? WHERE subscription_id=?", (_now(), _now(), subscription["subscription_id"]))
                        conn.commit()
                    expired = True
            _record_attempt(db_path, alert_id, subscription["subscription_id"], severity, attempt, status, reason)
            if delivered:
                with connect(db_path) as conn:
                    conn.execute("UPDATE web_push_subscriptions SET failure_count=0, last_success_at=?, updated_at=? WHERE subscription_id=?", (_now(), _now(), subscription["subscription_id"]))
                    conn.commit()
                sent += 1
                break
            if expired:
                break
            if attempt < 3:
                time.sleep(0.05 * attempt)
        if not delivered:
            failed += 1
            with connect(db_path) as conn:
                conn.execute("UPDATE web_push_subscriptions SET failure_count=failure_count+1, last_failure_at=?, updated_at=? WHERE subscription_id=?", (_now(), _now(), subscription["subscription_id"]))
                conn.commit()
    return {"status": "sent" if sent and not failed else "partial" if sent else "failed" if subscriptions else "no_subscriptions", "sent": sent, "failed": failed}


def _record_attempt(db_path: Path, alert_id: str | None, subscription_id: str, severity: str, attempt: int, status: str, reason: str) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO alert_delivery_attempts(attempt_id, alert_id, subscription_id, channel, severity, attempt, status, reason, created_at) VALUES (?, ?, ?, 'web_push', ?, ?, ?, ?, ?)",
            (f"attempt-{uuid.uuid4().hex[:24]}", alert_id, subscription_id, severity, attempt, status, reason[:200], _now()),
        )
        conn.commit()
