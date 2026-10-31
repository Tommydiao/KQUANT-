"""TEST_ONLY separate-process journal crash/recovery, not full topology acceptance."""
import argparse
from datetime import date
import json
import sqlite3
from contextlib import closing
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant import options_one_minute as common
from kquant import options_opening_momentum as model
from kquant import options_opening_momentum_journal as journal
from kquant.market_clock import session_bounds_utc


def run(phase, root):
    value = json.loads((root / "TEST_ONLY-input.json").read_text())
    now = common.timestamp(value["now"])
    db = root / "TEST_ONLY-journal.db"
    jobs = {}
    for symbol in value["symbols"]:
        key = "opening_momentum", value["session"], symbol, 1
        bars = [{**row, "symbol": symbol} for row in value["bars"]]
        reference = {**value["reference"], "symbol": symbol}
        jobs[key] = symbol, date.fromisoformat(value["session"]), bars, "TEST_ONLY", reference
    if phase == "lease":
        key, job = next(iter(jobs.items()))
        lease = journal.begin(db, key, job, now)
        (root / "TEST_ONLY-leased.json").write_text(json.dumps({"job_id": str(lease), "generation": lease.generation}))
        time.sleep(60)
        raise RuntimeError("TEST_PROCESS_WAS_NOT_TERMINATED")
    restored = journal.restore(db, now)
    completed = 0
    deadlines = []
    for key in restored:
        job = jobs[key]
        lease = journal.begin(db, key, job, now)
        if lease is None:
            raise RuntimeError("PENDING_JOB_NOT_RESTORED")
        opening, close_at = session_bounds_utc(job[1])
        rows = model.evaluate_pair(symbol=job[0], bars=job[2], history={}, reference=job[4],
            opening=opening, closing=close_at, now=now, scope_hash="TEST_ONLY", checkpoint=opening.replace(minute=35))
        assert all(not row["qualified_signal"] for row in rows)
        if not journal.finish(db, lease, rows=rows):
            raise RuntimeError("RECOVERED_CAS_NOT_COMMITTED")
        with closing(sqlite3.connect(db)) as connection:
            deadlines.append(connection.execute("SELECT deadline_at FROM two_hour_jobs WHERE job_id=?", (str(lease),)).fetchone()[0])
        completed += 1
    print(json.dumps({"test_only": True, "separate_process": True, "restored": len(restored),
        "completed": completed, "deadlines": deadlines, "actual_sdk": False,
        "production_topology_acceptance": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["lease", "recover"])
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    run(args.phase, args.root.resolve())
