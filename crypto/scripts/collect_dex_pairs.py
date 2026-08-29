from __future__ import annotations

import argparse
import json

from kquant_crypto.config import load_settings
from kquant_crypto.dex_models import DexMarketStore
from kquant_crypto.providers.dexscreener import DexScreenerPublicAdapter


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect read-only DEX discovery snapshots.")
    parser.add_argument("--query", action="append", dest="queries", help="Token or pair search query; repeatable.")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    settings = load_settings()
    queries = args.queries or ["SOL", "WIF", "BONK", "PEPE", "DOGE"]
    adapter = DexScreenerPublicAdapter()
    store = DexMarketStore(settings.db_path)
    pairs = adapter.discover(queries, max_pairs=args.limit)
    saved = [store.save_pair(pair) for pair in pairs]
    print(json.dumps({"queries": queries, "discovered": len(pairs), "saved": len(saved), "deduplicated": sum(item["deduplicated"] for item in saved)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
