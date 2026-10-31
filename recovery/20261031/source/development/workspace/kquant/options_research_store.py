from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .options_research_features import content_hash


RESEARCH_SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_meta (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_protocol_versions (
  protocol_id TEXT NOT NULL,
  version TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  PRIMARY KEY(protocol_id, version)
);
CREATE TABLE IF NOT EXISTS research_universe_manifests (
  manifest_id TEXT PRIMARY KEY,
  as_of TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_input_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  input_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  as_of_market_time TEXT,
  max_input_available_at TEXT,
  lineage_hash TEXT NOT NULL,
  quality_status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_feature_definitions (
  factor_id TEXT NOT NULL,
  version TEXT NOT NULL,
  definition_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(factor_id, version)
);
CREATE TABLE IF NOT EXISTS research_feature_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  as_of_market_time TEXT,
  max_input_available_at TEXT,
  lineage_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_hypotheses (
  hypothesis_id TEXT NOT NULL,
  version TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  lifecycle_state TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  PRIMARY KEY(hypothesis_id, version)
);
CREATE TABLE IF NOT EXISTS research_experiment_runs (
  run_id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  protocol_version TEXT NOT NULL,
  status TEXT NOT NULL,
  dataset_hash TEXT,
  split_hash TEXT,
  result_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_cohorts (
  cohort_id TEXT PRIMARY KEY,
  policy_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_observed_outcomes (
  outcome_id TEXT PRIMARY KEY,
  cohort_id TEXT NOT NULL,
  contract_id TEXT NOT NULL,
  target_check_at TEXT NOT NULL,
  outcome_status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_scenario_runs (
  scenario_run_id TEXT PRIMARY KEY,
  contract_id TEXT NOT NULL,
  status TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_review_cards (
  card_id TEXT NOT NULL,
  version TEXT NOT NULL,
  card_type TEXT NOT NULL,
  status TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(card_id, version)
);
CREATE TABLE IF NOT EXISTS research_task_state (
  task_id TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  evidence_hash TEXT,
  updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


@contextmanager
def research_connection(db_path: Path, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    db_path = db_path.resolve()
    if readonly:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def initialize_research_store(db_path: Path) -> dict[str, Any]:
    with research_connection(db_path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT OR REPLACE INTO research_meta(key,value_json,updated_at) VALUES ('schema_version',?,?)",
            (_json(RESEARCH_SCHEMA_VERSION), _now()),
        )
        connection.commit()
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    return {"path": str(db_path.resolve()), "schema_version": RESEARCH_SCHEMA_VERSION, "integrity_check": result}


def register_protocol(db_path: Path, protocol: dict[str, Any]) -> dict[str, Any]:
    config_hash = content_hash(protocol)
    now = _now()
    with research_connection(db_path) as connection:
        connection.execute(
            """INSERT OR REPLACE INTO research_protocol_versions
               (protocol_id,version,config_hash,status,payload_json,registered_at) VALUES (?,?,?,?,?,?)""",
            (protocol["protocol_id"], protocol["version"], config_hash, "REGISTERED_RESEARCH_ONLY", _json(protocol), now),
        )
        connection.commit()
    return {"protocol_id": protocol["protocol_id"], "version": protocol["version"], "config_hash": config_hash, "status": "REGISTERED_RESEARCH_ONLY"}


def put_universe_manifest(db_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    digest = content_hash(payload)
    manifest_id = str(payload.get("manifest_id") or f"universe-{digest[:24]}")
    with research_connection(db_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO research_universe_manifests VALUES (?,?,?,?,?)",
            (manifest_id, str(payload.get("as_of") or _now()), digest, _json(payload), _now()),
        )
        connection.commit()
    return {"manifest_id": manifest_id, "content_hash": digest}


def put_feature_definitions(db_path: Path, definitions: list[dict[str, Any]]) -> None:
    with research_connection(db_path) as connection:
        for definition in definitions:
            connection.execute(
                "INSERT OR REPLACE INTO research_feature_definitions VALUES (?,?,?,?,?)",
                (definition["factor_id"], definition["version"], definition["definition_hash"], _json(definition), _now()),
            )
        connection.commit()


def put_feature_snapshot(db_path: Path, payload: dict[str, Any]) -> None:
    with research_connection(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO research_feature_snapshots
               (snapshot_id,entity_type,entity_id,as_of_market_time,max_input_available_at,lineage_hash,status,payload_json,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                payload["snapshot_id"], payload["entity_type"], payload["entity_id"], payload.get("as_of_market_time"),
                payload.get("max_input_available_at"), payload["lineage_hash"], payload["status"], _json(payload), _now(),
            ),
        )
        connection.commit()


def put_hypothesis(db_path: Path, payload: dict[str, Any]) -> None:
    digest = content_hash(payload)
    with research_connection(db_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO research_hypotheses VALUES (?,?,?,?,?,?,?)",
            (payload["hypothesis_id"], payload["version"], payload["profile_id"], payload["lifecycle_state"], digest, _json(payload), _now()),
        )
        connection.commit()


def put_experiment(db_path: Path, payload: dict[str, Any]) -> None:
    digest = content_hash(payload)
    with research_connection(db_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO research_experiment_runs VALUES (?,?,?,?,?,?,?,?,?)",
            (
                payload["run_id"], payload["experiment_id"], payload["protocol_version"], payload["status"],
                payload.get("dataset_hash"), payload.get("split_hash"), digest, _json(payload), _now(),
            ),
        )
        connection.commit()


def put_cohort(db_path: Path, payload: dict[str, Any]) -> None:
    with research_connection(db_path) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO research_cohorts VALUES (?,?,?,?,?)",
            (payload["cohort_id"], payload["policy_hash"], payload["status"], _json(payload), _now()),
        )
        for item in payload.get("checkpoints", []):
            connection.execute(
                """INSERT OR IGNORE INTO research_observed_outcomes
                   (outcome_id,cohort_id,contract_id,target_check_at,outcome_status,payload_json,updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (item["outcome_id"], payload["cohort_id"], item["contract_id"], item["target_check_at"], item["outcome_status"], _json(item), _now()),
            )
        connection.commit()


def put_scenario(db_path: Path, payload: dict[str, Any]) -> None:
    with research_connection(db_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO research_scenario_runs VALUES (?,?,?,?,?,?)",
            (payload["scenario_run_id"], payload["contract_id"], payload["status"], payload["content_hash"], _json(payload), _now()),
        )
        connection.commit()


def put_review_card(db_path: Path, payload: dict[str, Any]) -> None:
    digest = content_hash(payload)
    with research_connection(db_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO research_review_cards VALUES (?,?,?,?,?,?,?)",
            (payload["card_id"], payload["version"], payload["card_type"], payload["status"], digest, _json(payload), _now()),
        )
        connection.commit()


def update_task(db_path: Path, task_id: str, state: str, detail: dict[str, Any]) -> None:
    evidence_hash = content_hash(detail) if detail else None
    with research_connection(db_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO research_task_state VALUES (?,?,?,?,?)",
            (task_id, state, _json(detail), evidence_hash, _now()),
        )
        connection.commit()


def list_payloads(db_path: Path, table: str, *, order_by: str | None = None) -> list[dict[str, Any]]:
    order_columns = {
        "research_feature_definitions": "created_at",
        "research_feature_snapshots": "created_at",
        "research_hypotheses": "registered_at",
        "research_experiment_runs": "created_at",
        "research_cohorts": "created_at",
        "research_observed_outcomes": "updated_at",
        "research_scenario_runs": "created_at",
        "research_review_cards": "created_at",
    }
    if table not in order_columns:
        raise ValueError("Unsupported research table")
    selected_order = order_by or order_columns[table]
    if selected_order not in {order_columns[table], "rowid"}:
        raise ValueError("Unsupported research ordering")
    with research_connection(db_path, readonly=True) as connection:
        rows = connection.execute(f"SELECT payload_json FROM {table} ORDER BY {selected_order}").fetchall()
    return [json.loads(row[0]) for row in rows]


def research_status(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"status": "NOT_INITIALIZED", "database": str(db_path.resolve()), "tasks": [], "counts": {}}
    with research_connection(db_path, readonly=True) as connection:
        tables = [
            "research_feature_definitions", "research_feature_snapshots", "research_hypotheses", "research_experiment_runs",
            "research_cohorts", "research_observed_outcomes", "research_scenario_runs", "research_review_cards",
        ]
        counts = {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}
        tasks = [
            {"task_id": row["task_id"], "state": row["state"], "detail": json.loads(row["detail_json"]), "updated_at": row["updated_at"]}
            for row in connection.execute("SELECT * FROM research_task_state ORDER BY task_id").fetchall()
        ]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    return {"status": "AVAILABLE", "database": str(db_path.resolve()), "schema_version": RESEARCH_SCHEMA_VERSION, "integrity_check": integrity, "counts": counts, "tasks": tasks}


__all__ = [
    "initialize_research_store", "list_payloads", "put_cohort", "put_experiment", "put_feature_definitions",
    "put_feature_snapshot", "put_hypothesis", "put_review_card", "put_scenario", "put_universe_manifest",
    "register_protocol", "research_status", "update_task",
]
