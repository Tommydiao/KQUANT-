from __future__ import annotations

from kquant_crypto.evidence_collectors import evidence_source_capabilities, fetch_configured_evidence, normalize_provider_evidence


def test_capabilities_never_expose_provider_values(monkeypatch):
    monkeypatch.setenv("COINGLASS_API_KEY", "secret-value")
    payload = evidence_source_capabilities()
    item = next(value for value in payload["items"] if value["source"] == "coinglass_optional")
    assert item["configured"] is True
    assert "secret-value" not in str(payload)
    assert item["secrets_exposed"] is False
    assert next(value for value in payload["items"] if value["source"] == "defillama_public")["public_only"] is True
    assert next(value for value in payload["items"] if value["source"] == "binance_public_market_structure")["public_only"] is True


def test_normalized_evidence_preserves_point_in_time_contract():
    snapshot = normalize_provider_evidence(
        {"flow_usd": 100.0, "unknown_field": 20},
        source="official_etf_feed",
        category="etf_flow",
        asset_id="asset:BTC",
        symbol="BTC",
        source_status="live",
        source_time="2026-08-23T11:50:00+00:00",
        published_at="2026-08-23T11:55:00+00:00",
        available_at="2026-08-23T12:00:00+00:00",
    )
    assert snapshot.values == {"flow_usd": 100.0}
    assert snapshot.content_hash


def test_configured_feed_clamps_provider_clock_ahead(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "values": {"flow_usd": 100.0},
                "source_time": "2030-01-01T00:00:00+00:00",
            }

    monkeypatch.setattr("kquant_crypto.evidence_collectors.httpx.get", lambda *args, **kwargs: Response())
    result = fetch_configured_evidence(
        url="https://example.invalid/evidence",
        source="official_etf_feed",
        category="etf_flow",
        asset_id="asset:BTC",
        symbol="BTC",
    )
    assert result["status"] == "available"
    snapshot = result["snapshot"]
    assert snapshot["source_time"] <= snapshot["available_at"]
