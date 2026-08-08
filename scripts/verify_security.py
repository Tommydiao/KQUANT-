from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from kquant.dashboard.app import create_app, route_safety_report
from kquant.security import SecuritySettings


ROOT = Path(__file__).resolve().parents[1]
SUSPICIOUS_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)(?:api[_-]?key|secret|access[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9_-]{16,}['\"]"),
)
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".json", ".yml", ".yaml", ".ps1", ".md"}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if Path(line).suffix.lower() in SOURCE_SUFFIXES]


def main() -> int:
    failures: list[str] = []
    for path in tracked_files():
        if path.name.startswith(".env"):
            failures.append(f"Tracked environment file: {path.relative_to(ROOT)}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SUSPICIOUS_SECRET_PATTERNS:
            if pattern.search(text):
                failures.append(f"Potential hard-coded secret: {path.relative_to(ROOT)}")
                break
    app = create_app(config_path=ROOT / "config" / "default.yml")
    safety = route_safety_report(app)
    if safety["status"] != "pass":
        failures.append("Forbidden runtime route registered.")
    source = (ROOT / "kquant" / "dashboard" / "app.py").read_text(encoding="utf-8")
    if "allow_origin_regex" in source:
        failures.append("Wildcard CORS regex remains in dashboard app.")
    security = SecuritySettings.from_environment().report()
    payload = {"status": "pass" if not failures else "fail", "failures": failures, "route_safety": safety, "security": security}
    print(payload)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
