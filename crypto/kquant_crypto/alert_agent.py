from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .notifications import NotificationHub, deliver_telegram, deliver_web_push, notification_delivery_policy, record_notification


def emit_evaluated_alert(
    db_path: Path,
    hub: NotificationHub,
    evaluation: dict[str, Any],
    *,
    title: str,
    body: str,
    deep_link: str | None = None,
    settings: Settings | None = None,
    severity: str = "ACTION",
) -> dict[str, Any] | None:
    """Deliver only a decision explicitly authorized by deterministic EVAL."""

    severity = str(severity or "ACTION").upper()
    # Alert delivery is a post-EVAL capability. Warnings are still a failed
    # authorization state until a later, explicit evaluation passes cleanly.
    if str(evaluation.get("evaluation_status") or "").lower() != "passed":
        return None
    if str(evaluation.get("decision") or "").upper() in {"REJECTED", "WATCH_ONLY", "INVALIDATED"}:
        return None
    if not bool(evaluation.get("allowed_alert")):
        return None
    metadata = {
        "evaluation_id": evaluation.get("evaluation_id"),
        "plan_id": evaluation.get("plan_id"),
        "eval_policy_version": evaluation.get("evaluation_policy_version"),
    }
    policy = None
    if settings is not None and settings.notifications_enabled:
        policy = notification_delivery_policy(db_path, settings.login_email, severity)
        if not policy["allowed"]:
            metadata.update({
                "delivery_suppressed": True,
                "delivery_suppressed_reason": policy["reason"],
                "delivery_count": policy["count"],
            })
            payload = record_notification(
                db_path,
                severity=severity,
                title=title,
                body=body,
                deep_link=deep_link,
                metadata=metadata,
                status="suppressed",
            )
            payload["delivery"] = {
                "web_push": {"status": "suppressed", "reason": policy["reason"]},
                "telegram": {"status": "suppressed", "reason": policy["reason"]},
            }
            return payload
    payload = record_notification(
        db_path,
        severity=severity,
        title=title,
        body=body,
        deep_link=deep_link,
        metadata=metadata,
    )
    delivery = {"web_push": {"status": "not_attempted"}, "telegram": {"status": "not_attempted"}}
    if settings is not None:
        delivery = {
            "web_push": deliver_web_push(settings, db_path, payload),
            "telegram": deliver_telegram(settings, db_path, payload),
        }
    payload["delivery"] = delivery
    hub.publish(payload)
    return payload
