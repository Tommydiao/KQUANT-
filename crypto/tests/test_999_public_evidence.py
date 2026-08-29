from datetime import UTC, datetime
from pathlib import Path

from scripts.collect_999_public_evidence import _asset_id, _quote_symbol, _save_result
from kquant_crypto.external_evidence import ExternalEvidenceSnapshot


class _Result:
    def __init__(self, snapshot):
        self.status = "partial"
        self.snapshot = snapshot


def _snapshot():
    return ExternalEvidenceSnapshot.create(
        asset_id="asset:btc",
        symbol="BTC",
        category="exchange_derivatives",
        source="binance_public_derivatives",
        source_status="partial",
        available_at=datetime(2026, 8, 24, tzinfo=UTC).isoformat(),
        values={"funding_rate": 0.0001},
    )


def test_batch_collector_normalizes_asset_ids_and_saves_partial_evidence(tmp_path: Path):
    assert _asset_id(" BTCUSDT ") == "asset:btc"
    assert _quote_symbol("BTCUSDT") == "BTCUSDT"
    assert _quote_symbol("ETH") == "ETHUSDT"
    result = _save_result(
        db_path=tmp_path / "test.sqlite3",
        provider="binance_public_derivatives",
        category="exchange_derivatives",
        symbol="BTC",
        collect=lambda: _Result(_snapshot()),
    )
    assert result["status"] == "partial"
    assert result["trust_status"] == "data_caution"
    assert result["field_count"] == 1
    assert result["evidence_id"]


def test_batch_collector_isolates_provider_failure(tmp_path: Path):
    result = _save_result(
        db_path=tmp_path / "test.sqlite3",
        provider="defillama_public",
        category="onchain",
        symbol="PUMP",
        collect=lambda: (_ for _ in ()).throw(TimeoutError("offline")),
    )
    assert result["status"] == "collector_error"
    assert result["trust_status"] == "data_caution"
    assert result["field_count"] == 0
    assert result["missing_fields"] == ["provider_response"]
