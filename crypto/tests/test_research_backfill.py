from datetime import UTC, datetime

from kquant_crypto.research_backfill import build_research_backfill_plan, summarize_backfill_plan


def test_backfill_plan_respects_listing_market_and_rolling_scope(settings):
    jobs = build_research_backfill_plan(
        settings.root_dir,
        now=datetime(2026, 9, 4, tzinfo=UTC),
    )
    by_key = {(item.symbol, item.market_type, item.interval): item for item in jobs}

    assert by_key[("ARBUSDT", "spot", "1h")].start_month == "2023-03-01"
    assert by_key[("PUMPUSDT", "spot", "5m")].start_month == "2025-09-01"
    assert ("HYPEUSDT", "spot", "1h") not in by_key
    assert by_key[("HYPEUSDT", "perpetual", "funding")].kind == "funding"
    assert by_key[("BTCUSDT", "spot", "1m")].start_month == "2026-07-01"
    assert by_key[("BTCUSDT", "spot", "1m")].end_month == "2026-08-01"

    report = summarize_backfill_plan(jobs)
    assert report["network_started"] is False
    assert {"ZECUSDT", "PUMPUSDT", "HYPEUSDT"}.issubset(report["symbols"])
