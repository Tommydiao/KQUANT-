from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .bayesian_model import BayesianPosterior, PointInTimeFeatureSnapshot
from .db.migrations import connect, migrate
from .evaluation_models import stable_hash
from .monte_carlo import MonteCarloResult


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def save_bayesian_posterior(db_path: Path, snapshot: PointInTimeFeatureSnapshot, posterior: BayesianPosterior) -> dict[str, Any]:
    payload = {"snapshot": snapshot.to_mapping(), "posterior": posterior.to_mapping()}
    migrate(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO crypto_bayesian_snapshots(
              snapshot_id,asset_id,symbol,model_version,signal_time,available_at,
              source_status,evidence_status,content_hash,payload_json,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                snapshot.snapshot_id, snapshot.asset_id, snapshot.symbol,
                posterior.model_version, snapshot.signal_time, snapshot.available_at,
                snapshot.source_status, posterior.evidence_status, posterior.content_hash,
                _dump(payload), datetime.now(UTC).isoformat(),
            ),
        )
    return payload


def get_bayesian_posterior(db_path: Path, snapshot_id: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM crypto_bayesian_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
    return json.loads(row["payload_json"]) if row else None


def latest_bayesian_posterior(db_path: Path, asset_id: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM crypto_bayesian_snapshots WHERE asset_id=? ORDER BY signal_time DESC, created_at DESC LIMIT 1",
            (asset_id,),
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def save_monte_carlo_result(
    db_path: Path,
    *,
    asset_id: str,
    symbol: str,
    as_of_time: str | None,
    result: MonteCarloResult,
) -> dict[str, Any]:
    payload = result.to_mapping()
    run_key = {"asset_id": asset_id, "symbol": symbol, "result_hash": result.result_hash}
    run_id = f"mc_{stable_hash(run_key)[:20]}"
    migrate(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO crypto_monte_carlo_runs(
              run_id,asset_id,symbol,model_version,status,sample_count,as_of_time,
              config_json,result_hash,payload_json,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id, asset_id, symbol, result.model_version, result.status,
                result.sample_count, as_of_time, _dump(result.config), result.result_hash,
                _dump(payload), datetime.now(UTC).isoformat(),
            ),
        )
    return {"run_id": run_id, "asset_id": asset_id, "symbol": symbol, "as_of_time": as_of_time, **payload}


def get_monte_carlo_result(db_path: Path, run_id: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM crypto_monte_carlo_runs WHERE run_id=?", (run_id,)).fetchone()
    return json.loads(row["payload_json"]) if row else None


def latest_monte_carlo_result(db_path: Path, asset_id: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM crypto_monte_carlo_runs WHERE asset_id=? ORDER BY created_at DESC LIMIT 1",
            (asset_id,),
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


__all__ = [
    "save_bayesian_posterior",
    "get_bayesian_posterior",
    "latest_bayesian_posterior",
    "save_monte_carlo_result",
    "get_monte_carlo_result",
    "latest_monte_carlo_result",
]
