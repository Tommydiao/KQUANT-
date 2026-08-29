from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, time as datetime_time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

from .config import Settings
from .db.migrations import connect, migrate


NOTIFICATION_DAILY_LIMIT = 5
MAX_DELIVERY_ATTEMPTS = 3
RISK_SEVERITIES = frozenset({"RISK", "CRITICAL"})


@dataclass
class NotificationHub:
    _subscribers: set[asyncio.Queue[str]] = field(default_factory=set)

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.discard(queue)

    def publish(self, payload: dict[str, Any]) -> None:
        message = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A slow browser must not block the deterministic evaluator.
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                except asyncio.QueueEmpty:
                    pass

    async def events(self, queue: asyncio.Queue[str]) -> AsyncIterator[str]:
        while True:
            yield await queue.get()


def notification_status(settings: Settings, db_path: Path) -> dict[str, Any]:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM web_push_subscriptions WHERE status='active'").fetchone()
        active_subscriptions = int(row["count"])
    return {
        "enabled": settings.notifications_enabled,
        "web_push": {
            "configured": bool(settings.web_push_public_key and settings.web_push_private_key and settings.web_push_subject),
            "active_subscriptions": active_subscriptions,
        },
        "telegram": {"enabled": settings.telegram_enabled, "configured": bool(settings.telegram_bot_token and settings.telegram_chat_id)},
        "delivery_mode": "disabled" if not settings.notifications_enabled else "configured" if settings.web_push_public_key and settings.web_push_private_key and settings.web_push_subject else "not_configured",
        "read_only": True,
    }


