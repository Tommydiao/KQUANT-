"""Verify the migration and inspect disposable, companion-preserving DB copies."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def main():
    EVIDENCE.mkdir(exist_ok=True)
    manifests = [
        (ROOT / "development", ROOT / "development/TRANSFER_MANIFEST.json", "included"),
        (ROOT / "recovered-data", ROOT / "recovered-data/DATA_MANIFEST.json", None),
    ]
    verified = []
    for base, manifest, key in manifests:
        source = json.loads(manifest.read_text(encoding="utf-8-sig"))
        entries = source[key] if key else source
        failures = []
        for entry in entries:
            path = (base / entry["path"]).resolve()
            if not path.is_relative_to(base.resolve()):
                raise ValueError("Manifest path escaped its root")
            if not path.is_file() or path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"].lower():
                failures.append(entry["path"])
        result = {"manifest": str(manifest), "checked_files": len(entries), "mismatches": failures}
        verified.append(result)
        print(json.dumps(result), flush=True)
        if failures:
            raise ValueError("Migration file mismatch")
    (EVIDENCE / "extracted-file-verification.json").write_text(json.dumps(verified, indent=2), encoding="utf-8")

    original = ROOT / "recovered-data/business"
    copies = ROOT / "inspection-data"
    if copies.exists():
        raise FileExistsError("Inspection directory already exists; never overlay a prior audit")
    shutil.copytree(original, copies)
    results = []
    for path in sorted(copies.rglob("*.sqlite3")):
        started = time.monotonic()
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        db.execute("PRAGMA query_only=ON")
        quick_check = [r[0] for r in db.execute("PRAGMA quick_check")]
        tables = []
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            columns = [r[1] for r in db.execute(f"PRAGMA table_info({quote(name)})")]
            deadline = time.monotonic() + 10
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            table = {"table": name, "columns": columns}
            try:
                table["rows"] = db.execute(f"SELECT count(*) FROM {quote(name)}").fetchone()[0]
                for field in ("session", "session_date", "trade_date", "timestamp", "bar_start", "open_at", "bar_end", "created_at", "updated_at"):
                    if field in columns:
                        table[field] = list(db.execute(f"SELECT min({quote(field)}), max({quote(field)}) FROM {quote(name)}").fetchone())
                if "interval" in columns:
                    table["interval_counts"] = list(db.execute(f"SELECT interval,count(*) FROM {quote(name)} GROUP BY interval"))
            except sqlite3.DatabaseError as exc:
                table["query_error"] = type(exc).__name__
            finally:
                db.set_progress_handler(None, 0)
            tables.append(table)
        db.close()
        result = {"path": str(path.relative_to(ROOT)), "quick_check": quick_check, "seconds": round(time.monotonic()-started, 3), "tables": tables}
        results.append(result)
        print(json.dumps({"database":path.name,"quick_check":quick_check,"tables":len(tables),"seconds":result["seconds"]}), flush=True)
    report = {"scope":"isolated companion-preserving copies; original database files never opened", "complete_minute_database_present":False, "old_business_continuity":"UNKNOWN", "databases":results}
    (EVIDENCE / "database-audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__ == "__main__":
    main()
