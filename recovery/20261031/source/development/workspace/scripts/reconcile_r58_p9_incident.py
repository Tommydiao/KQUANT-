"""Enumerate each original watch direction from bounded archival captures."""
import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    watch = json.loads((args.capture / "watch.json").read_text())
    report = {"session": "2026-10-05", "scope_hash": watch["scope_hash"],
        "observed_at": datetime.now(UTC).isoformat(), "archived_diagnostic_only": True,
        "historical_instant_signals_created": 0, "checkpoints": []}
    for minute in (35, 40, 45, 50, 55):
        packet = json.loads((args.capture / f"point-{minute}.json").read_text())
        grouped = {}
        for row in packet.get("records", []):
            grouped.setdefault((row[0], row[1]), []).append(row)
        rows = []
        for asset in watch["items"]:
            for right in ("CALL", "PUT"):
                found = grouped.get((asset["symbol"], right), [])
                value = {"symbol": asset["symbol"], "right": right,
                    "checkpoint": packet["checkpoint"], "identity_status": asset["identity_status"]}
                if asset["identity_status"] != "verified":
                    value.update(state="IDENTITY_UNRESOLVED", reasons=["REGISTERED_IDENTITY_NOT_VERIFIED"])
                elif not packet.get("query_confirmed"):
                    value.update(state="QUERY_UNCONFIRMED", reasons=["BOUNDED_ARCHIVE_QUERY_FAILED"])
                elif not found:
                    value.update(state="NO_PERSISTED_RECORD", reasons=["SYSTEM_NOT_ACCOUNTED_AT_ORIGINAL_CHECKPOINT"],
                        journal_state="NOT_CAPTURED_DO_NOT_INFER")
                else:
                    first, latest = found[0], found[-1]
                    value.update(state=first[2], first_evaluated_at=first[3], reasons=json.loads(first[5]),
                        first_generation=first[6], first_fingerprint=first[7], latest_state=latest[2],
                        latest_evaluated_at=latest[3], evaluation_records=len(found), revisions=len(found) - 1)
                rows.append(value)
        assert len(rows) == 222
        report["checkpoints"].append({"checkpoint": packet["checkpoint"], "query_confirmed": packet["query_confirmed"],
            "registered_directions": len(rows), "states": dict(Counter(row["state"] for row in rows)),
            "first_direction_records": sum("first_evaluated_at" in row for row in rows),
            "revisions": sum(row.get("revisions", 0) for row in rows), "items": rows,
            "capture": packet["capture"]})
    args.out.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps([{k: v for k, v in point.items() if k not in {"items", "capture"}} for point in report["checkpoints"]]))


if __name__ == "__main__":
    main()
