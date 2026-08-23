from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .db.migrations import connect, migrate
from .evaluation_models import stable_hash


@dataclass(frozen=True)
class ModelArtifact:
    """Metadata-only model artifact record.

    KQUANT stores evidence hashes and metrics here, never executable model
    bytes. A model can only be referenced by an EVAL plan after its metadata
    has been registered and frozen.
    """

    model_id: str
    model_version: str
    model_type: str
    dataset_version: str
    dataset_hash: str
    feature_order_hash: str
    test_partition_hash: str
    artifact_hash: str
    calibration_gate: str = "insufficient"
    status: str = "registered"
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    frozen_at: str | None = None

    @classmethod
    def from_metadata(cls, *, model_id: str, model_version: str, model_type: str, dataset_version: str, dataset_hash: str, feature_order: list[str] | tuple[str, ...], test_partition_hash: str, artifact_payload: dict[str, Any] | None = None, calibration_gate: str = "insufficient", status: str = "registered", metrics: dict[str, Any] | None = None, frozen_at: str | None = None) -> "ModelArtifact":
        payload = artifact_payload or {}
        return cls(
            model_id=model_id,
            model_version=model_version,
            model_type=model_type,
            dataset_version=dataset_version,
            dataset_hash=dataset_hash,
            feature_order_hash=stable_hash(list(feature_order)),
            test_partition_hash=test_partition_hash,
            artifact_hash=stable_hash({
                "model_id": model_id,
                "model_version": model_version,
                "dataset_hash": dataset_hash,
                "feature_order": list(feature_order),
                "test_partition_hash": test_partition_hash,
                "artifact_payload": payload,
            }),
            calibration_gate=calibration_gate,
            status=status,
            metrics=dict(metrics or {}),
            frozen_at=frozen_at,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "model_type": self.model_type,
            "dataset_version": self.dataset_version,
            "dataset_hash": self.dataset_hash,
            "feature_order_hash": self.feature_order_hash,
            "test_partition_hash": self.test_partition_hash,
            "artifact_hash": self.artifact_hash,
            "calibration_gate": self.calibration_gate,
            "status": self.status,
            "metrics": self.metrics,
            "created_at": self.created_at,
            "frozen_at": self.frozen_at,
        }


class ModelArtifactRegistry:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def register(self, artifact: ModelArtifact) -> dict[str, Any]:
        migrate(self.db_path)
        value = artifact.as_dict()
        with connect(self.db_path) as conn:
            existing = conn.execute("SELECT * FROM crypto_model_artifacts WHERE model_id=?", (artifact.model_id,)).fetchone()
            if existing is not None:
                current = dict(existing)
                if current["artifact_hash"] != artifact.artifact_hash:
                    raise ValueError("model_id is immutable and already points to a different artifact hash")
                return self._row(current)
            conn.execute(
                """
                INSERT INTO crypto_model_artifacts(
                  model_id,model_version,model_type,dataset_version,dataset_hash,
                  feature_order_hash,test_partition_hash,artifact_hash,calibration_gate,
                  status,metrics_json,created_at,frozen_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    artifact.model_id, artifact.model_version, artifact.model_type,
                    artifact.dataset_version, artifact.dataset_hash, artifact.feature_order_hash,
                    artifact.test_partition_hash, artifact.artifact_hash, artifact.calibration_gate,
                    artifact.status, json.dumps(artifact.metrics, ensure_ascii=True, sort_keys=True),
                    artifact.created_at, artifact.frozen_at,
                ),
            )
        return value

    def get(self, model_id: str) -> dict[str, Any] | None:
        migrate(self.db_path)
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM crypto_model_artifacts WHERE model_id=?", (model_id,)).fetchone()
        return self._row(dict(row)) if row else None

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        migrate(self.db_path)
        with connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM crypto_model_artifacts ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
        return [self._row(dict(row)) for row in rows]

    def evidence_gate(self, model_id: str | None) -> tuple[bool, list[str], dict[str, Any] | None]:
        if not model_id:
            return False, ["model_artifact_not_bound"], None
        artifact = self.get(model_id)
        if artifact is None:
            return False, ["model_artifact_not_found"], None
        reasons: list[str] = []
        if artifact["status"] not in {"validated", "frozen"}:
            reasons.append("model_artifact_not_frozen")
        if artifact["calibration_gate"] != "passed":
            reasons.append("calibration_gate_closed")
        return not reasons, reasons, artifact

    @staticmethod
    def _row(value: dict[str, Any]) -> dict[str, Any]:
        value["metrics"] = json.loads(value.pop("metrics_json")) if "metrics_json" in value else value.get("metrics", {})
        return value