def save_web_push_subscription(db_path: Path, owner_email: str, subscription: dict[str, Any]) -> dict[str, Any]:
    migrate(db_path)
    endpoint = str(subscription.get("endpoint") or "").strip()
    keys = subscription.get("keys") or {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth_key = str(keys.get("auth") or "").strip()
    if not endpoint or not p256dh or not auth_key:
        raise ValueError("endpoint and subscription keys are required")
    endpoint_hash = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
    now = datetime.now(UTC).isoformat()
    subscription_id = f"push_{endpoint_hash[:24]}"
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO web_push_subscriptions(
              subscription_id,owner_email,endpoint_hash,endpoint,p256dh,auth_key,
              status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(endpoint_hash) DO UPDATE SET
              owner_email=excluded.owner_email,p256dh=excluded.p256dh,
              auth_key=excluded.auth_key,status='active',updated_at=excluded.updated_at
            """,
            (subscription_id, owner_email, endpoint_hash, endpoint, p256dh, auth_key, "active", now, now),
        )
    return {"subscription_id": subscription_id, "status": "active", "endpoint_hash": endpoint_hash}


def remove_web_push_subscription(db_path: Path, owner_email: str, endpoint: str) -> bool:
    migrate(db_path)
    endpoint_hash = hashlib.sha256(endpoint.strip().encode("utf-8")).hexdigest()
    with connect(db_path) as conn:
        cursor = conn.execute(
            "UPDATE web_push_subscriptions SET status='revoked',updated_at=? WHERE owner_email=? AND endpoint_hash=?",
            (datetime.now(UTC).isoformat(), owner_email, endpoint_hash),
        )
        return cursor.rowcount > 0


def get_notification_preferences(db_path: Path, owner_email: str) -> dict[str, Any]:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM notification_preferences WHERE owner_email=?", (owner_email,)).fetchone()
    if row is None:
        return {"owner_email": owner_email, "enabled": False, "web_push_enabled": False, "telegram_enabled": False, "quiet_start": None, "quiet_end": None, "timezone": "Asia/Shanghai"}
    value = dict(row)
    for key in ("enabled", "web_push_enabled", "telegram_enabled"):
        value[key] = bool(value[key])
    return value


def set_notification_preferences(db_path: Path, owner_email: str, values: dict[str, Any]) -> dict[str, Any]:
    migrate(db_path)
    now = datetime.now(UTC).isoformat()
    current = get_notification_preferences(db_path, owner_email)
    merged = {**current, **values, "owner_email": owner_email, "updated_at": now}
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO notification_preferences(
              owner_email,enabled,web_push_enabled,telegram_enabled,
              quiet_start,quiet_end,timezone,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(owner_email) DO UPDATE SET
              enabled=excluded.enabled,web_push_enabled=excluded.web_push_enabled,
              telegram_enabled=excluded.telegram_enabled,quiet_start=excluded.quiet_start,
              quiet_end=excluded.quiet_end,timezone=excluded.timezone,updated_at=excluded.updated_at
            """,
            (owner_email, int(bool(merged["enabled"])), int(bool(merged["web_push_enabled"])), int(bool(merged["telegram_enabled"])), merged.get("quiet_start"), merged.get("quiet_end"), merged.get("timezone") or "Asia/Shanghai", now),
        )
    return get_notification_preferences(db_path, owner_email)


def _parse_clock(value: str | None) -> datetime_time | None:
    if not value:
        return None
    try:
        hour, minute = (int(item) for item in value.split(":", 1))
        return datetime_time(hour=hour, minute=minute)
    except (TypeError, ValueError):
        return None


def _in_quiet_window(local_time: datetime_time, start: datetime_time | None, end: datetime_time | None) -> bool:
    if start is None or end is None or start == end:
        return False
    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end


def notification_delivery_policy(
    db_path: Path,
    owner_email: str,
    severity: str,
    *,
    now: datetime | None = None,
    daily_limit: int = NOTIFICATION_DAILY_LIMIT,
) -> dict[str, Any]:
    """Return a delivery decision without changing the EVAL result."""

    preference = get_notification_preferences(db_path, owner_email)
    normalized_severity = str(severity or "INFO").upper()
    if not preference.get("enabled"):
        return {"allowed": False, "reason": "user_notifications_disabled", "count": 0, "daily_limit": daily_limit}
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    try:
        local_zone = ZoneInfo(str(preference.get("timezone") or "Asia/Shanghai"))
    except Exception:
        local_zone = ZoneInfo("UTC")
    local_current = current.astimezone(local_zone)
    if normalized_severity not in RISK_SEVERITIES and _in_quiet_window(
        local_current.timetz().replace(tzinfo=None),
        _parse_clock(preference.get("quiet_start")),
        _parse_clock(preference.get("quiet_end")),
    ):
        return {"allowed": False, "reason": "quiet_hours", "count": 0, "daily_limit": daily_limit}
    local_midnight = datetime.combine(local_current.date(), datetime_time.min, tzinfo=local_zone)
    utc_midnight = local_midnight.astimezone(UTC).isoformat()
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM notification_events WHERE created_at>=? AND severity NOT IN ('RISK','CRITICAL')",
            (utc_midnight,),
        ).fetchone()
    count = int(row["count"])
    if normalized_severity not in RISK_SEVERITIES and count >= max(0, daily_limit):
        return {"allowed": False, "reason": "daily_limit", "count": count, "daily_limit": daily_limit}
    return {"allowed": True, "reason": None, "count": count, "daily_limit": daily_limit}


