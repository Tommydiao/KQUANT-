from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


PATTERNS = {
    "openai_api_key": re.compile(r"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "longbridge_credential": re.compile(r"(?<![A-Za-z0-9_])ap_(?:m_)?[A-Za-z0-9._-]{24,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for path in tracked_files(root):
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                findings.append(f"{path.relative_to(root)}:{line}: {name}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when tracked files contain credential-shaped values.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    findings = scan(root)
    if findings:
        print("Tracked credential scan failed:")
        print("\n".join(findings))
        return 1
    print("Tracked credential scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
