from __future__ import annotations

"""Persistent OCR preview and explicit user-confirmation boundary."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from .db.migrations import connect, migrate


PREVIEW_TTL = timedelta(hours=24)


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def save_roll_journal_preview(db_path: Path, preview: Mapping[str, Any]) -> dict[str, Any]:
    migrate(db_path)
    payload = dict(preview)
    created_at = datetime.now(UTC).isoformat()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO crypto_roll_journal_previews(
              preview_id, content_hash, status, payload_json, created_at, confirmed_at
            ) VALUES (?,?,?,?,?,NULL)
            """,
            (
                str(payload.get("preview_id") or ""),
                str(payload.get("content_hash") or ""),
                "preview_ready",
                _json(payload),
                created_at,
            ),
        )
        row = conn.execute(
            "SELECT * FROM crypto_roll_journal_previews WHERE preview_id=?",
            (str(payload.get("preview_id") or ""),),
        ).fetchone()
    return {
        **payload,
        "created_at": row["created_at"] if row else created_at,
        "confirmation_required": True,
        "write_allowed": False,
        "research_only": True,
    }


def confirm_roll_journal_preview(
    db_path: Path,
    preview_id: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Confirm an unexpired preview and require exact parsed-value agreement."""

    migrate(db_path)
    now = datetime.now(UTC)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM crypto_roll_journal_previews WHERE preview_id=?",
            (str(preview_id or ""),),
        ).fetchone()
        if row is None:
            raise ValueError("journal_preview_not_found")
        if row["status"] != "preview_ready":
            raise ValueError("journal_preview_already_confirmed")
        created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if now - created.astimezone(UTC) > PREVIEW_TTL:
            conn.execute(
                "UPDATE crypto_roll_journal_previews SET status='expired' WHERE preview_id=?",
                (str(preview_id),),
            )
            raise ValueError("journal_preview_expired")
        original = json.loads(row["payload_json"])
        for field in ("symbol", "realized_profit", "rolled_capital", "remaining_risk"):
            submitted = payload.get(field)
            expected = original.get(field)
            if field == "symbol":
                matches = str(submitted or "").upper() == str(expected or "").upper()
            else:
                try:
                    matches = abs(float(submitted) - float(expected)) < 1e-9
                except (TypeError, ValueError):
                    matches = False
            if not matches:
                raise ValueError(f"journal_preview_mismatch:{field}")
        conn.execute(
            "UPDATE crypto_roll_journal_previews SET status='confirmed', confirmed_at=? WHERE preview_id=?",
            (now.isoformat(), str(preview_id)),
        )
        return {
            "preview_id": str(preview_id),
            "status": "confirmed",
            "confirmed_at": now.isoformat(),
            "research_only": True,
        }


__all__ = ["PREVIEW_TTL", "save_roll_journal_preview", "confirm_roll_journal_preview"]
