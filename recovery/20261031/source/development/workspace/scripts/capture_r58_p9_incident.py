"""Bounded read-only incident queries; never migrate or touch production writes."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from time import monotonic

ROOT = Path(__file__).absolute().parents[1]


def read(path):
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.05)
    end = monotonic() + 1
    db.set_progress_handler(lambda: int(monotonic() > end), 100)
    return db


def capture(case):
    minute = ROOT / "work/options_one_minute/one_minute.sqlite3"
    research = minute.with_name("opening_trend_research.sqlite3")
    from kquant.options_opening_momentum import load_policy
    policy_hash = load_policy()["policy_hash"]
    if case == "watch":
        from kquant.options_two_hour_data import universe
        return universe(ROOT / "work/kquant_us.sqlite3")
    if case == "inputs":
        result = {}
        with closing(read(research)) as db:
            for symbol in ("FCX", "NVTS"):
                try:
                    row = db.execute("""SELECT payload_json FROM evaluations WHERE policy_hash=?
                        AND session='2026-10-05' AND symbol=? ORDER BY evaluated_at DESC LIMIT 1""",
                        (policy_hash, symbol)).fetchone()
                    value = json.loads(row[0]) if row else {}
                    result[symbol] = value.get("reference_evidence") or value.get("factor_evidence", {}).get("reference") or {"status": "ARCHIVE_NOT_FOUND"}
                    result[symbol + "_evaluation_envelope"] = {key: value.get(key) for key in
                        ("evaluation_id", "evaluated_at", "calculation_bar_end", "deadline_at", "scope_hash")}
                except sqlite3.Error as exc:
                    result[symbol] = {"status": "QUERY_UNCONFIRMED", "sqlite_code": getattr(exc, "sqlite_errorname", None)}
            row = db.execute("""SELECT payload_json FROM evaluations WHERE session='2026-10-05'
                AND policy_hash=? AND symbol='ASTX' ORDER BY evaluated_at DESC LIMIT 1""", (policy_hash,)).fetchone()
            result["ASTX_evaluation"] = json.loads(row[0]) if row else None
        with closing(read(minute)) as db:
            rows = db.execute("""SELECT payload_json FROM one_minute_bars WHERE session='2026-10-05'
                AND symbol='ASTX' AND open_at>=? AND open_at<? ORDER BY received_at LIMIT 501""",
                ("2026-10-05T13:30:00+00:00", "2026-10-05T13:55:00+00:00")).fetchall()
            result["ASTX_raw_versions"] = [json.loads(row[0]) for row in rows]
            for symbol in ("FCX", "NVTS"):
                rows = db.execute("""SELECT payload_json FROM one_minute_bars WHERE session='2026-10-05'
                    AND symbol=? AND open_at>=? AND open_at<? ORDER BY received_at LIMIT 101""",
                    (symbol, "2026-10-05T13:30:00+00:00", "2026-10-05T13:35:00+00:00")).fetchall()
                result[symbol + "_raw_versions"] = [json.loads(row[0]) for row in rows]
        return result
    if case.startswith("point-"):
        minute_number = int(case.split("-")[1])
        slot = f"2026-10-05T13:{minute_number:02}:00+00:00"
        with closing(read(research)) as db:
            rows = db.execute("""SELECT symbol,right_name,state,evaluated_at,
                json_extract(payload_json,'$.calculation_bar_end'),
                json_extract(payload_json,'$.reasons'),
                json_extract(payload_json,'$.runtime_inputs.input_generation'),
                json_extract(payload_json,'$.runtime_inputs.input_fingerprint')
                FROM evaluations WHERE session='2026-10-05' AND policy_hash=?
                AND json_extract(payload_json,'$.calculation_bar_end')=?
                ORDER BY evaluated_at LIMIT 3001""", (policy_hash, slot)).fetchall()
        if len(rows) > 3000:
            raise ValueError("CHECKPOINT_RECORD_BOUND_EXCEEDED")
        first = {}
        for row in rows:
            first.setdefault((row[0], row[1]), row)
        return {"checkpoint": slot, "query_confirmed": True, "first_direction_records": len(first),
            "first_states": dict(Counter(row[2] for row in first.values())), "records": rows,
            "revisions": len(rows) - len(first), "system_missing": None,
            "note": "Reconcile registered watch rows separately; do not infer missing from latest80."}
    raise ValueError("UNKNOWN_CASE")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--case")
    args = parser.parse_args()
    if args.case:
        try:
            value = capture(args.case)
            if args.out:
                value["capture"] = {"observed_at": datetime.now(UTC).isoformat(), "mode": "READ_ONLY_DIAGNOSTIC"}
                args.out.write_text(json.dumps(value, ensure_ascii=True, indent=2), encoding="utf-8")
                print(json.dumps({"case": args.case, "saved": str(args.out)}))
            else:
                print(json.dumps(value, ensure_ascii=True))
        except Exception as exc:
            print(json.dumps({"query_confirmed": False, "error_type": type(exc).__name__,
                "sqlite_code": getattr(exc, "sqlite_errorname", None)}))
        return
    args.out.mkdir(parents=True, exist_ok=True)
    for case in ("watch", "inputs", "point-35", "point-40", "point-45", "point-50", "point-55"):
        started = monotonic()
        try:
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(Path(__file__).absolute()),
                "--case", case], capture_output=True, timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            value = json.loads(result.stdout)
        except Exception as exc:
            value = {"query_confirmed": False, "error_type": type(exc).__name__}
        value["capture"] = {"observed_at": datetime.now(UTC).isoformat(),
                            "elapsed_seconds": monotonic() - started, "mode": "READ_ONLY_DIAGNOSTIC"}
        (args.out / (case + ".json")).write_text(json.dumps(value, ensure_ascii=True, indent=2), encoding="utf-8")
        print(json.dumps({"case": case, "confirmed": value.get("query_confirmed", "items" in value or "FCX" in value),
            "elapsed_seconds": monotonic() - started}), flush=True)


if __name__ == "__main__":
    main()
