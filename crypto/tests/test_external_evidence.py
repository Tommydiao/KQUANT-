from __future__ import annotations

from kquant_crypto.external_evidence import ExternalEvidenceSnapshot, evidence_bundle, evidence_coverage, save_evidence_snapshot


def test_external_evidence_keeps_source_times_and_marks_missing_as_na(settings):
    snapshot = ExternalEvidenceSnapshot.create(
        asset_id="asset:BTC",
        symbol="BTC",
        category="etf_flow",
        source="official_etf_feed",
        source_status="live",
        available_at="2026-08-23T12:00:00+00:00",
        published_at="2026-08-23T11:55:00+00:00",
        values={"flow_usd": 10_000_000, "aum_usd": 1_000_000_000},
    )
    saved = save_evidence_snapshot(settings.db_path, snapshot)
    assert saved["source"] == "official_etf_feed"
    assert saved["source_version"] == "official_etf_feed"
    assert saved["collected_at"].endswith("+00:00")
    assert saved["published_at"].endswith("+00:00")
    assert "flow_7d_usd" in saved["missing_fields"]
    bundle = evidence_bundle(settings.db_path, "asset:BTC")
    assert bundle["items"]["etf_flow"]["values"]["flow_usd"] == 10_000_000
    assert bundle["not_available"] == "N/A"
    assert bundle["unknown_values_are_blocked"] is True


def test_external_evidence_rejects_invalid_timestamp():
    try:
        ExternalEvidenceSnapshot.create(
            asset_id="asset:ETH",
            symbol="ETH",
            category="onchain",
            source="public_chain_index",
            source_status="live",
            available_at="not-a-time",
            values={},
        )
    except ValueError as exc:
        assert "available_at" in str(exc)
    else:
        raise AssertionError("invalid evidence timestamp must be rejected")


def test_external_evidence_coverage_separates_observed_from_verified(settings):
    snapshot = ExternalEvidenceSnapshot.create(
        asset_id="asset:BTC",
        symbol="BTC",
        category="exchange_derivatives",
        source="binance_public_derivatives",
        source_status="complete",
        available_at="2026-08-23T12:00:00+00:00",
        values={"funding_rate": 0.001},
    )
    save_evidence_snapshot(settings.db_path, snapshot)
    coverage = evidence_coverage(settings.db_path, ("asset:BTC", "asset:ETH"))
    item = coverage["categories"]["exchange_derivatives"]
    assert item["observed_assets"] == ["asset:BTC"]
    assert item["verified_assets"] == []
    assert item["status"] == "partial"


def test_external_evidence_coverage_uses_category_asset_scope(settings):
    coverage = evidence_coverage(settings.db_path, ("asset:BTC", "asset:ETH", "asset:ETHU", "asset:AAVE"))
    assert coverage["categories"]["etf_flow"]["expected_assets"] == ["asset:BTC", "asset:ETH"]
    assert coverage["categories"]["protocol_metric"]["expected_assets"] == ["asset:AAVE"]
    assert coverage["categories"]["onchain"]["expected_assets"] == ["asset:BTC", "asset:ETH", "asset:AAVE"]


def test_default_evidence_scope_includes_core_sol_without_changing_etf_scope(settings):
    coverage = evidence_coverage(settings.db_path)
    assert "asset:sol" in coverage["categories"]["exchange_derivatives"]["expected_assets"]
    assert coverage["categories"]["etf_flow"]["expected_assets"] == ["asset:btc", "asset:eth"]
