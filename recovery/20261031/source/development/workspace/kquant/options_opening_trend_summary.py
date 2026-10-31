"""Transport-only summaries; immutable evidence remains available by evaluation ID."""
from copy import deepcopy
import json
from collections import Counter


DETAIL_FIELDS = frozenset({
    "policy_snapshot", "factor_evidence", "reference_evidence", "input_checks",
    "event_coverage", "contract_qualification", "initial_eligibility",
})


def compact_record(row: dict) -> dict:
    result = {**{key: deepcopy(value) for key, value in row.items()
               if key not in DETAIL_FIELDS and key != "strategy_comparison"}, "evidence_deferred": True}
    if isinstance(row.get("strategy_comparison"), dict):
        from .options_intraday_comparison import compact_comparison
        result["strategy_comparison"] = compact_comparison(row["strategy_comparison"])
    elif "strategy_comparison" in row:
        result["strategy_comparison"] = deepcopy(row["strategy_comparison"])
    return result


def compact_status(payload: dict) -> dict:
    # Never trim the shared snapshot in place or change current eligibility proof.
    result = {key: deepcopy(value) for key, value in payload.items()
              if key not in {"evaluations", "candidates"}}
    for name in ("evaluations", "candidates"):
        rows = payload.get(name, [])
        # Current cards are bounded; historical evidence uses the existing paged API.
        result[name] = [compact_record(row) for row in rows[:8]]
        result[name + "_total"] = payload.get(name + "_total", len(rows))
        result[name + "_deferred"] = result[name + "_total"] > len(result[name])
    coverage = result.get("checkpoint_coverage")
    if isinstance(coverage, dict) and "items" in coverage:
        rows = coverage.pop("items", [])
        coverage["items_total"] = coverage.get("items_total", len(rows))
        coverage["items_deferred"] = True
    if isinstance(coverage, dict):
        for point in coverage.get("checkpoints", []):
            if "items" in point:
                items = point.pop("items")
                point["items_total"] = len(items)
                point["reason_counts"] = dict(Counter(reason for row in items for reason in set(row.get("reasons", []))))
                point["items_deferred"] = True
    result["response_format"] = "COMPACT_V2"
    if "registered_items" in result:
        result["registered_items"] = [{key: row[key] for key in ("symbol", "identity_status", "identity_reason") if key in row}
            for row in result["registered_items"]]
    for name in ("evaluations", "candidates"):
        while result[name] and len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 32768:
            result[name].pop()
            result[name + "_deferred"] = True
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 32768:
        for name in ("worker", "reference_collection"):
            value = result.get(name)
            if isinstance(value, dict):
                result[name] = {key: item for key, item in value.items() if not isinstance(item, (dict, list))}
                result[name]["diagnostics_deferred"] = True
    return result
