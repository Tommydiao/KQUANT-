from __future__ import annotations

from kquant_crypto.collection_gate import evaluate_collection_gate


def test_collection_gate_requires_one_independent_session():
    result = evaluate_collection_gate(
        started_at="2026-08-01T00:00:00+00:00",
        ended_at="2026-08-02T00:00:00+00:00",
        requested_hours=24,
        required_symbols=("BTCUSDT", "ETHUSDT"),
        streams=(
            {"instrument_id": "binance:spot:BTCUSDT", "span_hours": 24.0},
            {"instrument_id": "binance:spot:ETHUSDT", "span_hours": 24.0},
        ),
        providers={"binance": {"sequence_gaps": 0}},
    )
    assert result["status"] == "PASS"
    assert result["evidence_scope"] == "independent_collector_session"


def test_collection_gate_rejects_short_or_gapful_session():
    result = evaluate_collection_gate(
        started_at="2026-08-01T00:00:00+00:00",
        ended_at="2026-08-01T12:00:00+00:00",
        requested_hours=24,
        required_symbols=("BTCUSDT",),
        streams=({"instrument_id": "binance:spot:BTCUSDT", "span_hours": 24.0},),
        providers={"binance": {"sequence_gaps": 1}},
    )
    assert result["status"] == "NO_GO"
    assert {"session_duration", "sequence_integrity"}.issubset(result["failed_checks"])
