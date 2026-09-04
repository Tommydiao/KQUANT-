from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .db.migrations import connect, migrate
from .evaluation_models import stable_hash
from .universe_catalog import candidate_instrument


MODEL_EVIDENCE_VERSION = "crypto_model_evidence_v1.0.0"
PROMOTION_STAGES = ("RESEARCH_ONLY", "SHADOW_ELIGIBLE", "TESTNET_CANDIDATE", "TESTNET_ENABLED")
ASSET_REQUIRED_BAYESIAN_FEATURES = {
    "PUMPUSDT": frozenset({"gap_risk", "volume_decay", "abnormal_volatility"}),
    "HYPEUSDT": frozenset({"funding_stress", "oi_change", "basis_signal", "deleveraging_risk"}),
}
MINIMUM_MONTE_CARLO_PATHS = 5_000
PACKET_HASH_FIELDS = (
    "model_evidence_version",
    "asset_id",
    "symbol",
    "market_type",
    "strategy_version",
    "signal_time",
    "available_at",
    "evidence_history_start",
    "limited_history",
    "calibration_status",
    "promotion_status",
    "bayesian_posterior",
    "monte_carlo_result",
    "logistic_result",
    "expected_return_quantiles",
    "source_snapshot_ids",
    "blockers",
)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


@dataclass(frozen=True)
class ModelEvidencePacket:
    packet_id: str
    asset_id: str
    symbol: str
    market_type: str
    strategy_version: str
    signal_time: str
    available_at: str
    evidence_history_start: str | None
    limited_history: bool
    calibration_status: str
    promotion_status: str
    bayesian_posterior: dict[str, Any]
    monte_carlo_result: dict[str, Any]
    logistic_result: dict[str, Any]
    expected_return_quantiles: dict[str, Any]
    source_snapshot_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    content_hash: str
    created_at: str
    model_evidence_version: str = MODEL_EVIDENCE_VERSION

    def to_mapping(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "market_type": self.market_type,
            "strategy_version": self.strategy_version,
            "signal_time": self.signal_time,
            "available_at": self.available_at,
            "evidence_history_start": self.evidence_history_start,
            "limited_history": self.limited_history,
            "calibration_status": self.calibration_status,
            "promotion_status": self.promotion_status,
            "bayesian_posterior": dict(self.bayesian_posterior),
            "monte_carlo_result": dict(self.monte_carlo_result),
            "logistic_result": dict(self.logistic_result),
            "expected_return_quantiles": dict(self.expected_return_quantiles),
            "source_snapshot_ids": list(self.source_snapshot_ids),
            "blockers": list(self.blockers),
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "model_evidence_version": self.model_evidence_version,
        }


