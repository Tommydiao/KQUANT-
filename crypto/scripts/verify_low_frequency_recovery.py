"""Independent artifact/accounting checks and unchanged-baseline replay."""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from kquant_crypto.low_frequency_research import CANDIDATES,SYMBOLS,DAY,STEP,stamp,load_contract,prepare_market,replay
from kquant_crypto.low_frequency_recovery import write


def rows(path):
    with gzip.open(path,"rt",encoding="utf-8",newline="") as f: return list(csv.DictReader(f))


def identity_audit(out, source):
    """Match economic opportunities, not float-sensitive content hashes across datasets."""
    result={}
    for candidate in CANDIDATES:
        old=[t for year in (2022,2023,2024) for t in rows(source/f"{candidate}_{year}_base_trades.csv.gz")]
        new=rows(out/f"{candidate}_all_base_trades.csv.gz")
        def key(t):return f"{t['symbol']}:{t['signal_time']}:{t['entry_time']}"
        before,after={key(t):t for t in old},{key(t):t for t in new}
        if len(after)!=len(new): raise ValueError("Duplicate economic opportunity")
        comparisons=[]
        for k in sorted(before.keys() & after.keys()):
            a,b=before[k],after[k]
            differences={}
            if a["label_status"]==b["label_status"]=="MATURE":
                for field in ("entry_reference","exit_reference","exit_time","quantity","net_pnl","net_r"):
                    delta=float(b[field])-float(a[field])
                    if abs(delta)>1e-8: differences[field]=delta
            comparisons.append({"economic_key":k,"old_id":a["opportunity_id"],"new_id":b["opportunity_id"],
                "old_status":a["label_status"],"new_status":b["label_status"],"numeric_differences_over_1e_8":differences})
        stops=Counter()
        for t in new:
            if t["label_status"]!="MATURE":continue
            if t["exit_reason"]=="stop":
                category="raised_trailing_stop" if float(t["stop"])>float(t["initial_stop"])+1e-10 else "initial_stop"
            else:category=t["exit_reason"]
            stops[category]+=1
        result[candidate]={"newly_admitted_economic_keys":sorted(after.keys()-before.keys()),
            "removed_economic_keys":sorted(before.keys()-after.keys()),"comparisons":comparisons,"exit_categories":dict(stops),
            "hash_only_differences":sum(x["old_id"]!=x["new_id"] and not x["numeric_differences_over_1e_8"] for x in comparisons),
            "resolved_censored":sum(x["old_status"]=="CENSORED" and x["new_status"]=="MATURE" for x in comparisons)}
    write(out/"identity_audit.json",{"match_contract":"candidate+symbol+signal_time+entry_time; separate content hashes retained",
        "reason":"Float-sensitive plan hashes can change under recomputation; do not count them as new opportunities.","candidates":result})


