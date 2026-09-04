from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kquant_crypto.config import load_settings
from kquant_crypto.research_backfill import build_research_backfill_plan, summarize_backfill_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the immutable Binance research backfill plan; this command never downloads data.")
    parser.add_argument("--as-of", help="UTC ISO time used to make the plan reproducible.")
    args = parser.parse_args()
    settings = load_settings()
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else datetime.now(UTC)
    report = summarize_backfill_plan(build_research_backfill_plan(settings.root_dir, now=as_of))
    report["as_of"] = as_of.astimezone(UTC).isoformat()
    report["project_root"] = str(PROJECT_ROOT)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