def build_model_evidence_packet(
    *,
    asset_id: str,
    symbol: str,
    market_type: str,
    strategy_version: str,
    signal_time: str,
    available_at: str,
    evidence_history_start: str | None,
    bayesian_posterior: Mapping[str, Any] | None,
    monte_carlo_result: Mapping[str, Any] | None,
    logistic_result: Mapping[str, Any] | None = None,
    expected_return_quantiles: Mapping[str, Any] | None = None,
    calibration_status: str = "not_trained",
    source_snapshot_ids: Sequence[str] = (),
    minimum_history_observations: int = 220,
) -> ModelEvidencePacket:
    """Bind mathematical evidence to one point-in-time instrument decision.

    This function does not train or infer missing models. Missing, mismatched or
    uncalibrated evidence stays explicit and keeps the asset research-only.
    """

    normalized_symbol = str(symbol).strip().upper()
    normalized_market = str(market_type).strip().lower()
    if normalized_market not in {"spot", "perpetual"}:
        raise ValueError("market_type_must_be_spot_or_perpetual")
    signal = _parse_time(signal_time)
    available = _parse_time(available_at)
    history_start = _parse_time(evidence_history_start)
    if signal is None or available is None:
        raise ValueError("signal_time_and_available_at_required")
    if available > signal:
        raise ValueError("available_at_must_not_be_after_signal_time")
    if history_start and history_start > signal:
        raise ValueError("evidence_history_starts_after_signal")

    instrument = candidate_instrument(normalized_symbol, normalized_market)
    same_symbol_other_market = candidate_instrument(normalized_symbol)
    if same_symbol_other_market is not None and instrument is None:
        raise ValueError("candidate_market_type_mismatch")
    if instrument and instrument.listed_since:
        listed = _parse_time(instrument.listed_since)
        if listed and signal < listed:
            raise ValueError("signal_precedes_instrument_listing")
        if history_start and listed and history_start < listed:
            raise ValueError("evidence_precedes_instrument_listing")

    bayesian = _mapping(bayesian_posterior)
    monte_carlo = _mapping(monte_carlo_result)
    logistic = _mapping(logistic_result)
    quantiles = _mapping(expected_return_quantiles)
    blockers: list[str] = []
    if bayesian.get("evidence_status") != "complete":
        blockers.append("bayesian_evidence_incomplete")
    if monte_carlo.get("status") != "available":
        blockers.append("monte_carlo_unavailable")
    monte_carlo_config = dict(monte_carlo.get("config") or {})
    if int(monte_carlo_config.get("paths") or 0) < MINIMUM_MONTE_CARLO_PATHS:
        blockers.append("monte_carlo_paths_insufficient")
    if normalized_market == "perpetual":
        if monte_carlo_config.get("instrument_type") != "perpetual":
            blockers.append("perpetual_model_contract_mismatch")
    required_features = ASSET_REQUIRED_BAYESIAN_FEATURES.get(normalized_symbol, frozenset())
    feature_order = {str(item) for item in bayesian.get("feature_order", ())}
    missing_asset_features = sorted(required_features - feature_order)
    if missing_asset_features:
        blockers.append("asset_model_features_missing")
    if not logistic or logistic.get("status") not in {"available", "validated", "passed"}:
        blockers.append("logistic_evidence_unavailable")
    if not quantiles or quantiles.get("status") not in {"available", "validated", "passed"}:
        blockers.append("quantile_evidence_unavailable")
    normalized_calibration = str(calibration_status or "not_trained").strip().lower()
    if normalized_calibration != "passed":
        blockers.append("calibration_gate_closed")
    if not source_snapshot_ids:
        blockers.append("source_snapshot_binding_missing")

    sample_count = int(monte_carlo.get("sample_count") or 0)
    limited_history = history_start is None or sample_count < max(1, int(minimum_history_observations))
    if limited_history:
        blockers.append("limited_history")
    blockers = list(dict.fromkeys(blockers))
    promotion_status = "SHADOW_ELIGIBLE" if not blockers else "RESEARCH_ONLY"
    created_at = datetime.now(UTC).isoformat()
    payload = {
        "model_evidence_version": MODEL_EVIDENCE_VERSION,
        "asset_id": asset_id,
        "symbol": normalized_symbol,
        "market_type": normalized_market,
        "strategy_version": strategy_version,
        "signal_time": signal.isoformat(),
        "available_at": available.isoformat(),
        "evidence_history_start": history_start.isoformat() if history_start else None,
        "limited_history": limited_history,
        "calibration_status": normalized_calibration,
        "promotion_status": promotion_status,
        "bayesian_posterior": bayesian,
        "monte_carlo_result": monte_carlo,
        "logistic_result": logistic,
        "expected_return_quantiles": quantiles,
        "source_snapshot_ids": list(source_snapshot_ids),
        "blockers": blockers,
    }
    content_hash = stable_hash(payload)
    return ModelEvidencePacket(
        packet_id=f"model_evidence_{content_hash[:24]}",
        asset_id=str(asset_id),
        symbol=normalized_symbol,
        market_type=normalized_market,
        strategy_version=str(strategy_version),
        signal_time=signal.isoformat(),
        available_at=available.isoformat(),
        evidence_history_start=history_start.isoformat() if history_start else None,
        limited_history=limited_history,
        calibration_status=normalized_calibration,
        promotion_status=promotion_status,
        bayesian_posterior=bayesian,
        monte_carlo_result=monte_carlo,
        logistic_result=logistic,
        expected_return_quantiles=quantiles,
        source_snapshot_ids=tuple(str(item) for item in source_snapshot_ids),
        blockers=tuple(blockers),
        content_hash=content_hash,
        created_at=created_at,
    )


