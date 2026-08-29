from __future__ import annotations

import argparse
import json

from kquant_crypto.config import load_settings
from kquant_crypto.external_evidence import save_evidence_snapshot
from kquant_crypto.market_structure_evidence import fetch_binance_market_structure_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect public Binance market-structure evidence.")
    parser.add_argument("--symbol", default="BTC")
    args = parser.parse_args()
    settings = load_settings()
    result = fetch_binance_market_structure_evidence(
        asset_id=f"asset:{args.symbol.lower()}",
        symbol=args.symbol,
        universe_symbols=settings.core_symbols,
    )
    saved = save_evidence_snapshot(settings.db_path, result.snapshot)
    print(json.dumps({**result.to_mapping(), "snapshot": saved}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
