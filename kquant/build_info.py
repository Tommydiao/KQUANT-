from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _git_value(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


@lru_cache(maxsize=1)
def build_info() -> dict[str, Any]:
    """Return deployment identity without exposing runtime credentials."""

    sha = os.getenv("KQUANT_BUILD_SHA", "").strip() or _git_value("rev-parse", "HEAD")
    build_time = os.getenv("KQUANT_BUILD_TIME", "").strip() or _git_value(
        "show", "-s", "--format=%cI", "HEAD"
    )
    environment = os.getenv("KQUANT_ENVIRONMENT", "local").strip() or "local"
    return {
        "product": "KQUANT",
        "build_sha": sha,
        "build_sha_short": sha[:7] if sha != "unknown" else "unknown",
        "build_time": build_time,
        "environment": environment,
        "source_of_truth": "github_main" if sha != "unknown" else "unverified_build",
    }
