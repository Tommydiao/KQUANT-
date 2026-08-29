from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db.migrations import connect, migrate
from .evaluation_models import EvaluationDecision, TradePlanDraft, stable_hash


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def save_trade_plan(db_path: Path, draft: TradePlanDraft) -> None:
    migrate(db_path)
    payload = draft.to_mapping()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO crypto_trade_plan_drafts(
              plan_id, asset_id, symbol, asset_type, strategy_version,
              proposed_stage, factor_snapshot_hash, source_snapshot_ids_json,
              snapshot_bindings_json,
              identity_status, data_quality_status, security_status,
              liquidity_status, market_regime, model_status, entry_zone_json,
              stop_zone_json, target_zone_json, risk_reward, valid_from,
              valid_until, invalid_conditions_json, factor_ids_json,
              requested_execution_class, material_state_hash, payload_json,
              created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(plan_id) DO UPDATE SET
              payload_json=excluded.payload_json,
              snapshot_bindings_json=excluded.snapshot_bindings_json,
              valid_until=excluded.valid_until,
              material_state_hash=excluded.material_state_hash
            """,
            (
                draft.plan_id,
                draft.asset_id,
                draft.symbol,
                draft.asset_type,
                draft.strategy_version,
                draft.proposed_stage,
                draft.factor_snapshot_hash,
                _dump(payload["source_snapshot_ids"]),
                _dump(payload["snapshot_bindings"]),
                draft.identity_status,
                draft.data_quality_status,
                draft.security_status,
                draft.liquidity_status,
                draft.market_regime,
                draft.model_status,
                _dump(payload["entry_zone"]),
                _dump(payload["stop_zone"]),
                _dump(payload["target_zone"]),
                draft.risk_reward,
                draft.valid_from,
                draft.valid_until,
                _dump(payload["invalid_conditions"]),
                _dump(payload["factor_ids"]),
                draft.requested_execution_class,
                draft.material_state_hash,
                _dump(payload),
                draft.created_at,
            ),
        )


def _row_mapping(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    value = json.loads(row["payload_json"])
    return value


def get_trade_plan(db_path: Path, plan_id: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM crypto_trade_plan_drafts WHERE plan_id=?", (plan_id,)).fetchone()
        return _row_mapping(row)


def list_trade_plans(db_path: Path, limit: int = 50) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT payload_json FROM crypto_trade_plan_drafts ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


def save_evaluation(db_path: Path, result: EvaluationDecision) -> None:
    migrate(db_path)
    payload = result.to_mapping()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO crypto_evaluation_runs(
              evaluation_id, plan_id, evaluated_at, decision,
              evaluation_status, execution_class, allowed_alert,
              allowed_paper, allowed_shadow, evidence_grade, strategy_stage,
              factor_snapshot_hash, material_state_hash,
              evaluation_policy_version, expires_at, source_snapshot_ids_json,
              snapshot_bindings_json,
              result_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                result.evaluation_id,
                result.plan_id,
                result.evaluated_at,
                result.decision,
                result.evaluation_status,
                result.execution_class,
                int(result.allowed_alert),
                int(result.allowed_paper),
                int(result.allowed_shadow),
                result.evidence_grade,
                result.strategy_stage,
                result.factor_snapshot_hash,
                result.material_state_hash,
                result.evaluation_policy_version,
                result.expires_at,
                _dump(result.source_snapshot_ids),
                _dump(result.snapshot_bindings),
                _dump(payload),
            ),
        )
        for blocker in result.blockers:
            conn.execute(
                """
                INSERT INTO crypto_evaluation_blockers(
                  evaluation_id, precedence, blocker_group, code, severity,
                  message, details_json
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    result.evaluation_id,
                    {"security": 10, "data": 20, "liquidity": 30, "market_regime": 40,
                     "model_evidence": 50, "trade_plan": 60, "duplicate_or_expiry": 70}.get(
                        blocker["blocker_group"], 999
                    ),
                    blocker["blocker_group"],
                    blocker["code"],
                    blocker["severity"],
                    blocker["message"],
                    _dump(blocker.get("details") or {}),
                ),
            )
        evidence_rows: list[tuple[str, str, str, dict[str, Any], str | None]] = []
        for group, entries in (
            ("supporting_factor", result.supporting_factors),
            ("opposing_factor", result.opposing_factors),
            ("warning", result.warnings),
        ):
            for index, entry in enumerate(entries):
                value = dict(entry) if isinstance(entry, dict) else {"value": entry}
                evidence_rows.append((group, str(value.get("factor_id") or value.get("code") or index), "observed", value, None))
        for snapshot_id in result.source_snapshot_ids:
            evidence_rows.append(("source_snapshot", snapshot_id, "bound", {"snapshot_id": snapshot_id}, snapshot_id))
        for binding_type, snapshot_id in result.snapshot_bindings.items():
            evidence_rows.append(("snapshot_binding", binding_type, "bound", {"binding_type": binding_type, "snapshot_id": snapshot_id}, snapshot_id))
        for group, key, status, value, source_snapshot_id in evidence_rows:
            conn.execute(
                """
                INSERT INTO crypto_evaluation_evidence(
                  evaluation_id, evidence_group, evidence_key, status,
                  value_json, source_snapshot_id, recorded_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (result.evaluation_id, group, key, status, _dump(value), source_snapshot_id, result.evaluated_at),
            )
        conn.execute(
            """
            INSERT INTO crypto_evaluation_decisions(
              evaluation_id, decision, allowed_alert, allowed_paper,
              allowed_shadow, decided_at, decision_hash
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                result.evaluation_id,
                result.decision,
                int(result.allowed_alert),
                int(result.allowed_paper),
                int(result.allowed_shadow),
                result.evaluated_at,
                stable_hash(payload),
            ),
        )


def _evaluation_mapping(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return json.loads(row["result_json"])


def get_evaluation(db_path: Path, evaluation_id: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT result_json FROM crypto_evaluation_runs WHERE evaluation_id=?",
            (evaluation_id,),
        ).fetchone()
        return _evaluation_mapping(row)


def latest_evaluations(db_path: Path, limit: int = 50) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT result_json FROM crypto_evaluation_runs ORDER BY evaluated_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [json.loads(row["result_json"]) for row in rows]


def latest_evaluation_for_plan(db_path: Path, plan_id: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT result_json FROM crypto_evaluation_runs WHERE plan_id=? ORDER BY evaluated_at DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return _evaluation_mapping(row)
