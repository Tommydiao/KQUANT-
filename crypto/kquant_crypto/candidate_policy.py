from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/dual_regime_candidate_v1.json"


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_policy(path: Path = DEFAULT_CONFIG, candidate: str | None = None) -> dict:
    defaults = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    value = json.loads(path.read_text(encoding="utf-8"))
    if set(value) != set(defaults):
        raise ValueError("Candidate config must contain exactly the registered fields")
    allowed_changes = {"candidate", "database", "output_dir", "data_dir"}
    if any(value[key] != defaults[key] for key in defaults if key not in allowed_changes):
        raise ValueError("Frozen candidate policy fields cannot be changed")
    if candidate:
        value["candidate"] = candidate
    if value["candidate"] not in {"A", "B"}:
        raise ValueError("Only registered candidates A/B are permitted")
    source=ROOT / "docs/KQUANT_24H_Dual_Regime_Strategy_Plan_V2.0.md"
    value["specification_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    value["policy_hash"] = digest({k: v for k, v in value.items() if k not in {"database", "output_dir", "data_dir"}})
    return value


def resolve_path(policy: dict, key: str) -> Path:
    value = Path(policy[key])
    return value if value.is_absolute() else ROOT / value
