"""Frozen contract for the DEV-only 24-hour mathematical action study."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "math_action_24h_dev_v1.json"
SCOPE = "DEV_ONLY"
EXPOSURE = "EXPOSED_RESEARCH"
CORE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def load_math_action_contract(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    path = path.resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("scope") != SCOPE or value.get("exposure") != EXPOSURE:
        raise ValueError("Only exposed DEV research is permitted")
    if value.get("execution_enabled") is not False or value.get("admission_enabled") is not False:
        raise ValueError("Mathematical study cannot enable execution or admission")
    universe = value.get("universe", {})
    if tuple(universe.get("spot_long", ())) != CORE_SYMBOLS:
        raise ValueError("Spot universe must remain frozen to BTC/ETH/SOL")
    if tuple(universe.get("perpetual_short", ())) != CORE_SYMBOLS:
        raise ValueError("Perpetual universe must remain frozen to BTC/ETH/SOL")
    if value["dataset"].get("perpetual_source") is not None:
        raise ValueError("Unregistered perpetual source")
    if value["claims"] != {
        "independent_oos": False,
        "calibrated_probability": False,
        "performance_gate_passed": False,
        "runtime_admission": False,
        "live_trading": False,
    }:
        raise ValueError("Research claims must remain fail-closed")
    if value["trade_plan"].get("same_bar_collision") != "stop_first":
        raise ValueError("Stop-first collision policy is mandatory")
    if value["trade_plan"].get("entry_outside_plan") != "not_filled":
        raise ValueError("Entry gap policy changed")
    if value["bayesian"].get("action_gate") != "posterior_q05_conditional_mean_gt_zero":
        raise ValueError("Bayesian action gate changed")
    result = dict(value)
    result["config_path"] = str(path)
    result["config_sha256"] = file_hash(path)
    result["contract_hash"] = canonical_hash(value)
    return result


def resolve_contract_path(contract: dict[str, Any], value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()
