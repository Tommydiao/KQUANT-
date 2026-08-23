from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kquant_crypto.dashboard.app import create_app  # noqa: E402


FORBIDDEN_SEGMENTS = {"account", "wallet", "orders", "positions", "trade", "swap"}


def route_segments(path: str) -> set[str]:
    return {segment.lower() for segment in re.split(r"/", path) if segment}


def main() -> int:
    app = create_app()
    violations: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        segments = route_segments(path)
        if segments & FORBIDDEN_SEGMENTS:
            violations.append(f"{getattr(route, 'methods', set())} {path}")
    if violations:
        print("Forbidden read/write routes found:")
        print("\n".join(violations))
        return 1
    print("Read-only boundary passed.")
    for route in sorted({getattr(item, "path", "") for item in app.routes}):
        print(route)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
