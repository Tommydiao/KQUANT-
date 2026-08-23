from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

from kquant_crypto.config import load_settings
from kquant_crypto.dex_runtime import DexDiscoveryRuntime


async def collect(runtime: DexDiscoveryRuntime, hours: float) -> dict:
    if hours <= 0:
        result = await runtime.run_once()
        return {"provider": "dexscreener", "started_at": result["run_at"], "runs": 1, "last": result}
    deadline = datetime.now(UTC) + timedelta(hours=max(0.0, hours))
    runs = []
    while datetime.now(UTC) < deadline:
        runs.append(await runtime.run_once())
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            break
        await asyncio.sleep(min(runtime.interval_seconds, remaining))
    return {"provider": "dexscreener", "started_at": runs[0]["run_at"] if runs else None, "runs": len(runs), "last": runs[-1] if runs else None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only DEX discovery collection.")
    parser.add_argument("--hours", type=float, default=0.0)
    parser.add_argument("--interval-seconds", type=float, default=300.0)
    parser.add_argument("--query", action="append", dest="queries")
    args = parser.parse_args()
    settings = load_settings()
    runtime = DexDiscoveryRuntime(settings, queries=args.queries or ["SOL", "WIF", "BONK", "PEPE", "DOGE"], interval_seconds=args.interval_seconds)
    print(json.dumps(asyncio.run(collect(runtime, args.hours)), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
