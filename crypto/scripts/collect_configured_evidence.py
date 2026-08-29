from __future__ import annotations

"""Collect a configured, source-timed ETF or on-chain JSON feed.

The command is intentionally explicit. It never falls back to a different
provider, fills missing values, or writes credentials to the database.
"""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kquant_crypto.config import load_settings  # noqa: E402
from kquant_crypto.db.migrations import migrate  # noqa: E402
from kquant_crypto.evidence_collectors import fetch_configured_evidence, normalize_provider_evidence  # noqa: E402
from kquant_crypto.external_evidence import save_evidence_snapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect configured ETF/on-chain evidence without secrets.")
    parser.add_argument("--source", choices=("official_etf_feed", "onchain_metrics_feed"), required=True)
    parser.add_argument("--category", choices=("etf_flow", "onchain", "whale", "protocol_metric"), required=True)
    parser.add_argument("--symbol", action="append", required=True, help="asset symbol, e.g. BTC or ETH")
    parser.add_argument("--db-path", type=Path)
    args = parser.parse_args()

    settings = load_settings(ROOT)
    db_path = (args.db_path or settings.db_path).resolve()
    migrate(db_path)
    url = settings.etf_evidence_url if args.source == "official_etf_feed" else settings.onchain_evidence_url

    for raw_symbol in args.symbol:
        symbol = str(raw_symbol).upper()
        result = fetch_configured_evidence(
            url=url,
            source=args.source,
            category=args.category,
            asset_id=f"asset:{symbol.lower()}",
            symbol=symbol,
        )
        snapshot = result.get("snapshot") or {}
        normalized = normalize_provider_evidence(
            snapshot.get("values") or {},
            source=args.source,
            category=args.category,
            asset_id=f"asset:{symbol.lower()}",
            symbol=symbol,
            source_status=snapshot.get("source_status") or "provider_unavailable",
            available_at=snapshot.get("available_at") or "",
            source_time=snapshot.get("source_time"),
            published_at=snapshot.get("published_at"),
        )
        saved = save_evidence_snapshot(db_path, normalized)
        print(
            f"{symbol}: status={result.get('status')} trust={saved['trust_status']} "
            f"fields={len(saved['values'])} missing={len(saved['missing_fields'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
