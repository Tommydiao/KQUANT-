"""Independent, explicit recovery accounting around the unchanged strategy kernel."""
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .low_frequency_research import (CANDIDATES, SYMBOLS, DAY, STEP, digest, load_contract,
    prepare_market, replay, metrics, recost, centered_block_test, stamp)


def write(path, obj):
    body = json.dumps(obj, indent=2, sort_keys=True, allow_nan=False)
    with path.open("x", encoding="utf-8") as f: f.write(body)


def csv_write(path, rows):
    keys = sorted({k for r in rows for k in r})
    with gzip.open(path, "xt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def safe_metrics(result):
    value = dict(result["metrics"])
    if result["uncertain"]:
        value["capital_return"] = value["max_drawdown"] = None
    return value


def independent_segments(market, c, candidate, start, end, signals, halts=frozenset(), multiplier=1, excluded=()):
    """Only a holding-path failure ends an account; never transfer its uncertain cash."""
    segments = []
    cursor = start
    while cursor < end:
        sig = {t: ps for t, ps in signals.items() if cursor <= t < end}
        r = replay(market, c, candidate, cursor, end, multiplier, sig, excluded=excluded, confirmed_halts=halts)
        gaps = [e["time"] for e in r["events"] if e["reason"] == "unresolved_holding_gap"]
        segment_end = end
        restart = None
        if gaps:
            at = min(gaps)
            segment_end = at + STEP
            # Recompute only the sealed prefix; no outcomes after the unknown path survive.
            r = replay(market, c, candidate, cursor, segment_end, multiplier,
                       {t: p for t, p in sig.items() if t < segment_end}, excluded=excluded, confirmed_halts=halts)
            after = segment_end
            while after < end and not all(after in market.frames[s].index for s in SYMBOLS): after += STEP
            first_full_day = ((after + DAY-1)//DAY)*DAY
            restart = first_full_day + (c["momentum_days"]+1)*DAY + c["entry_delay_seconds"]
        sid = f"{start}_{len(segments):02d}"
        for row in r["trades"]:
            row.update(segment_id=sid, equity_trust="UNKNOWN_PATH" if r["uncertain"] else "KNOWN_SEGMENT",
                       recovery_policy="lf_gap_recovery_v1.1.0")
        segments.append({"segment_id": sid, "start": cursor, "end": segment_end,
            "restart_at": restart, "starting_capital": c["capital"], "capital_inherited": False,
            "result": r})
        if restart is None or restart >= end: break
        if restart <= cursor: raise ValueError("Non-progressing restart")
        cursor = restart
    return segments


def build_recovered_market(out, source, c):
    from zipfile import ZipFile
    original = json.loads((source / "dataset_manifest.json").read_text())
    audit = json.loads((out / "gap_audit.json").read_text())["gaps"]
    frames, changes, halts = {}, [], set()
    for s in SYMBOLS:
        p = source / f"{s}_5m.parquet"
        if hashlib.sha256(p.read_bytes()).hexdigest() != original["symbols"][s]["sha256"]: raise ValueError("source drift")
        frame = pd.read_parquet(p)
        for g in audit:
            if g["symbol"] != s: continue
            for t in g.get("halt_bins_including_placeholders", []):
                if t in frame.index:
                    if frame.loc[t, "volume"] != 0: raise ValueError("halt contradicts nonzero archive volume")
                    frame = frame.drop(t)
                    changes.append({"symbol": s, "time": t, "kind": "excluded_exchange_zero_volume_halt_placeholder", "sources": g["source_hashes"]})
                halts.add((s, t))
            if not g["recoverable_bins"]: continue
            name = f"{s}-1m-{g['date']}.zip"
            with ZipFile(out / "archives" / name) as z:
                with z.open(z.namelist()[0]) as f: m = pd.read_csv(f, header=None)
            for t in g["recoverable_bins"]:
                v = m[(m[0] >= t*1000) & (m[0] < (t+STEP)*1000)].sort_values(0)
                if len(v) != 5 or set(v[0]) != set(range(t*1000, (t+STEP)*1000, 60000)) or not (v[6] == v[0]+59999).all():
                    raise ValueError("invalid minute reconstruction")
                frame.loc[t] = [float(v[1].iloc[0]), float(v[2].max()), float(v[3].min()), float(v[4].iloc[-1]), float(v[5].sum())]
                changes.append({"symbol": s, "time": t, "kind": "reconstructed_five_complete_native_minutes", "sources": g["source_hashes"]})
        frames[s] = frame.sort_index()
        p = out / f"{s}_5m.parquet"
        if p.exists(): raise FileExistsError(p)
        frames[s].to_parquet(p)
    write(out / "data_changes.json", {"changes": changes, "confirmed_halts": sorted(halts),
        "manifest": {s: hashlib.sha256((out / f"{s}_5m.parquet").read_bytes()).hexdigest() for s in SYMBOLS},
        "synthetic_prices": False, "historical_execution": "BAR_PROXY_NOT_EXCHANGE_FILLS"})
    return prepare_market(frames, c), frozenset(halts)


def run_recovery(out, source):
    c = load_contract(out / "contract.json")
    policy = json.loads((out / "recovery_policy.json").read_text())
    if digest(c) != policy["strategy_hash"]: raise ValueError("strategy drift")
    for item in json.loads((out / "supplemental_sources.json").read_text()):
        if item["status"] == "VERIFIED" and hashlib.sha256((out / "archives" / item["file"]).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Supplemental source drift before replay")
    write(out / "replay_source_hashes.json", {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [Path(__file__), Path(__file__).with_name("low_frequency_research.py")]})
    market, halts = build_recovered_market(out, source, c)
    summary = {}
    for candidate in CANDIDATES:
        all_trades, all_stress, all_segments = [], [], []
        for year in c["evaluation_years"]:
            start, end = stamp(f"{year}-01-01")+c["embargo_days"]*DAY, stamp(f"{year+1}-01-01")
            entry_end = end-c["max_holding_days"]*DAY-STEP
            signals = {t: p for t,p in market.signals.items() if start <= t < entry_end}
            for scenario, multiplier in (("base",1),("stress",2)):
                segments = independent_segments(market,c,candidate,start,end,signals,halts,multiplier)
                for segment in segments:
                    r = segment["result"]
                    prefix = f"{candidate}_{year}_{scenario}_{segment['segment_id']}"
                    csv_write(out / f"{prefix}_trades.csv.gz",r["trades"])
                    csv_write(out / f"{prefix}_equity.csv.gz",r["equity"])
                    csv_write(out / f"{prefix}_events.csv.gz",r["events"])
                    all_segments.append({k:v for k,v in segment.items() if k != "result"} | {
                        "year":year,"scenario":scenario,"metrics":safe_metrics(r),"uncertain":r["uncertain"],
                        "event_counts":dict(Counter(e["reason"] for e in r["events"])),
                        "by_symbol":{s:metrics([t for t in r["trades"] if t["symbol"]==s],[]) for s in SYMBOLS}})
                    (all_trades if scenario=="base" else all_stress).extend(r["trades"])
                print(candidate,year,scenario,[(s["result"]["metrics"]["trades"],s["result"]["metrics"]["censored"]) for s in segments],flush=True)
        mature = [t for t in all_trades if t["label_status"]=="MATURE"]
        best = max(SYMBOLS,key=lambda s:sum(t["net_pnl"] for t in mature if t["symbol"]==s))
        leave_trades = []
        for year in c["evaluation_years"]:
            start,end=stamp(f"{year}-01-01")+c["embargo_days"]*DAY,stamp(f"{year+1}-01-01")
            signals={t:p for t,p in market.signals.items() if start<=t<end-c["max_holding_days"]*DAY-STEP}
            for seg in independent_segments(market,c,candidate,start,end,signals,halts,excluded=(best,)):
                leave_trades.extend(seg["result"]["trades"])
                prefix=f"{candidate}_{year}_leave_best_{seg['segment_id']}"
                csv_write(out/f"{prefix}_equity.csv.gz",seg["result"]["equity"])
        csv_write(out/f"{candidate}_leave_best_trades.csv.gz",leave_trades)
        csv_write(out/f"{candidate}_all_base_trades.csv.gz",all_trades)
        fixed=recost(all_trades,c,2)
        csv_write(out/f"{candidate}_fixed_double_cost.csv.gz",fixed)
        biggest=max(mature,key=lambda t:t["net_pnl"],default=None)
        summary[candidate]={"combined_completed_only":metrics(all_trades,[]),"segments":all_segments,
            "fixed_double_cost":metrics(fixed,[]),"full_stress":metrics(all_stress,[]),
            "leave_best_symbol":{"symbol":best,"metrics":metrics(leave_trades,[])},
            "remove_largest_trade":metrics([t for t in mature if t is not biggest],[]),
            "exit_attribution":{r:{"count":sum(t["exit_reason"]==r for t in mature),
                "net_pnl":sum(t["net_pnl"] for t in mature if t["exit_reason"]==r),
                "mean_days":float(np.mean([(t["exit_time"]-t["entry_time"])/DAY for t in mature if t["exit_reason"]==r]))}
                for r in sorted({t["exit_reason"] for t in mature})},
            "uncertainty":centered_block_test(all_trades,stamp("2022-01-01"),stamp("2025-01-01"),c),
            "accounting":"independent accounts; no linked NAV; completed pooled trade metrics only"}
    write(out/"recovery_results.json",summary)


def report_recovery(out, source):
    c=load_contract(out/"contract.json")
    results=json.loads((out/"recovery_results.json").read_text())
    baseline=json.loads((source/"delivery_summary.json").read_text())["candidates"]
    running=0.
    for rank,k in enumerate(sorted(results,key=lambda k:results[k]["uncertainty"]["p_value"] if results[k]["uncertainty"]["p_value"] is not None else 1)):
        p=results[k]["uncertainty"]["p_value"]
        running=max(running,min(1.,(2-rank)*(p if p is not None else 1)))
        results[k]["holm_p"]=running
    for k,r in results.items():
        m=r["combined_completed_only"]
        def ge(v,x): return v is not None and v>=x
        target=c["targets"]
        known=[s for s in r["segments"] if s["scenario"]=="base"]
        r["checks"]={"pf":ge(m["pf"],target["pf"]),"payoff":ge(m["payoff"],target["payoff"]),
            "positive_mean_r":ge(m["mean_r"],1e-15),"fixed_stress_pf":ge(r["fixed_double_cost"]["pf"],target["stress_pf"]),
            "full_stress_positive":ge(r["full_stress"]["mean_r"],1e-15),"samples":m["trades"]>=target["trades"],
            "per_symbol":all(sum(s["by_symbol"][sym]["trades"] for s in known)>=target["per_symbol"] for sym in SYMBOLS),
            "no_unresolved_paths":all(not s["uncertain"] for s in r["segments"]),
            "segment_drawdowns":all(s["metrics"]["max_drawdown"] is not None and s["metrics"]["max_drawdown"]<=target["max_drawdown"] for s in known),
            "continuous_portfolio_drawdown":False,"legacy_10r_resolved":c["legacy_10r_resolved"],
            "leave_best_positive":ge(r["leave_best_symbol"]["metrics"]["mean_r"],1e-15),
            "remove_largest_positive":ge(r["remove_largest_trade"]["mean_r"],1e-15),
            "holm_significance":r["holm_p"]<=target["alpha"]}
        r["baseline_completed"]=baseline[k]["combined"]
        r["failed_checks"]=[name for name,ok in r["checks"].items() if not ok]
        r["decision"]="REJECT_CURRENT_DEFINITION" if not all(r["checks"][x] for x in ("pf","payoff","positive_mean_r","fixed_stress_pf","full_stress_positive")) else "LIMITED_DEV_EVIDENCE_ONLY"
    original=json.loads((out/"baseline_manifest.json").read_text())
    changed=[name for name,h in original.items() if hashlib.sha256((source/name).read_bytes()).hexdigest()!=h]
    if changed: raise ValueError(f"baseline changed: {changed}")
    write(out/"delivery_summary.json",{"candidates":results,"baseline_unchanged":True,
        "data":"PARTIAL_DEVELOPMENT_ARCHIVES","model":"NO_MODEL_TRAINING","performance":"NO_GO_DEV_ONLY",
        "execution_enabled":False,"selected":None,"no_continuous_account_claim":True})
