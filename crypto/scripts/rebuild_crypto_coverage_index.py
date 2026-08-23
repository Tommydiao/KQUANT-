from __future__ import annotations

import argparse
import json
from pathlib import Path

from kquant_crypto.config import load_settings
from kquant_crypto.parquet_store import ParquetMarketStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the crypto Parquet coverage index after a collector upgrade.")
    parser.add_argument("--root", type=Path, default=None, help="Optional data root override.")
    args = parser.parse_args()
    settings = load_settings(Path(__file__).resolve().parents[1])
    store = ParquetMarketStore(args.root or settings.data_dir)
    print(json.dumps(store.rebuild_coverage_index(), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
