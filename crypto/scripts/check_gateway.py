from __future__ import annotations

import argparse
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the local read-only Stocks/Crypto gateway.")
    parser.add_argument("--url", default="http://127.0.0.1:8020")
    args = parser.parse_args()
    # The gateway probes two backends sequentially; bypass local proxy settings
    # and allow enough time for a cold backend health check.
    with httpx.Client(timeout=10.0, trust_env=False) as client:
        response = client.get(args.url.rstrip("/") + "/api/gateway/health")
    response.raise_for_status()
    body = response.json()
    print(f"gateway={body.get('gateway_version')}")
    print(f"stocks={body.get('stocks', {}).get('status')}")
    print(f"crypto={body.get('crypto', {}).get('status')}")
    print(f"data_mixing={body.get('data_mixing')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
