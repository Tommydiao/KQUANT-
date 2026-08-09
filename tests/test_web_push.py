from __future__ import annotations

from pathlib import Path

from kquant.web_push import (
    deliver_web_push,
    notification_preferences,
    subscribe,
    unsubscribe,
    update_notification_preferences,
    web_push_status,
)


def test_web_push_subscription_and_preferences_are_local_and_secret_safe(tmp_path: Path) -> None:
    db = tmp_path / "push.sqlite3"
    saved = subscribe(db, {
        "endpoint": "https://push.example.test/subscription/abc",
        "keys": {"p256dh": "public-client-key", "auth": "auth-secret"},
    }, "iPhone")
    assert saved["secret_values_exposed"] is False
    assert web_push_status(db)["active_subscriptions"] == 1
    preferences = update_notification_preferences(db, {
        "web_push_enabled": True,
        "quiet_start": "23:00",
        "quiet_end": "07:30",
        "timezone": "Asia/Shanghai",
        "daily_routine_limit": 5,
    })
    assert preferences["quiet_start"] == "23:00"
    assert notification_preferences(db)["daily_routine_limit"] == 5
    assert unsubscribe(db, "https://push.example.test/subscription/abc")["status"] == "disabled"


def test_web_push_stays_disabled_without_local_vapid(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "push.sqlite3"
    monkeypatch.delenv("KQUANT_WEB_PUSH_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("KQUANT_WEB_PUSH_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("KQUANT_WEB_PUSH_ENABLED", "true")
    result = deliver_web_push(db, alert_id=None, severity="CRITICAL", payload={"title": "test"})
    assert result == {"status": "disabled", "reason": "vapid_not_configured", "sent": 0}
