from __future__ import annotations

import json
import argparse
from pathlib import Path

from kquant_crypto.config import load_settings
from kquant_crypto.parquet_store import ParquetMarketStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect crypto Parquet coverage and the long-run collection Gate.")
    parser.add_argument("--min-hours", type=float, default=23.0)
    args = parser.parse_args()
    settings = load_settings(Path(__file__).resolve().parents[1])
    coverage = ParquetMarketStore(settings.data_dir).coverage()
    streams = coverage.get("streams", [])
    required_symbols = {symbol.upper() for symbol in settings.core_symbols}
    eligible = [
        item for item in streams
        if item.get("span_hours") is not None and float(item["span_hours"]) >= args.min_hours
    ]
    eligible_symbols = {
        str(item.get("instrument_id", "")).rsplit(":", 1)[-1].upper()
        for item in eligible
    }
    persisted_gate_passed = bool(streams) and coverage.get("coverage_index_status") == "complete" and required_symbols.issubset(eligible_symbols)
    coverage["persisted_coverage_gate"] = {
        "status": "PASS" if persisted_gate_passed else "NO_GO",
        "evidence_scope": "persisted_parquet_span",
        "minimum_hours": args.min_hours,
        "required_symbols": sorted(required_symbols),
        "eligible_symbols": sorted(eligible_symbols),
        "reason": None if persisted_gate_passed else "coverage index, stream span or required core symbol coverage is incomplete",
    }
    report_path = settings.outputs_dir / "crypto_collection_latest.json"
    running_path = settings.outputs_dir / "crypto_collection_running.json"
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report = None
        coverage["continuous_collection_gate"] = (report or {}).get("collection_gate") or {
            "status": "NO_GO",
            "evidence_scope": "independent_collector_session",
            "failed_checks": ["invalid_collection_report"],
        }
    else:
        heartbeat = None
        if running_path.exists():
            try:
                heartbeat = json.loads(running_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                heartbeat = None
        coverage["continuous_collection_gate"] = {
            "status": "PENDING",
            "evidence_scope": "independent_collector_session",
            "failed_checks": ["collector_report_pending"],
            "heartbeat": heartbeat,
        }
    continuous = coverage["continuous_collection_gate"]
    coverage["gate"] = {
        "status": "PASS" if continuous.get("status") == "PASS" else "NO_GO",
        "evidence_scope": "independent_collector_session",
        "reason": None if continuous.get("status") == "PASS" else "independent collector session has not passed; persisted span is reported separately",
    }
    print(json.dumps(coverage, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