def save_model_evidence_packet(db_path: Path, packet: ModelEvidencePacket) -> dict[str, Any]:
    value = packet.to_mapping()
    migrate(db_path)
    dump = lambda item: json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO crypto_model_evidence_packets(
              packet_id,asset_id,symbol,market_type,strategy_version,signal_time,available_at,
              evidence_history_start,limited_history,calibration_status,promotion_status,
              bayesian_posterior_json,monte_carlo_result_json,logistic_result_json,
              expected_return_quantiles_json,source_snapshot_ids_json,blockers_json,
              content_hash,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                packet.packet_id, packet.asset_id, packet.symbol, packet.market_type,
                packet.strategy_version, packet.signal_time, packet.available_at,
                packet.evidence_history_start, int(packet.limited_history), packet.calibration_status,
                packet.promotion_status, dump(packet.bayesian_posterior), dump(packet.monte_carlo_result),
                dump(packet.logistic_result), dump(packet.expected_return_quantiles),
                dump(packet.source_snapshot_ids), dump(packet.blockers), packet.content_hash, packet.created_at,
            ),
        )
    return value


def _decode_packet_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    value = dict(row)
    for key in (
        "bayesian_posterior", "monte_carlo_result", "logistic_result",
        "expected_return_quantiles", "source_snapshot_ids", "blockers",
    ):
        value[key] = json.loads(value.pop(f"{key}_json"))
    value["limited_history"] = bool(value["limited_history"])
    value["model_evidence_version"] = MODEL_EVIDENCE_VERSION
    return value


def get_model_evidence_packet(db_path: Path, packet_id: str) -> dict[str, Any] | None:
    """Load one immutable packet by its content-derived identifier."""

    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM crypto_model_evidence_packets WHERE packet_id=?",
            (str(packet_id),),
        ).fetchone()
    return _decode_packet_row(row)


def verify_model_evidence_packet(packet: Mapping[str, Any] | None) -> tuple[bool, tuple[str, ...]]:
    """Verify the content hash and identifier of a persisted evidence packet.

    ``created_at`` is deliberately excluded from the hash so rebuilding the
    same point-in-time evidence remains deterministic.  A caller cannot make a
    candidate packet eligible by merely supplying a plausible hash string.
    """

    if not isinstance(packet, Mapping):
        return False, ("packet_missing",)
    missing = tuple(field for field in PACKET_HASH_FIELDS if field not in packet)
    if missing:
        return False, ("packet_fields_missing",)
    payload = {field: packet[field] for field in PACKET_HASH_FIELDS}
    expected_hash = stable_hash(payload)
    issues: list[str] = []
    if str(packet.get("model_evidence_version") or "") != MODEL_EVIDENCE_VERSION:
        issues.append("model_evidence_version_mismatch")
    if str(packet.get("content_hash") or "") != expected_hash:
        issues.append("content_hash_mismatch")
    expected_packet_id = f"model_evidence_{expected_hash[:24]}"
    if str(packet.get("packet_id") or "") != expected_packet_id:
        issues.append("packet_id_mismatch")
    return not issues, tuple(issues)


def latest_model_evidence_packet(db_path: Path, asset_id: str, market_type: str | None = None) -> dict[str, Any] | None:
    migrate(db_path)
    query = "SELECT * FROM crypto_model_evidence_packets WHERE asset_id=?"
    params: list[Any] = [asset_id]
    if market_type:
        query += " AND market_type=?"
        params.append(str(market_type).lower())
    query += " ORDER BY signal_time DESC, created_at DESC LIMIT 1"
    with connect(db_path) as conn:
        row = conn.execute(query, params).fetchone()
    return _decode_packet_row(row)


__all__ = [
    "MODEL_EVIDENCE_VERSION",
    "ASSET_REQUIRED_BAYESIAN_FEATURES",
    "MINIMUM_MONTE_CARLO_PATHS",
    "PACKET_HASH_FIELDS",
    "ModelEvidencePacket",
    "build_model_evidence_packet",
    "save_model_evidence_packet",
    "get_model_evidence_packet",
    "verify_model_evidence_packet",
    "latest_model_evidence_packet",
]