def verify(out, source):
    begin=time.monotonic()
    c=load_contract(out/"contract.json")
    original=prepare_market({s:pd.read_parquet(source/f"{s}_5m.parquet") for s in SYMBOLS},c)
    recovered=prepare_market({s:pd.read_parquet(out/f"{s}_5m.parquet") for s in SYMBOLS},c)
    changes=json.loads((out/"data_changes.json").read_text())
    halts=frozenset(tuple(p) for p in changes["confirmed_halts"])
    errors=[]; baseline_count=0; completed_count=0; diffs={}; affected={}
    for item in json.loads((out/"supplemental_sources.json").read_text()):
        if item["status"]=="VERIFIED" and hashlib.sha256((out/"archives"/item["file"]).read_bytes()).hexdigest()!=item["sha256"]:
            errors.append("supplemental_source_drift")
    for s,h in changes["manifest"].items():
        if hashlib.sha256((out/f"{s}_5m.parquet").read_bytes()).hexdigest()!=h: errors.append("recovered_data_drift")
    for candidate in CANDIDATES:
        old_trades=[]; new_trades=rows(out/f"{candidate}_all_base_trades.csv.gz")
        for year in c["evaluation_years"]:
            start,end=stamp(f"{year}-01-01")+c["embargo_days"]*DAY,stamp(f"{year+1}-01-01")
            signals={t:p for t,p in original.signals.items() if start<=t<end-c["max_holding_days"]*DAY-STEP}
            baseline=replay(original,c,candidate,start,end,signals=signals)
            saved=rows(source/f"{candidate}_{year}_base_trades.csv.gz")
            old_trades+=saved
            if len(saved)!=len(baseline["trades"]): errors.append(f"baseline_count:{candidate}:{year}")
            for old,new in zip(saved,baseline["trades"]):
                baseline_count+=1
                for key in ("opportunity_id","label_status","exit_reason"):
                    if old[key]!=new[key]: errors.append(f"baseline:{candidate}:{year}:{key}")
                if old["label_status"]=="MATURE":
                    for key in ("exit_time","entry_reference","exit_reference","net_pnl","net_r","risk_amount"):
                        if abs(float(old[key])-new[key])>1e-9: errors.append(f"baseline_numeric:{candidate}:{year}:{key}")
            affected[f"{candidate}:{year}"]={"baseline_events":dict(Counter(e["reason"] for e in baseline["events"])),
                "censored_positions":[{"opportunity_id":t["opportunity_id"],"symbol":t["symbol"],"entry_time":t["entry_time"]}
                                      for t in baseline["trades"] if t["label_status"]!="MATURE"]}
        old_index={t["opportunity_id"]:t for t in old_trades}
        new_index={t["opportunity_id"]:t for t in new_trades}
        if len(new_index)!=len(new_trades): errors.append("duplicate_opportunity")
        diffs[candidate]={"newly_admitted":sorted(set(new_index)-set(old_index)),"no_longer_admitted":sorted(set(old_index)-set(new_index)),
            "resolved_censored":[key for key in old_index.keys() & new_index.keys() if old_index[key]["label_status"]!="MATURE" and new_index[key]["label_status"]=="MATURE"],
            "changed_completed":[key for key in old_index.keys() & new_index.keys() if old_index[key]["label_status"]==new_index[key]["label_status"]=="MATURE"
                and (old_index[key]["exit_time"]!=new_index[key]["exit_time"] or abs(float(old_index[key]["net_pnl"])-float(new_index[key]["net_pnl"]))>1e-9)]}
        for t in new_trades:
            if t["label_status"]!="MATURE":continue
            s,entry,exit_at=t["symbol"],int(t["entry_time"]),int(t["exit_time"])
            plan=next(p for p in recovered.signals[entry] if p["symbol"]==s)
            single=replay(recovered,c,candidate,entry,exit_at+STEP,signals={entry:[plan]},independent=True,confirmed_halts=halts)
            match=single["trades"][0]
            for key in ("exit_time","exit_reference","net_r","base_r_per_unit"):
                if abs(float(t[key])-match[key])>1e-8:errors.append(f"path:{t['opportunity_id']}:{key}")
            q,en,ex=float(t["quantity"]),float(t["entry_price"]),float(t["exit_price"])
            pnl=q*(ex-en)-float(t["fees"])
            if abs(pnl-float(t["net_pnl"]))>1e-8 or abs(pnl/float(t["risk_amount"])-float(t["net_r"]))>1e-8:
                errors.append("accounting_identity")
            if (s,entry) in halts: errors.append("halt_fill")
            completed_count+=1
        print(candidate,"verified",len(new_trades),flush=True)
    snapshot=out/"verified_source_snapshot"
    snapshot.mkdir(exist_ok=False)
    paths=[Path(__file__),ROOT/"scripts/run_low_frequency_recovery.py",ROOT/"scripts/run_low_frequency_research.py",
           ROOT/"kquant_crypto/low_frequency_recovery.py",ROOT/"kquant_crypto/low_frequency_research.py"]
    for p in paths: shutil.copy2(p,snapshot/p.name)
    write(out/"business_verification.json",{"status":"PASS" if not errors else "FAIL","errors":errors,
        "baseline_rows_reproduced":baseline_count,"recovered_completed_paths_checked":completed_count,"differences":diffs,
        "baseline_gap_impact":affected,"elapsed_seconds":time.monotonic()-begin,
        "source_hashes":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})
    if errors: raise ValueError(errors[:10])


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--run-id",required=True);p.add_argument("--identity-only",action="store_true")
    a=p.parse_args()
    if Path(a.run_id).name!=a.run_id:raise ValueError("invalid run")
    out=ROOT/"outputs/low_frequency_recovery"/a.run_id
    source=Path(json.loads((out/"preregistration.json").read_text())["source_run"])
    (identity_audit if a.identity_only else verify)(out,source)
