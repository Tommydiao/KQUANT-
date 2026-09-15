"""Versioned recovery research; never writes the source run or execution storage."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from kquant_crypto.low_frequency_research import DAY, STEP, SYMBOLS, digest, stamp
from run_low_frequency_research import write, csv_write

OFFICIAL = "https://www.binance.com/en/blog/from-our-ceo/6789340645608890113"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gap_groups(times):
    groups = []
    for t in sorted(times):
        if groups and groups[-1]["end"] == t:
            groups[-1]["end"] += STEP
        else:
            groups.append({"start": t, "end": t + STEP})
    return groups


def freeze(out, source):
    out.mkdir(parents=True, exist_ok=False)
    c = json.loads((source / "contract.json").read_text())
    policy = {"version": "lf_gap_recovery_v1.1.0", "scope": "DEV_ONLY",
        "strategy_hash": digest(c), "execution_enabled": False,
        "unknown_gap": "censor_original_path_and_restart_independent_account_after_full_warmup",
        "warmup_complete_days": 61, "capital_transfer_between_segments": False,
        "halt": "official_halt_plus_contiguous_trades_and_absent_or_zero_volume_minutes; exclude_zero_volume_placeholders; no_fills_or_trailing_updates; reopen_original_protection",
        "source_conflict": "UNKNOWN_not_imputed", "no_parameter_search": True}
    write(out / "recovery_policy.json", policy)
    write(out / "contract.json", c)
    files = list(source.glob("*.json")) + list(source.glob("*.parquet")) + list(source.glob("*.csv.gz"))
    write(out / "baseline_manifest.json", {str(p.relative_to(source)): sha(p) for p in files})
    write(out / "preregistration.json", {"source_run": str(source), "created_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.executable, "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "recovery_hash": digest(policy), "strategy_hash": digest(c), "restricted_history_consumed": False})
    snap = out / "source_snapshot"
    snap.mkdir()
    for p in [Path(__file__), ROOT / "kquant_crypto/low_frequency_research.py",
              ROOT / "kquant_crypto/low_frequency_recovery.py", ROOT / "scripts/verify_low_frequency_recovery.py",
              ROOT / "scripts/run_low_frequency_research.py"]:
        shutil.copy2(p, snap / p.name)


def acquire(out, source):
    manifest = json.loads((source / "dataset_manifest.json").read_text())
    jobs = set()
    for s, data in manifest["symbols"].items():
        for g in gap_groups(data["missing_timestamps"]):
            date = datetime.fromtimestamp(g["start"], timezone.utc).strftime("%Y-%m-%d")
            jobs.add((s, date, "1m"))
            if date == "2023-03-24": jobs.add((s, date, "aggTrades"))
    folder = out / "archives"
    folder.mkdir(exist_ok=True)
    def fetch(job):
        s, date, kind = job
        name = f"{s}-{kind}-{date}.zip"
        tail = f"klines/{s}/1m" if kind == "1m" else f"aggTrades/{s}"
        url = f"https://data.binance.vision/data/spot/daily/{tail}/{name}"
        target = folder / name
        try:
            for suffix in (".CHECKSUM", ""):
                dest = folder / (name + suffix)
                if not dest.exists():
                    with urlopen(url + suffix, timeout=120) as response: body = response.read()
                    with dest.open("xb") as f: f.write(body)
            expected = (folder / (name + ".CHECKSUM")).read_text().split()[0]
            if sha(target) != expected: raise ValueError("checksum mismatch")
            return {"symbol": s, "date": date, "kind": kind, "file": name, "sha256": expected,
                    "url": url, "status": "VERIFIED", "received_at": None,
                    "file_written_at": datetime.fromtimestamp(target.stat().st_mtime,timezone.utc).isoformat(),
                    "verified_at": datetime.now(timezone.utc).isoformat()}
        except Exception as exc:
            return {"symbol": s, "date": date, "kind": kind, "url": url, "status": "UNAVAILABLE", "error": str(exc)}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(fetch, sorted(jobs)))
    write(out / "supplemental_sources.json", results)
    print("acquired", len(results), "verified", sum(x["status"] == "VERIFIED" for x in results), flush=True)


def archive_frame(path):
    with zipfile.ZipFile(path) as z:
        with z.open(z.namelist()[0]) as f:
            return pd.read_csv(f, header=None)


def audit(out, source):
    manifest = json.loads((source / "dataset_manifest.json").read_text())
    sources = json.loads((out / "supplemental_sources.json").read_text())
    index = {(x["symbol"], x["date"], x["kind"]): x for x in sources if x["status"] == "VERIFIED"}
    rows = []
    for s, data in manifest["symbols"].items():
        for g in gap_groups(data["missing_timestamps"]):
            date = datetime.fromtimestamp(g["start"], timezone.utc).strftime("%Y-%m-%d")
            row = {"symbol": s, **g, "date": date, "missing_5m_bins": (g["end"]-g["start"])//STEP,
                   "gap_type": "UNKNOWN", "source_hashes": [], "recoverable_bins": [], "empty_minute_bins": [],
                   "confirmed_halt_bins": [], "policy": "lf_gap_recovery_v1.1.0"}
            m = None
            minute_source = index.get((s, date, "1m"))
            if minute_source:
                path = out / "archives" / minute_source["file"]
                if sha(path) != minute_source["sha256"]: raise ValueError("source drift")
                m = archive_frame(path)
                times = pd.to_numeric(m[0], errors="coerce")
                m = m.loc[times.notna()].copy()
                m[0] = pd.to_numeric(m[0]); m[6] = pd.to_numeric(m[6])
                row["source_hashes"].append(minute_source["sha256"])
                for t in range(g["start"], g["end"], STEP):
                    sub = m[(m[0] >= t*1000) & (m[0] < (t+STEP)*1000)]
                    if len(sub) == 5 and set(sub[0]) == set(range(t*1000, (t+STEP)*1000, 60000)) and (sub[6] == sub[0]+59999).all():
                        row["recoverable_bins"].append(t)
                    elif sub.empty: row["empty_minute_bins"].append(t)
                row["minute_last_before_gap"] = int(m.loc[m[0] < g["start"]*1000, 0].max()) if (m[0] < g["start"]*1000).any() else None
                row["minute_first_after_gap"] = int(m.loc[m[0] >= g["end"]*1000, 0].min()) if (m[0] >= g["end"]*1000).any() else None
            trade_source = index.get((s, date, "aggTrades"))
            if trade_source:
                path = out / "archives" / trade_source["file"]
                if sha(path) != trade_source["sha256"]: raise ValueError("source drift")
                trades = archive_frame(path)
                ts = pd.to_numeric(trades[5], errors="coerce").dropna().astype("int64")
                ids = pd.to_numeric(trades[0], errors="coerce").dropna().astype("int64")
                row["source_hashes"].append(trade_source["sha256"])
                row["aggtrade_ids_contiguous"] = bool((ids.diff().dropna() == 1).all())
                row["last_trade_before_reopen_ms"] = int(ts[ts < stamp(date)*1000+14*3600000].max())
                row["first_trade_after_reopen_ms"] = int(ts[ts >= stamp(date)*1000+14*3600000].min())
                row["halt_bins_including_placeholders"] = []
                # Use full intervals after the last actual trade, not the rounded announcement time.
                last = row["last_trade_before_reopen_ms"]
                first = row["first_trade_after_reopen_ms"]
                bounded = stamp(date)*1000 + (11*60+27)*60000 <= last < stamp(date)*1000 + (11*60+28)*60000
                bounded &= stamp(date)*1000 + 14*3600000 <= first < stamp(date)*1000 + 14*3600000+60000
                for t in range((last//(STEP*1000)+1)*STEP, first//(STEP*1000)*STEP, STEP):
                    sub = m[(m[0] >= t*1000) & (m[0] < (t+STEP)*1000)] if m is not None else None
                    minutes_agree = sub is not None and (sub.empty or (pd.to_numeric(sub[5]) == 0).all())
                    if (bounded and row["aggtrade_ids_contiguous"] and minutes_agree
                            and not ((ts >= t*1000) & (ts < (t+STEP)*1000)).any()):
                        row["halt_bins_including_placeholders"].append(t)
                        if g["start"] <= t < g["end"]: row["confirmed_halt_bins"].append(t)
                row["official_context"] = OFFICIAL
                row["announcement_start_not_used_as_fill_boundary"] = True
            n = row["missing_5m_bins"]
            row["unresolved_bins"] = [t for t in range(g["start"], g["end"], STEP)
                                      if t not in row["recoverable_bins"] and t not in row["confirmed_halt_bins"]]
            if len(row["recoverable_bins"]) == n: row["gap_type"] = "RECOVERABLE"
            elif len(row["confirmed_halt_bins"]) == n: row["gap_type"] = "CONFIRMED_HALT"
            elif row["recoverable_bins"] or row["confirmed_halt_bins"]: row["gap_type"] = "MIXED_UNKNOWN"
            rows.append(row)
    write(out / "gap_audit.json", {"gaps": rows, "official_source": OFFICIAL,
        "note": "Missing intervals are not synthetic bars. Partial close bins remain unknown unless all five original minute bars qualify."})
    print("audited", len(rows), "gaps", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze", "acquire", "audit", "replay", "report"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-run", default="dev_20260913_02")
    a = parser.parse_args()
    if any(Path(v).name != v for v in (a.run_id, a.source_run)): raise ValueError("invalid run name")
    source = ROOT / "outputs/low_frequency_research" / a.source_run
    out = ROOT / "outputs/low_frequency_recovery" / a.run_id
    if a.command == "freeze": freeze(out, source)
    else:
        registration = json.loads((out / "preregistration.json").read_text())
        if str(source) != registration["source_run"]: raise ValueError("source run mismatch")
        if digest(json.loads((out / "recovery_policy.json").read_text())) != registration["recovery_hash"]:
            raise ValueError("policy drift")
        if a.command == "acquire": acquire(out, source)
        elif a.command == "audit": audit(out, source)
        else:
            from kquant_crypto.low_frequency_recovery import run_recovery, report_recovery
            (run_recovery if a.command == "replay" else report_recovery)(out, source)
    print(out, flush=True)


if __name__ == "__main__": main()
