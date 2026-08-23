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


async def collect(hours: float) -> int:
    settings = load_settings(ROOT)
    started_at = datetime.now(UTC)
    running_path = settings.outputs_dir / "crypto_collection_running.json"
    runtime = MarketDataRuntime(settings.data_dir, db_path=settings.db_path)
    supervisor = ProviderSupervisor(settings, on_event=runtime.ingest)
    if not any(settings.providers.as_dict().get(name, False) for name in ("binance", "okx", "coinbase", "kraken")):
        raise RuntimeError("Enable at least one public CEX provider in .env before collection.")
    task = asyncio.create_task(supervisor.run(list(settings.core_symbols)))
    _write_json(running_path, {
        "status": "running",
        "started_at": started_at.isoformat(),
        "requested_hours": hours,
        "symbols": list(settings.core_symbols),
        "market_data_only": True,
        "paper_or_order_access": False,
    })
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.1, hours * 3600)
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
                "market_data_only": True,
                "paper_or_order_access": False,
            })
    finally:
        supervisor.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        runtime.flush()
    # Older collectors may have written valid Parquet files before the
    # incremental coverage index existed. Rebuild after the writer has
    # stopped so the final Gate is based on the complete append-only dataset.
    coverage_index = runtime.store.rebuild_coverage_index()
    report = {
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
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    report_path = settings.outputs_dir / "crypto_collection_latest.json"
    _write_json(report_path, report)
    with suppress(FileNotFoundError):
        running_path.unlink()
    print(json.dumps({"report_path": str(report_path), **report}, ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect public crypto market data into Parquet.")
    parser.add_argument("--hours", type=float, default=24.0)
    args = parser.parse_args()
    return asyncio.run(collect(args.hours))


if __name__ == "__main__":
    raise SystemExit(main())
