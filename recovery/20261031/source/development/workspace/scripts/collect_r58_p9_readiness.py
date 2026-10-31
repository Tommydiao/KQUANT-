"""Read-only source gap matrix from captured scope, not an invented live scan."""
import argparse
from collections import Counter
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).absolute().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from kquant.options_opening_trend_reference import load_reviews, source_review
    from kquant.market_clock import session_bounds_utc, is_trading_day
    now = datetime.now(UTC)
    scope = json.loads((args.out / "production-readonly-indexed/watch.json").read_text())
    saved_worker = json.loads((args.out / "one-minute-worker.json").read_text())
    reviews = load_reviews()
    items = []
    for asset in scope["items"]:
        symbol = asset["symbol"]
        proof = (reviews.get("instrument_facts", {}).get(symbol)
                 or reviews.get("ordinary_equities", {}).get(symbol))
        checked = source_review(proof, root=ROOT, now=now)
        actions = reviews.get("instrument_price_actions", {}).get(symbol)
        action_proof = source_review(actions, root=ROOT, now=now)
        items.append({**asset,
            "asset_type": checked.get("asset_type") if checked else None,
            "asset_fact": "VERIFIED_ARCHIVED_SOURCE" if checked and checked.get("asset_type") not in
                (None, "UNKNOWN") else "UNCONFIRMED_OR_MISSING",
            "provider_standard_asset_mapping": "SUPPORTED_BY_CURRENT_ADAPTER" if checked and
                checked.get("asset_type") in {"US_ORDINARY_EQUITY", "US_ADR", "US_ETF"}
                else "NO_VERIFIED_STANDARD_MAPPING_NOT_A_SECURITY_UNSUPPORTED_CLAIM",
            "price_asset_consumer_has_instrument_fact": bool(reviews.get("instrument_facts", {}).get(symbol)),
            "asset_fact_hash": proof.get("source_sha256") if proof else None,
            "price_action_fact": "REVIEWED_SOURCE_PRESENT_NOT_LIVE_BINDING" if action_proof else "MISSING_OR_UNCONFIRMED",
            "price_action_fact_hash": actions.get("source_sha256") if actions else None,
            "current_session_binding": "NOT_VERIFIED_IN_THIS_RUN",
            "current_minute": "NOT_OBSERVED_PRODUCTION_STOPPED",
            "depth_unit_fact": "MISSING" if reviews.get("depth_units") is None else "REQUIRES_LIVE_IDENTITY_CHECK",
            "blocked_capabilities": (["IDENTITY_UNCONFIRMED"] if asset["identity_status"] != "verified" else [])
                + ([] if action_proof else ["PRICE_ACTION_COVERAGE_NOT_PROVEN"])
                + (["OPTION_DEPTH_CONTRACT_UNITS_NOT_PROVEN"] if reviews.get("depth_units") is None else [])})
    day = now.astimezone(ZoneInfo("America/New_York")).date()
    opening, closing = session_bounds_utc(day)
    payload = {"observed_at": now.isoformat(), "session": day.isoformat(),
        "trade_day": is_trading_day(day), "scope_hash": scope["scope_hash"],
        "registered_symbols": len(items), "registered_directions_per_checkpoint": len(items) * 2,
        "source": "CAPTURED_READ_ONLY_SCOPE_AND_CURRENT_REVIEWED_FILES",
        "not_a_live_market_or_input_readiness_claim": True,
        "source_bundle": reviews.get("source_bundle"),
        "counts": {name: dict(Counter(row[name] for row in items)) for name in
            ("identity_status", "asset_fact", "provider_standard_asset_mapping", "price_action_fact", "depth_unit_fact")},
        "last_persisted_preflight_not_current": saved_worker.get("worker", {}).get("price_fact_preflight"),
        "items": items, "next_window": {
            "preheat_at": (opening - timedelta(hours=1)).isoformat(),
            "decision_at": (opening - timedelta(minutes=5)).isoformat(),
            "opening_at": opening.isoformat(), "closing_at": closing.isoformat(),
            "checkpoint_minutes": [5, 10, 15, 20, 25],
            "checkpoints": [{"at": (opening + timedelta(minutes=minute)).isoformat(),
                "registered_directions": 222, "evaluated": None, "qualified": None, "outcome": "NOT_YET_OBSERVED"}
                for minute in (5, 10, 15, 20, 25)],
            "no_new_entries_after": (opening + timedelta(minutes=30)).isoformat(),
            "production_entry": "http://127.0.0.1:8020/?workspace=options&view=signals",
            "production_state": "STOPPED_STORAGE_INCIDENT_NOT_APPROVED_TO_RESTART"}}
    target = args.out / "source_gap_matrix.json"
    target.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(target), "registered": len(items), "counts": payload["counts"],
                      "trade_day": payload["trade_day"], "source_bundle": payload["source_bundle"]}))


if __name__ == "__main__":
    main()
