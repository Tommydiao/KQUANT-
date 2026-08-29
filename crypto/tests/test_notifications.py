from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from kquant_crypto.notifications import (
    get_notification_preferences,
    notification_delivery_policy,
    notification_status,
    record_notification,
    save_web_push_subscription,
    set_notification_preferences,
)
from kquant_crypto.alert_agent import emit_evaluated_alert
from kquant_crypto.notifications import NotificationHub


def test_notifications_are_disabled_by_default(settings):
    status = notification_status(settings, settings.db_path)
    assert status["delivery_mode"] == "disabled"
    payload = record_notification(settings.db_path, severity="INFO", title="test", body="body")
    assert payload["notification_id"].startswith("notice_")


def test_alert_agent_rejects_unapproved_eval(settings):
    hub = NotificationHub()
    assert emit_evaluated_alert(
        settings.db_path,
        hub,
        {"evaluation_status": "blocked", "allowed_alert": True},
        title="blocked",
        body="must not deliver",
    ) is None
    assert emit_evaluated_alert(
        settings.db_path,
        hub,
        {"evaluation_status": "passed_with_warnings", "allowed_alert": False},
        title="not authorized",
        body="must not deliver",
    ) is None
    assert emit_evaluated_alert(
        settings.db_path,
        hub,
        {"evaluation_status": "passed_with_warnings", "allowed_alert": True, "decision": "PAPER_REVIEW"},
        title="warning state",
        body="must not deliver",
    ) is None


def test_web_push_subscription_and_preferences_are_local_and_secret_free(settings):
    saved = save_web_push_subscription(settings.db_path, settings.login_email, {"endpoint": "https://push.example/subscription-123", "keys": {"p256dh": "public-key", "auth": "auth-key"}})
    assert saved["status"] == "active"
    assert "public-key" not in saved
    preferences = set_notification_preferences(settings.db_path, settings.login_email, {"enabled": True, "web_push_enabled": True, "quiet_start": "23:00"})
    assert preferences["enabled"] is True
    assert preferences["quiet_start"] == "23:00"
    assert get_notification_preferences(settings.db_path, settings.login_email)["web_push_enabled"] is True


def test_notification_policy_has_quiet_hours_daily_cap_and_risk_exception(settings):
    set_notification_preferences(settings.db_path, settings.login_email, {
        "enabled": True,
        "timezone": "UTC",
        "quiet_start": "10:00",
        "quiet_end": "11:00",
    })
    quiet_now = datetime(2026, 8, 23, 10, 30, tzinfo=UTC)
    assert notification_delivery_policy(settings.db_path, settings.login_email, "ACTION", now=quiet_now)["reason"] == "quiet_hours"
    assert notification_delivery_policy(settings.db_path, settings.login_email, "CRITICAL", now=quiet_now)["allowed"] is True

    set_notification_preferences(settings.db_path, settings.login_email, {"quiet_start": None, "quiet_end": None})
    for index in range(5):
        record_notification(settings.db_path, severity="ACTION", title=f"n{index}", body="body")
    result = notification_delivery_policy(
        settings.db_path,
        settings.login_email,
        "ACTION",
        now=datetime.now(UTC) + timedelta(seconds=1),
    )
    assert result["reason"] == "daily_limit"
    assert notification_delivery_policy(settings.db_path, settings.login_email, "RISK")["allowed"] is True


def test_alert_agent_audits_suppressed_delivery_without_publishing(settings):
    settings = replace(settings, notifications_enabled=True)
    set_notification_preferences(settings.db_path, settings.login_email, {
        "enabled": True,
        "timezone": "UTC",
        "quiet_start": "00:00",
        "quiet_end": "23:59",
    })
    hub = NotificationHub()
    payload = emit_evaluated_alert(
        settings.db_path,
        hub,
        {"evaluation_status": "passed", "decision": "PAPER_REVIEW", "allowed_alert": True, "evaluation_id": "eva-1"},
        title="quiet",
        body="suppressed",
        settings=settings,
    )
    assert payload is not None
    assert payload["delivery"]["web_push"]["status"] == "suppressed"
    assert payload["delivery_suppressed_reason"] == "quiet_hours"
