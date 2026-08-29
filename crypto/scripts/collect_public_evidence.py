from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kquant_crypto.config import load_settings  # noqa: E402
from kquant_crypto.db.migrations import migrate  # noqa: E402
from kquant_crypto.external_evidence import save_evidence_snapshot  # noqa: E402
from kquant_crypto.public_evidence import (  # noqa: E402
    fetch_binance_derivatives_evidence,
    fetch_okx_derivatives_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect secret-free public crypto evidence.")
    parser.add_argument("--symbol", action="append", required=True, help="base or exchange symbol, e.g. BTC or ETHUSDT")
    parser.add_argument("--source", choices=("binance", "okx"), default="binance", help="public derivatives source")
    parser.add_argument("--db-path", type=Path)
    args = parser.parse_args()
    settings = load_settings(ROOT)
    db_path = (args.db_path or settings.db_path).resolve()
    migrate(db_path)
    collector = fetch_binance_derivatives_evidence if args.source == "binance" else fetch_okx_derivatives_evidence
    for raw in args.symbol:
        symbol = raw.upper()
        asset = symbol.removesuffix("USDT").removesuffix("USDC").removesuffix("USD")
        result = collector(asset_id=f"asset:{asset.lower()}", symbol=symbol)
        saved = save_evidence_snapshot(db_path, result.snapshot)
        print(f"{asset}: status={result.status} trust={saved['trust_status']} fields={len(saved['values'])} missing={len(saved['missing_fields'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
