"""Explicit missing-policy status; absence never supplies substitute policy values."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


class PolicyConfigUnavailable(RuntimeError):
    def __init__(self, path: Path, capability: str, reason: str):
        self.path, self.capability, self.reason = Path(path), capability, reason
        super().__init__(reason)

    def status(self) -> dict[str, Any]:
        return {"status": "UNAVAILABLE", "reason": self.reason,
                "capability": self.capability, "config_file": self.path.name,
                "current_policy_available": False, "configuration_restored": False,
                "historical_records_status": "UNKNOWN", "position_records_complete": False,
                "old_position_continuity": "UNKNOWN",
                "scan_enabled": False, "signal_generation_enabled": False,
                "paper_enabled": False, "automatic_paper_enabled": False,
                "orders_enabled": False, "real_orders_enabled": False,
                "account_access_enabled": False}


def read_policy(path: Path, *, capability: str) -> dict[str, Any]:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise PolicyConfigUnavailable(path, capability, "POLICY_CONFIG_MISSING") from exc
    except (OSError, UnicodeError) as exc:
        raise PolicyConfigUnavailable(path, capability, "POLICY_CONFIG_UNREADABLE") from exc
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise PolicyConfigUnavailable(path, capability, "POLICY_CONFIG_INVALID") from exc
    if not isinstance(value, dict):
        raise PolicyConfigUnavailable(path, capability, "POLICY_CONFIG_INVALID")
    return value
