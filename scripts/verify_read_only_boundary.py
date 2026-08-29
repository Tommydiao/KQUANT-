from __future__ import annotations

import json
from pathlib import Path

from kquant.dashboard.app import create_app, route_safety_report


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_RUNTIME_TEXT = (
    "btc_eth_15m",
    "TradeContext",
    "broker_for_mode",
    "submit_order",
    "/api/orders",
    "/api/positions",
    "Binance",
)
SECRET_PATTERNS = (
    "LONGBRIDGE_APP_SECRET=",
    "LONGBRIDGE_ACCESS_TOKEN=",
    "OPENAI_API_KEY=",
)


def main() -> None:
    app = create_app()
    report = route_safety_report(app)
    failures: list[str] = []
    if report["status"] != "pass":
        failures.append(f"forbidden routes: {report['forbidden_routes']}")
    runtime_source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "kquant").rglob("*.py"))
    for token in FORBIDDEN_RUNTIME_TEXT:
        if token in runtime_source:
            failures.append(f"forbidden runtime token: {token}")
    bundle_dir = ROOT / "web" / "dist" / "assets"
    if bundle_dir.exists():
        bundle = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in bundle_dir.rglob("*.js"))
        for pattern in SECRET_PATTERNS:
            if pattern in bundle:
                failures.append(f"secret assignment leaked into bundle: {pattern}")
        for path in ("/api/broker", "/api/account", "/api/orders", "/api/positions", "/api/mstr/cycle-radar"):
            if path in bundle:
                failures.append(f"removed API path remains in bundle: {path}")
    print(json.dumps({"status": "fail" if failures else "pass", "route_safety": report, "failures": failures}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
