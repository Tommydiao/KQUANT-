from __future__ import annotations

from copy import deepcopy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .db.migrations import connect, migrate


ADVISORY_PROMPT_VERSION = "crypto_llm_advisory_v1.0.0"


def validate_advisory(advisory: dict[str, Any], registered_factor_ids: set[str] | frozenset[str]) -> dict[str, Any]:
    """Validate the advisory side channel without granting it authority."""

    referenced = [str(item) for item in advisory.get("factor_ids", []) if item is not None]
    unknown = sorted(set(referenced) - set(registered_factor_ids))
    forbidden_fields = sorted(
        field for field in ("decision", "entry_zone", "stop_zone", "target_zone", "risk_reward", "factor_weights", "allowed_paper", "allowed_shadow")
        if field in advisory
    )
    if unknown or forbidden_fields:
        return {
            "status": "rejected",
            "factor_ids": referenced,
            "rejection_reasons": (["unknown_factor_id"] if unknown else []) + (["forbidden_authority_field"] if forbidden_fields else []),
            "unknown_factor_ids": unknown,
            "forbidden_fields": forbidden_fields,
        }
    return {
        "status": "accepted",
        "factor_ids": referenced,
        "rejection_reasons": [],
        "summary": str(advisory.get("summary") or ""),
        "scenarios": list(advisory.get("scenarios") or []),
    }


def apply_advisory(evaluation: dict[str, Any], advisory: dict[str, Any], registered_factor_ids: set[str] | frozenset[str]) -> dict[str, Any]:
    """Return the unchanged deterministic decision plus an advisory record.

    The deep copy makes the non-authoritative boundary obvious and prevents a
    caller from mutating the stored result through a shared nested object.
    """

    result = deepcopy(evaluation)
    review = validate_advisory(advisory, registered_factor_ids)
    result["llm_advisory"] = review
    return result


def save_advisory_review(
    db_path: Path,
    evaluation: dict[str, Any],
    advisory: dict[str, Any],
    registered_factor_ids: set[str] | frozenset[str],
    *,
    provider: str = "local_advisory",
    model: str = "deterministic_contract",
    requested_at: str | None = None,
) -> dict[str, Any]:
    """Persist a non-authoritative advisory while preserving EVAL output."""

    review = validate_advisory(advisory, registered_factor_ids)
    review_id = f"llm_review_{uuid4().hex}"
    now = datetime.now(UTC).isoformat()
    requested = requested_at or now
    review = {"review_id": review_id, **review}
    migrate(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO crypto_llm_advisory_reviews(
              review_id,evaluation_id,provider,model,prompt_version,status,
              referenced_factor_ids_json,advisory_json,rejection_reasons_json,
              requested_at,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                review_id,
                str(evaluation.get("evaluation_id") or ""),
                str(provider or "local_advisory"),
                str(model or "deterministic_contract"),
                ADVISORY_PROMPT_VERSION,
                review["status"],
                json.dumps(review.get("factor_ids") or [], ensure_ascii=True, sort_keys=True),
                json.dumps(advisory, ensure_ascii=True, sort_keys=True),
                json.dumps(review.get("rejection_reasons") or [], ensure_ascii=True, sort_keys=True),
                requested,
                now,
            ),
        )
    result = deepcopy(evaluation)
    result["llm_advisory"] = review
    return result


def list_advisory_reviews(db_path: Path, evaluation_id: str, limit: int = 20) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM crypto_llm_advisory_reviews WHERE evaluation_id=? ORDER BY created_at DESC LIMIT ?",
            (evaluation_id, max(1, min(limit, 100))),
        ).fetchall()
    values: list[dict[str, Any]] = []
    for row in rows:
        value = dict(row)
        value["referenced_factor_ids"] = json.loads(value.pop("referenced_factor_ids_json"))
        value["advisory"] = json.loads(value.pop("advisory_json"))
        value["rejection_reasons"] = json.loads(value.pop("rejection_reasons_json"))
        values.append(value)
    return values


def build_advisory_request(plan: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_version": ADVISORY_PROMPT_VERSION,
        "plan_id": plan.get("plan_id"),
        "evaluation_id": evaluation.get("evaluation_id"),
        "decision": evaluation.get("decision"),
        "factor_ids": list(plan.get("factor_ids") or []),
        "allowed_actions": ["explain", "question_risks", "scenario_summary"],
    }
