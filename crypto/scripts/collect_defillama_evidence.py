from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kquant_crypto.config import load_settings  # noqa: E402
from kquant_crypto.external_evidence import save_evidence_snapshot  # noqa: E402
from kquant_crypto.providers.defillama import DefiLlamaPublicAdapter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect source-timed DefiLlama public evidence without credentials.")
    parser.add_argument("--category", choices=("onchain", "protocol_metric"), required=True)
    parser.add_argument("--symbol", action="append", required=True, help="Repeat for each symbol to collect.")
    args = parser.parse_args()
    settings = load_settings(ROOT)
    adapter = DefiLlamaPublicAdapter()
    results = []
    for raw_symbol in args.symbol:
        symbol = str(raw_symbol).strip().upper()
        result = adapter.fetch(
            asset_id=f"asset:{symbol.lower()}",
            symbol=symbol,
            category=args.category,
            enabled=settings.providers.defillama,
        )
        saved = save_evidence_snapshot(settings.db_path, result.snapshot)
        results.append({**result.to_mapping(), "snapshot": saved, "provider_enabled": settings.providers.defillama})
    print(json.dumps({"items": results, "research_only": True, "secrets_exposed": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
