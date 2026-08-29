from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kquant_crypto.config import load_settings  # noqa: E402
from kquant_crypto.market_runtime import MarketDataRuntime  # noqa: E402
from kquant_crypto.provider_runtime import ProviderSupervisor, provider_health  # noqa: E402
from kquant_crypto.collection_gate import evaluate_collection_gate  # noqa: E402


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


async def collect(hours: float, *, rebuild_index: bool = False) -> int:
    settings = load_settings(ROOT)
    started_at = datetime.now(UTC)
    running_path = settings.outputs_dir / "crypto_collection_running.json"
    runtime = MarketDataRuntime(
        settings.data_dir,
        db_path=settings.db_path,
        flush_every=settings.market_storage_flush_every,
        trade_bucket_seconds=settings.market_trade_bucket_seconds,
        quote_sample_seconds=settings.market_quote_sample_seconds,
        ticker_sample_seconds=settings.market_ticker_sample_seconds,
    )
    supervisor = ProviderSupervisor(settings, on_event=runtime.ingest)
    if not any(settings.providers.as_dict().get(name, False) for name in ("binance", "okx", "coinbase", "kraken")):
        raise RuntimeError("Enable at least one public CEX provider in .env before collection.")
    task = asyncio.create_task(supervisor.run(list(settings.core_symbols)))
    enabled_providers = [
        name for name, enabled in settings.providers.as_dict().items()
        if enabled and name in {"binance", "okx", "coinbase", "kraken"}
    ]
    _write_json(running_path, {
        "status": "running",
        "started_at": started_at.isoformat(),
        "requested_hours": hours,
        "symbols": list(settings.core_symbols),
        "providers": enabled_providers,
        "market_data_only": True,
        "paper_or_order_access": False,
    })
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.1, hours * 3600)
    run_error: dict[str, str] | None = None
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(30.0, remaining))
            _write_json(running_path, {
                "status": "running",
                "started_at": started_at.isoformat(),
                "heartbeat_at": datetime.now(UTC).isoformat(),
                "requested_hours": hours,
                "elapsed_hours": round((datetime.now(UTC) - started_at).total_seconds() / 3600.0, 4),
                "event_count": runtime.coverage()["collection_window"]["event_count"],
                "symbols": list(settings.core_symbols),
                "providers": enabled_providers,
                "market_data_only": True,
                "paper_or_order_access": False,
            })
    except Exception as exc:
        # Persist a secret-free failure report so maintenance never waits on
        # a marker whose process has already exited. The continuous Gate stays
        # NO_GO; partial Parquet data remains useful as storage evidence.
        run_error = {"error_type": type(exc).__name__}
    finally:
        supervisor.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        runtime.flush(force=True)
    # Older collectors may have written valid Parquet files before the
    # incremental coverage index existed. Rebuild after the writer has
    # stopped so the final Gate is based on the complete append-only dataset.
    coverage_index = (
        runtime.store.rebuild_coverage_index()
        if rebuild_index
        else {
            "status": "skipped",
            "reason": "full raw coverage rebuild is an explicit maintenance operation",
            "raw_index_repair_required": runtime.coverage().get("storage", {}).get("raw_index_repair_required", True),
        }
    )
    report = {
        "status": "failed" if run_error else "completed",
        "started_at": started_at.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "requested_hours": hours,
        "symbols": list(settings.core_symbols),
        "coverage": runtime.coverage(),
        "coverage_index_rebuild": coverage_index,
        "providers": provider_health(settings, supervisor),
        "market_data_only": True,
        "paper_or_order_access": False,
    }
    if run_error:
        report["failure"] = run_error
    window = report["coverage"].get("collection_window", {})
    required_symbols = {symbol.upper() for symbol in settings.core_symbols}
    eligible_streams = [
        item for item in window.get("streams", [])
        if item.get("span_hours") is not None and float(item["span_hours"]) >= max(23.0, hours * 0.95)
    ]
    eligible_symbols = {
        str(item.get("instrument_id", "")).rsplit(":", 1)[-1].upper()
        for item in eligible_streams
    }
    report["collection_gate"] = evaluate_collection_gate(
        started_at=report["started_at"],
        ended_at=report["ended_at"],
        requested_hours=hours,
        required_symbols=sorted(required_symbols),
        streams=window.get("streams", []),
        providers=report["providers"],
    )
    if run_error:
        report["collection_gate"] = {
            **report["collection_gate"],
            "status": "NO_GO",
            "failed_checks": list(dict.fromkeys(["collector_exception", *report["collection_gate"].get("failed_checks", [])])),
        }
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    report_path = settings.outputs_dir / "crypto_collection_latest.json"
    _write_json(report_path, report)
    with suppress(FileNotFoundError):
        running_path.unlink()
    print(json.dumps({"report_path": str(report_path), **report}, ensure_ascii=False, indent=2, default=str))
    return 1 if run_error else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect public crypto market data into Parquet.")
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Run the explicit full raw coverage rebuild after collection; omitted by default for large archives.",
    )
    args = parser.parse_args()
    return asyncio.run(collect(args.hours, rebuild_index=args.rebuild_index))


if __name__ == "__main__":
    raise SystemExit(main())