def deliver_web_push(settings: Settings, db_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Attempt delivery only when all VAPID values are configured."""

    if not settings.notifications_enabled or not (settings.web_push_public_key and settings.web_push_private_key and settings.web_push_subject):
        return {"status": "not_configured", "attempted": 0, "delivered": 0}
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return {"status": "dependency_missing", "attempted": 0, "delivered": 0}
    migrate(db_path)
    with connect(db_path) as conn:
        subscriptions = conn.execute("SELECT * FROM web_push_subscriptions WHERE status='active'").fetchall()
    delivered = 0
    for subscription in subscriptions:
        delivered_this_subscription = False
        for _attempt in range(1, MAX_DELIVERY_ATTEMPTS + 1):
            result = "sent"
            detail = "ok"
            terminal_failure = False
            try:
                webpush(
                    subscription_info={"endpoint": subscription["endpoint"], "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth_key"]}},
                    data=json.dumps(payload, ensure_ascii=False),
                    vapid_private_key=settings.web_push_private_key,
                    vapid_claims={"sub": settings.web_push_subject},
                )
                delivered_this_subscription = True
            except WebPushException as exc:
                result = "failed"
                detail = type(exc).__name__
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if status_code in {404, 410}:
                    terminal_failure = True
                    with connect(db_path) as conn:
                        conn.execute("UPDATE web_push_subscriptions SET status='expired',updated_at=? WHERE subscription_id=?", (datetime.now(UTC).isoformat(), subscription["subscription_id"]))
            except Exception as exc:
                result = "failed"
                detail = type(exc).__name__
            with connect(db_path) as conn:
                conn.execute("INSERT INTO notification_delivery_attempts(notification_id,channel,status,detail,attempted_at) VALUES(?,?,?,?,?)", (payload.get("notification_id", ""), "web_push", result, detail, datetime.now(UTC).isoformat()))
            if delivered_this_subscription or terminal_failure:
                break
        delivered += int(delivered_this_subscription)
    return {"status": "sent" if delivered else "failed", "attempted": len(subscriptions), "delivered": delivered}


def deliver_telegram(settings: Settings, db_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Send an EVAL-authorized notification through Telegram when enabled.

    The bot token is used only in the request URL and is never included in
    response data, delivery details or logs.
    """

    if not settings.notifications_enabled or not settings.telegram_enabled:
        return {"status": "disabled", "attempted": 0, "delivered": 0}
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return {"status": "not_configured", "attempted": 0, "delivered": 0}
    body = f"{payload.get('title', 'KQUANT Crypto')}\n{payload.get('body', '')}"
    if payload.get("deep_link"):
        body += f"\n{payload['deep_link']}"
    endpoint = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    request = Request(
        endpoint,
        data=urlencode({"chat_id": settings.telegram_chat_id, "text": body}).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "KQUANT-CRYPTO/0.2"},
        method="POST",
    )
    status = "failed"
    for _attempt in range(1, MAX_DELIVERY_ATTEMPTS + 1):
        detail = "ok"
        try:
            with urlopen(request, timeout=10.0) as response:
                if getattr(response, "status", 200) >= 400:
                    status = "failed"
                    detail = "http_error"
                else:
                    status = "sent"
        except Exception as exc:
            detail = type(exc).__name__
        migrate(db_path)
        with connect(db_path) as conn:
            conn.execute(
                "INSERT INTO notification_delivery_attempts(notification_id,channel,status,detail,attempted_at) VALUES(?,?,?,?,?)",
                (payload.get("notification_id", ""), "telegram", status, detail, datetime.now(UTC).isoformat()),
            )
        if status == "sent":
            break
    return {"status": status, "attempted": 1, "delivered": int(status == "sent")}


def record_notification(
    db_path: Path,
    *,
    severity: str,
    title: str,
    body: str,
    deep_link: str | None = None,
    metadata: dict[str, Any] | None = None,
    status: str = "queued",
) -> dict[str, Any]:
    migrate(db_path)
    notification_id = f"notice_{uuid4().hex}"
    now = datetime.now(UTC).isoformat()
    payload = {
        "notification_id": notification_id,
        "severity": severity,
        "title": title,
        "body": body,
        "deep_link": deep_link,
        **(metadata or {}),
    }
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO notification_events(notification_id,severity,title,body,deep_link,payload_json,status,created_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (notification_id, severity, title, body, deep_link, json.dumps(payload, ensure_ascii=False), status, now),
        )
    return payload


def list_evaluated_notifications(db_path: Path, limit: int = 100) -> list[dict[str, Any]]:
    """Read only notifications that carry an EVAL evaluation binding."""

    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT payload_json FROM notification_events ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit * 3, 500)),),
        ).fetchall()
    items = []
    for row in rows:
        value = json.loads(row["payload_json"])
        if value.get("evaluation_id"):
            items.append(value)
        if len(items) >= limit:
            break
    return items


def acknowledge_notification(db_path: Path, notification_id: str) -> bool:
    migrate(db_path)
    with connect(db_path) as conn:
        cursor = conn.execute("UPDATE notification_events SET status='acknowledged' WHERE notification_id=?", (notification_id,))
        return cursor.rowcount > 0
