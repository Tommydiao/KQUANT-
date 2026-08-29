from __future__ import annotations

"""Collect optional CoinGlass evidence with explicit source lineage."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kquant_crypto.config import load_settings  # noqa: E402
from kquant_crypto.db.migrations import migrate  # noqa: E402
from kquant_crypto.external_evidence import save_evidence_snapshot  # noqa: E402
from kquant_crypto.providers.coinglass import CoinGlassPublicAdapter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect optional CoinGlass evidence without execution access.")
    parser.add_argument("--category", choices=("exchange_derivatives", "etf_flow", "onchain", "whale"), required=True)
    parser.add_argument("--symbol", action="append", required=True, help="asset symbol, e.g. BTC or ETH")
    parser.add_argument("--db-path", type=Path)
    args = parser.parse_args()

    settings = load_settings(ROOT)
    db_path = (args.db_path or settings.db_path).resolve()
    migrate(db_path)
    adapter = CoinGlassPublicAdapter(
        api_key=settings.coinglass_api_key if settings.providers.coinglass else "",
    )
    for raw_symbol in args.symbol:
        symbol = str(raw_symbol).upper()
        result = adapter.fetch(
            asset_id=f"asset:{symbol.lower()}",
            symbol=symbol,
            category=args.category,
        )
        saved = save_evidence_snapshot(db_path, result.snapshot)
        print(
            f"{symbol}: status={result.status} trust={saved['trust_status']} "
            f"fields={len(saved['values'])} missing={len(saved['missing_fields'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
