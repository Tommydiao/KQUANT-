"""Pending-before > 0 and a real child termination. No production database."""
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from kquant import options_one_minute as common
from kquant import options_opening_momentum_journal as journal
from kquant import options_opening_trend_store as store
from test_options_opening_momentum import inputs


def test_real_process_crash_with_pending_and_original_deadline(tmp_path):
    args = inputs()
    path = tmp_path / "TEST_ONLY-journal.db"
    store.initialize(path)
    journal.initialize(path)
    symbols = ["TESTA", "TESTB", "TESTC"]
    for symbol in symbols:
        bars = [{**row, "symbol": symbol} for row in args["bars"]]
        ref = {**deepcopy(args["reference"]), "symbol": symbol}
        key = "opening_momentum", "2026-10-02", symbol, 1
        assert journal.ready(path, key, (symbol, args["opening"].date(), bars, "TEST_ONLY", ref), args["now"])
    (tmp_path / "TEST_ONLY-input.json").write_text(json.dumps({
        "now": args["now"].isoformat(), "session": "2026-10-02", "symbols": symbols,
        "bars": args["bars"], "reference": args["reference"]}))
    script = Path(__file__).resolve().parents[1] / "scripts/check_r58_p10_pending_recovery.py"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    child = subprocess.Popen([sys.executable, str(script), "lease", str(tmp_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=flags)
    try:
        until = time.monotonic() + 8
        while not (tmp_path / "TEST_ONLY-leased.json").exists() and time.monotonic() < until and child.poll() is None:
            time.sleep(.03)
        assert (tmp_path / "TEST_ONLY-leased.json").exists()
        with closing(sqlite3.connect(path)) as db:
            pending = db.execute("SELECT COUNT(*) FROM two_hour_jobs WHERE state IN ('READY','LEASED')").fetchone()[0]
        assert pending == 3
        child.terminate()
        child.communicate(timeout=5)
        recovered = subprocess.run([sys.executable, str(script), "recover", str(tmp_path)],
            capture_output=True, text=True, timeout=10, creationflags=flags)
        assert recovered.returncode == 0, recovered.stderr
        result = json.loads(recovered.stdout)
        assert result["restored"] == result["completed"] == pending
        assert set(result["deadlines"]) == {(args["opening"] + timedelta(minutes=10)).isoformat()}
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT COUNT(*) FROM two_hour_jobs WHERE state='COMPLETED'").fetchone()[0] == 3
            assert db.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] == 6
            assert db.execute("SELECT COUNT(*) FROM qualified_claims").fetchone()[0] == 0
        assert journal.restore(path, args["opening"] + timedelta(minutes=10)) == {}
        (tmp_path / "TEST_ONLY-recovery-result.json").write_text(json.dumps({**result, "pending_before": pending}))
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
