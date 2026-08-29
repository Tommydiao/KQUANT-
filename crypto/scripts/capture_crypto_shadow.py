from __future__ import annotations

"""Capture the current EVAL-approved crypto shadow set for a real calendar day."""

import argparse
import json
from pathlib import Path

from kquant_crypto.config import load_settings
from kquant_crypto.shadow_capture import capture_shadow_observations


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture EVAL-approved crypto shadow observations without synthetic days.")
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    settings = load_settings(Path(__file__).resolve().parents[1])
    result = capture_shadow_observations((args.db_path or settings.db_path).resolve(), limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
