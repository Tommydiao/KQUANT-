from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .options_cbrm_research import _block_bootstrap, load_protocol


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENTS = ROOT / "outputs" / "cbrm_v0_2" / "cbrm-dev-v0-2-20260921-01" / "events.jsonl"
DEFAULT_RESULT = ROOT / "outputs" / "cbrm_v0_2" / "cbrm-dev-v0-2-20260921-01" / "result.json"
DEFAULT_STORE = ROOT / "work" / "cbrm_v0_2" / "cbrm.sqlite3"
AUDIT_VERSION = "cbrm-v0.2.1-evidence-audit"


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _complete_case_exclusions(events: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for right in ("CALL", "PUT"):
        mature = [event for event in events if event["right"] == right and event["label"]["state"] == "MATURE"]
        excluded = []
        for event in mature:
            missing = [
                feature for feature in ("C", "V_log", "B", "G")
                if event["features"].get(feature) is None
                or not math.isfinite(float(event["features"][feature]))
            ]
            if not missing:
                continue
            excluded.append({
                "economic_event_id": event["economic_event_id"],
                "session": event["session"],
                "symbol": event["symbol"],
                "missing_features": missing,
                "filter_states": event["filter_states"],
                "missing_participation_sessions": event["participation"].get("missing_sessions", []),
                "reason": "COMPLETE_CASE_FEATURE_UNAVAILABLE",
            })
        result[right] = {
            "mature_events": len(mature),
            "common_eligible_events": len(mature) - len(excluded),
            "excluded_count": len(excluded),
            "excluded": excluded,
        }
    return result


def _timing_audit(events: list[dict[str, Any]], store_path: Path) -> dict[str, Any]:
    legacy = [event for event in events if event["label"]["state"] == "INVALID_BEFORE_T0"]
    rows = []
    with sqlite3.connect(f"file:{store_path.resolve().as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for event in legacy:
            bars = {
                row["time_et"]: dict(row)
                for row in connection.execute(
                    "SELECT time_et,timestamp_utc,open,close,availability_at,lineage_hash "
                    "FROM minute_bars WHERE symbol=? AND session_date=? AND time_et IN ('09:40','09:45') ORDER BY time_et",
                    (event["symbol"], event["session"]),
                )
            }
            reconfirm = bars.get("09:40")
            entry = bars.get("09:45")
            if not reconfirm or not entry:
                raise RuntimeError(f"missing timing evidence for {event['economic_event_id']}")
            bar_start = datetime.fromisoformat(reconfirm["timestamp_utc"])
            available_at = bar_start + timedelta(minutes=5)
            level = float(event["level"])
            close = float(reconfirm["close"])
            entry_open = float(entry["open"])
            right = event["right"]
            close_crossed = close < level if right == "CALL" else close > level
            open_crossed = entry_open < level if right == "CALL" else entry_open > level
            rows.append({
                "economic_event_id": event["economic_event_id"],
                "symbol": event["symbol"],
                "right": right,
                "session": event["session"],
                "signal_at": event["signal_at"],
                "frozen_level": level,
                "reconfirmation_bar_start": reconfirm["timestamp_utc"],
                "reconfirmation_bar_end": available_at.isoformat(),
                "reconfirmation_available_at": available_at.isoformat(),
                "reconfirmation_close": close,
                "reference_entry_at": entry["timestamp_utc"],
                "reference_entry_open": entry_open,
                "crossed_on_reconfirmation_close": close_crossed,
                "crossed_on_reference_open": open_crossed,
                "decision_uses_complete_5m_bar": True,
                "decision_uses_30m_bar": False,
                "future_data_used": False,
                "corrected_state_name": "CANCELLED_AT_T0",
                "corrected_reason": "FIVE_MINUTE_RECONFIRMATION_FAILED_AT_REFERENCE_ENTRY",
                "source_lineage_hashes": [reconfirm["lineage_hash"], entry["lineage_hash"]],
            })
    by_right = {right: sum(row["right"] == right for row in rows) for right in ("CALL", "PUT")}
    trigger = {
        "reconfirmation_close_only": sum(row["crossed_on_reconfirmation_close"] and not row["crossed_on_reference_open"] for row in rows),
        "reference_open_only": sum(row["crossed_on_reference_open"] and not row["crossed_on_reconfirmation_close"] for row in rows),
        "both": sum(row["crossed_on_reference_open"] and row["crossed_on_reconfirmation_close"] for row in rows),
    }
    return {
        "legacy_state": "INVALID_BEFORE_T0",
        "corrected_semantics": "ENTRY_ELIGIBILITY_CANCELLED_AT_REFERENCE_T0_USING_COMPLETED_09_40_5M_CLOSE_AND_09_45_OPEN",
        "not_part_of_F_30M_LABEL": True,
        "first_post_entry_complete_30m_available_at_et": "10:00",
        "count": len(rows),
        "by_right": by_right,
        "trigger_breakdown": trigger,
        "events": rows,
    }


def build_audit(*, events_path: Path = DEFAULT_EVENTS, result_path: Path = DEFAULT_RESULT, store_path: Path = DEFAULT_STORE) -> dict[str, Any]:
    protocol = load_protocol()
    events = _load_events(events_path)
    previous = json.loads(result_path.read_text(encoding="utf-8"))
    bootstrap = {right: _block_bootstrap(events, right, protocol) for right in ("CALL", "PUT")}
    statistics_audit = {}
    for right in ("CALL", "PUT"):
        old = previous["bootstrap"][right]
        revised = bootstrap[right]
        statistics_audit[right] = {
            "legacy_mean_Y_estimate": old["mean_Y"].get("estimate"),
            "legacy_failure_rate_estimate": old["failure_rate"].get("estimate"),
            "revised": revised,
            "reconciliation": (
                "The table used the original event-weighted sample difference. The old bootstrap estimate field "
                "used the mean across block-bootstrap replicate differences. These are different statistics; "
                "the revised artifact names both and reports bootstrap bias against the original point estimate."
            ),
        }
    audit = {
        "audit_id": "cbrm-audit-v0-2-1-20260921-01",
        "audit_version": AUDIT_VERSION,
        "status": "DEV_ONLY_EVIDENCE_CORRECTION",
        "activity_policy_changed": False,
        "model_loaded_by_runtime": False,
        "source_run_id": previous["run_id"],
        "source_event_count": len(events),
        "source_events_sha256": hashlib.sha256(events_path.read_bytes()).hexdigest(),
        "source_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "statistics": statistics_audit,
        "timing": _timing_audit(events, store_path),
        "complete_case": _complete_case_exclusions(events),
        "decision": {
            "event_population_changed": False,
            "model_refit_required": False,
            "reason": "The audit corrects labels and estimand names; it finds no future 30m data in the t0 cancellation path.",
            "call_model_status": "RETAIN_DEV_ONLY_NOT_ACTIVE",
            "put_model_status": "INSUFFICIENT_TRAINING_SUPPORT_UNCHANGED",
        },
    }
    audit["audit_sha256"] = _digest(audit)
    return audit


__all__ = ["AUDIT_VERSION", "build_audit"]
