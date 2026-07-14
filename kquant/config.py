from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class KquantConfig:
    db_path: Path
    outputs_dir: Path
    product: str = "KQUANT US Stock Signal Terminal"


def load_config(path: str | Path = "config/default.yml") -> KquantConfig:
    config_path = Path(path)
    payload: dict[str, Any] = {}
    if config_path.exists():
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return KquantConfig(
        db_path=Path(payload.get("db_path") or "work/kquant_us.sqlite3"),
        outputs_dir=Path(payload.get("outputs_dir") or "outputs"),
        product=str(payload.get("product") or "KQUANT US Stock Signal Terminal"),
    )
