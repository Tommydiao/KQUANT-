from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kquant_crypto.dashboard.app import create_app  # noqa: E402


FORBIDDEN_SEGMENTS = {"account", "wallet", "orders", "positions", "trade", "swap", "withdraw"}
ALLOWED_EXECUTION_ROUTES = {
    "/api/crypto/execution/status": {"GET"},
    "/api/crypto/execution/strategies": {"GET"},
    "/api/crypto/execution/account-summary": {"GET"},
    "/api/crypto/execution/positions": {"GET"},
    "/api/crypto/execution/orders": {"GET"},
    "/api/crypto/execution/risk": {"GET"},
    "/api/crypto/execution/arm": {"POST"},
    "/api/crypto/execution/disarm": {"POST"},
    "/api/crypto/execution/kill-switch": {"POST"},
    "/api/crypto/execution/reconcile": {"POST"},
}


def route_segments(path: str) -> set[str]:
    return {segment.lower() for segment in re.split(r"/", path) if segment}


def main() -> int:
    app = create_app()
    violations: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        segments = route_segments(path)
        methods = set(getattr(route, "methods", set()))
        if path in ALLOWED_EXECUTION_ROUTES:
            if not methods <= ALLOWED_EXECUTION_ROUTES[path]:
                violations.append(f"unexpected execution methods {methods} {path}")
            continue
        if segments & FORBIDDEN_SEGMENTS:
            violations.append(f"{methods} {path}")
    if violations:
        print("Forbidden read/write routes found:")
        print("\n".join(violations))
        return 1
    print("Gated execution boundary passed; no arbitrary order, wallet, or withdrawal routes.")
    for route in sorted({getattr(item, "path", "") for item in app.routes}):
        print(route)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
