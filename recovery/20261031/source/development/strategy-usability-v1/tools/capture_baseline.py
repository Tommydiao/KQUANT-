import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from bootstrap import activate
DEV, BASE = activate()
ROOT = BASE.parents[2]
from kquant import options_opening_momentum as s0

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

entry = read(BASE / "config/local_workspace_entry.json")
manifest = read(Path(entry["runtime_manifest"]["path"]))
roles = read(ROOT / "runtime/config/new-epoch-store-paths.json")
result = {"checked_at": datetime.now(UTC).isoformat(), "entry": entry,
    "roles": roles, "s0_normalized_hash": s0.load_policy()["policy_hash"],
    "s0_policy": s0.load_policy(), "baseline_files": {},
    "runtime": read(ROOT / "runtime/work/option_foundation/runtime/services.json"),
    "development_overlay": str(DEV), "production_changed": False}
for relative in ("kquant/options_opening_momentum.py", "config/options_opening_momentum_v1.json",
                 "kquant/options_opening_trend_runtime.py", "kquant/options_opening_trend_summary.py",
                 "web/src/unified/OptionsOperations.tsx"):
    result["baseline_files"][relative] = hashlib.sha256((BASE / relative).read_bytes()).hexdigest()
pack = Path(r"C:\Users\Administrator\AppData\Local\Temp\KQUANT_Strategy_Usability_Execution_Pack_V1_20261015.zip")
result["execution_pack_sha256"] = hashlib.sha256(pack.read_bytes()).hexdigest()
with zipfile.ZipFile(pack) as archive:
    for name in ("CODEX_START.md", "docs/EXECUTION_PLAN.md", "plan/research_protocol.json",
                 "plan/tasks.json", "plan/acceptance_tests.json"):
        raw = archive.read(name)
        dest = DEV / "input" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(raw)
minute = ROOT / "runtime/work/options_one_minute-epoch-20261008/one_minute.sqlite3"
research = ROOT / "runtime/work/options_one_minute/opening_trend_research.sqlite3"
for name, path in (("minute", minute), ("research", research)):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.2)) as db:
        db.execute("PRAGMA query_only=ON")
        import time
        deadline = time.monotonic() + 3
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        result[name + "_schema"] = db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'").fetchall()
        if name == "research":
            result["recent_evaluations"] = [readrow[0] for readrow in db.execute(
                "SELECT payload_json FROM evaluations ORDER BY rowid DESC LIMIT 2")]
        else:
            result["bar_samples"] = [json.loads(r[0]) for r in db.execute(
                "SELECT payload_json FROM one_minute_bars ORDER BY rowid DESC LIMIT 2")]
(DEV / "evidence").mkdir(exist_ok=True)
(DEV / "evidence/baseline_map.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"s0_hash": result["s0_normalized_hash"], "runtime": result["runtime"]["state"],
    "minute_tables": [r[0] for r in result["minute_schema"]],
    "research_tables": [r[0] for r in result["research_schema"]],
    "bar_samples": result.get("bar_samples")}, ensure_ascii=False))
