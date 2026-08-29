from __future__ import annotations

from kquant_crypto.roll_engine import RollInput
from kquant_crypto.roll_journal import preview_roll_journal_text
from kquant_crypto.roll_packet import build_roll_feature_packet


def _input() -> RollInput:
    return RollInput.from_mapping({
        "asset_id": "asset:ETH",
        "symbol": "ETH",
        "asset_type": "crypto_spot",
        "as_of_time": "2026-08-23T12:00:00+00:00",
        "data_cutoff_time": "2026-08-23T11:59:00+00:00",
        "source_status": "live",
        "coverage": 1.0,
        "market_state": "BULL",
        "state_probability": 0.82,
        "target_before_stop_probability": 0.72,
        "positive_return_probability": 0.70,
        "drawdown_probability": 0.18,
        "feature_snapshot_id": "packet_features_v1",
        "model_version": "crypto_bayesian_v1.0.0",
        "source_snapshot_ids": ["market_1"],
    })


def test_roll_feature_packet_is_deterministic_and_missing_evidence_is_explicit():
    first = build_roll_feature_packet(_input(), model={"status": "available_non_authoritative", "probability": 0.61}, journal={"status": "reviewed", "realized_profit": 10})
    second = build_roll_feature_packet(_input(), model={"status": "available_non_authoritative", "probability": 0.61}, journal={"status": "reviewed", "realized_profit": 10})
    assert first.packet_id == second.packet_id
    assert first.payload["external_evidence"]["not_available"] == "N/A"
    assert first.payload["research_metadata"]["strategy_version"] == "crypto_roll_v1.0.0"
    assert first.payload["model"]["probability"] == 0.61
    assert first.payload["journal"]["realized_profit"] == 10
    assert first.to_mapping()["eval_authority"] == "EVAL only"


def test_roll_journal_ocr_is_preview_only_and_requires_all_fields():
    preview = preview_roll_journal_text(
        "symbol: ETH\nrealized profit: 120\nroll capital: 80\nremaining risk: 40\nnote: manual review"
    )
    assert preview.status == "preview_ready"
    assert preview.write_allowed is False
    assert preview.symbol == "ETH"
    incomplete = preview_roll_journal_text("symbol: ETH\nrealized profit: 120")
    assert incomplete.status == "preview_incomplete"
    assert "rolled_capital" in incomplete.missing_fields
