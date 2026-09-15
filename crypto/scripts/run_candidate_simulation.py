from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kquant_crypto.candidate_policy import DEFAULT_CONFIG, digest, load_policy, resolve_path
from kquant_crypto.candidate_dataset import freeze_dataset, load_dataset
from kquant_crypto.candidate_metrics import summarize, evaluate_gates
from kquant_crypto.candidate_simulation import CandidatePortfolio, replay
from kquant_crypto.candidate_simulation_store import CandidateStore


def write_json(path: Path, value, *, immutable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    data=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+"\n"
    if immutable:
        with path.open("x",encoding="utf-8") as f:
            f.write(data)
    else:
        temporary=path.with_suffix(path.suffix+".tmp")
        temporary.write_text(data,encoding="utf-8")
        temporary.replace(path)


def write_csv(path: Path, rows: list[dict]):
    fields=sorted({k for r in rows for k in r}) or ["no_records"]
    with path.open("w",newline="",encoding="utf-8-sig") as stream:
        writer=csv.DictWriter(stream,fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})


def frozen_rules(output: Path) -> dict:
    path=output/"exchange_rules.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["rules"]
    import httpx
    symbols=["BTCUSDT","ETHUSDT","SOLUSDT"]
    response=httpx.get("https://data-api.binance.vision/api/v3/exchangeInfo",params={"symbols":json.dumps(symbols,separators=(",",":"))},timeout=30)
    response.raise_for_status()
    raw=response.json()
    rules={}
    for item in raw["symbols"]:
        if item["symbol"] not in symbols or item["status"] != "TRADING" or not item.get("isSpotTradingAllowed",False):
            continue
        filters={f["filterType"]:f for f in item["filters"]}
        lot=filters["LOT_SIZE"]
        notional=filters.get("NOTIONAL",filters.get("MIN_NOTIONAL",{}))
        rules[item["symbol"]]={"step_size":lot["stepSize"],"min_qty":float(lot["minQty"]),"max_qty":float(lot["maxQty"]),
                                "min_notional":float(notional["minNotional"]),"tick_size":filters["PRICE_FILTER"]["tickSize"]}
    write_json(path,{"rules":rules,"content_hash":digest(raw),"received_at":datetime.now(UTC).isoformat(),
                     "historical_filter_status":"current_rules_proxy_not_historical_rules","raw":raw},immutable=True)
    return rules


def prepare(policy: dict) -> tuple[Path,dict,dict]:
    output=resolve_path(policy,"output_dir")
    path=output/"frozen/data_manifest.json"
    manifest=json.loads(path.read_text(encoding="utf-8")) if path.exists() else freeze_dataset(resolve_path(policy,"data_dir"),path.parent)
    baseline=output/"run_manifest.json"
    if not baseline.exists():
        head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
        source=ROOT/"docs/KQUANT_24H_Dual_Regime_Strategy_Plan_V2.0.md"
        write_json(baseline,{"t0":"2026-09-05T06:16:08Z","deadline":"2026-09-06T06:16:08Z","head":head,
                   "python":sys.executable,"source_plan_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
                   "data_manifest_hash":manifest["manifest_hash"],"order_submission":False},immutable=True)
    config=output/f"candidate_{policy['candidate']}_{policy['policy_hash'][:12]}_config.json"
    if not config.exists():
        write_json(config,policy,immutable=True)
    elif json.loads(config.read_text(encoding="utf-8")) != policy:
        raise ValueError("Frozen policy changed; register implementation correction before new run")
    return output,manifest,frozen_rules(output)


def report_run(store: CandidateStore,run_id: str,output: Path) -> dict:
    data=store.report_data(run_id)
    valid_equity=[r for r in data["equity"] if r.get("equity") is not None]
    summary=summarize(data["trades"],valid_equity)
    summary["unavailable_equity_observations"]=len(data["equity"])-len(valid_equity)
    summary["equity_complete"]=bool(valid_equity) and len(valid_equity)==len(data["equity"])
    meta=data["metadata"]
    summary["evidence_scope"]="candidate_simulation"
    summary["independent_evidence_status"]="PERFORMANCE_UNPROVEN"
    summary["historical_exposure"]=meta.get("exposure","unknown_treated_as_exposed")
    summary["data_manifest_hash"]=meta.get("data_manifest_hash")
    summary["policy_hash"]=meta.get("policy_hash")
    summary["engineering_status"]="PENDING_VERIFICATION"
    folder=output/run_id
    folder.mkdir(parents=True,exist_ok=True)
    previous_path=folder/"metrics.json"
    if previous_path.exists():
        previous=json.loads(previous_path.read_text(encoding="utf-8"))
        if "full_stress_expectancy_r" in previous:
            summary["full_stress_expectancy_r"]=previous["full_stress_expectancy_r"]
            summary["gates"]=evaluate_gates(summary,previous.get("gate_evidence",{}))
            summary["performance_status"]=summary["gates"]["status"]
            summary["gate_evidence"]=previous.get("gate_evidence",{})
    summary["run_id"]=run_id
    summary["execution_source"]=meta.get("command")
    summary["scenario"]="STRESS_2X_FULL_REPLAY" if meta.get("cost_multiplier")==2 else "BASE"
    summary["source_hashes"]=meta.get("source_hashes",{})
    summary["cost_and_timing_contract"]={"ohlcv_fee_bps":10,"ohlcv_execution_cost_bps":5,"quote_extra_slippage_bps":2,
                                          "history_entry":"next_bar_open","forward_entry":"first_valid_received_ask_after_signal"}
    write_json(folder/"metrics.json",summary)
    write_csv(folder/"trades.csv",data["trades"])
    write_csv(folder/"equity_curve.csv",data["equity"])
    write_csv(folder/"events.csv",data["events"])
    write_csv(folder/"metrics_by_mode_symbol.csv",[{"symbol":s,"mode":m,**row} for s,items in summary["by_symbol_mode"].items() for m,row in items.items()])
    lines=[f"# Candidate simulation: {run_id}","","Independent performance: PERFORMANCE_UNPROVEN. Historical dates treated as exposed.","",
           f"Trades: {summary['sample_count']}; payoff: {summary['payoff']}; net PF: {summary['profit_factor']}; mean net R: {summary['expectancy_r']}; drawdown: {summary['max_drawdown_pct']}%.","",
           "| Mode | Trades | Net payoff | Net PF | Mean R |","|---|---:|---:|---:|---:|"]
    for mode,row in summary["by_mode"].items():
        lines.append(f"| {mode} | {row['sample_count']} | {row['payoff']} | {row['profit_factor']} | {row['expectancy_r']} |")
    lines += ["","Full acceptance checks are in metrics.json. Current exchange filters are a historical proxy, not point-in-time exchange rules.",
              "Original validation, EVAL, Paper, Shadow and execution eligibility are unchanged."]
    (folder/"performance_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description="Isolated dual-regime candidate simulation; no exchange orders")
    parser.add_argument("command",choices=["freeze","replay","forward","status","stop","report","compare"])
    parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--candidate",choices=["A","B"])
    parser.add_argument("--run-id")
    parser.add_argument("--stress",action="store_true")
    parser.add_argument("--only-mode",choices=["UP_TREND","RANGE"])
    parser.add_argument("--stop-after-seconds",type=float,help="Bounded forward engineering smoke run")
    args=parser.parse_args(argv)
    policy=load_policy(args.config,args.candidate)
    output=resolve_path(policy,"output_dir")
    store=CandidateStore(resolve_path(policy,"database"))
    if args.command in {"status","stop","report"}:
        runs=store.list_runs()
        run_id=args.run_id or (runs[-1]["run_id"] if runs else None)
        if not run_id:
            print(json.dumps({"status":"not_started","order_submission":False})); return 0
        if args.command=="stop":
            store.request_stop(run_id); result={"run_id":run_id,"stop_requested":True}
        elif args.command=="report":
            result=report_run(store,run_id,output)
        else:
            entry=next(r for r in runs if r["run_id"]==run_id)
            state=entry["state"]
            result={"run_id":run_id,"status":entry["status"],"updated_at":entry["updated_at"],"stop_requested":entry["stop_requested"],
                    "state":{k:state.get(k) for k in ("cash","positions","pending","decisions","last_bars","forward","day_paused","pause_until")}}
        print(json.dumps(result,ensure_ascii=False,default=str)); return 0
    output,manifest,rules=prepare(policy)
    if args.command=="freeze":
        print(json.dumps({"manifest_hash":manifest["manifest_hash"],"window":manifest["window"],"rules":sorted(rules)})); return 0
    if args.command=="compare":
        compare(store,output,manifest); return 0
    run_id=args.run_id or f"{args.command}_{policy['candidate']}_{int(time.time())}"
    if not all(c.isalnum() or c in "_-" for c in run_id):
        raise ValueError("Invalid run ID")
    metadata={"strategy_version":policy["strategy_version"],"execution":"quotes" if args.command=="forward" else "ohlcv",
              "policy_hash":policy["policy_hash"],"config":policy,"data_manifest_hash":manifest["manifest_hash"],"candidate":policy["candidate"],
              "exposure":"development_exposed","command":args.command,"cost_multiplier":2 if args.stress else 1,"only_mode":args.only_mode,
              "rules_hash":digest(rules),"source_hashes":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/"kquant_crypto").glob("candidate*.py")}}
    metadata["source_hashes"]["strategy_dual_mode_v1.py"]=hashlib.sha256((ROOT/"kquant_crypto/strategy_dual_mode_v1.py").read_bytes()).hexdigest()
    metadata["source_hashes"]["run_candidate_simulation.py"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    selection_path=output/"candidate_selection.json"
    if args.command=="forward" and selection_path.exists():
        selected=json.loads(selection_path.read_text(encoding="utf-8"))
        if selected["selected"]!=policy["candidate"]:
            raise ValueError("Forward run must use the frozen selected candidate")
        metadata["selection_hash"]=digest(selected)
        metadata["exposure"]="post_selection_forward"
        metadata["acceptance_start_not_before"]=datetime.now(UTC).isoformat()
    existing=next((r for r in store.list_runs() if r["run_id"]==run_id),None)
    if args.command=="replay" and existing:
        raise ValueError("Run IDs are immutable; register a new run for an implementation correction")
    if not existing:
        store.create_run(run_id,metadata)
    elif existing["metadata"].get("policy_hash") != policy["policy_hash"]:
        raise ValueError("Run policy mismatch")
    if existing and any(existing["metadata"].get(k)!=metadata.get(k) for k in ("cost_multiplier","only_mode","rules_hash","source_hashes","data_manifest_hash")):
        raise ValueError("Resume implementation, scenario, rules or data hash mismatch")
    policy={**policy,"data_manifest_hash":manifest["manifest_hash"]}
    portfolio=CandidatePortfolio(policy,rules,execution="quotes" if args.command=="forward" else "ohlcv",cost_multiplier=2 if args.stress else 1,only_mode=args.only_mode)
    if args.command=="forward":
        from kquant_crypto.candidate_forward import run_forward
        asyncio.run(run_forward(portfolio,store,run_id,output/run_id,stop_after_seconds=args.stop_after_seconds))
    else:
        dataset=load_dataset(output/"frozen/data_manifest.json")
        window=manifest["window"]
        end=window["start"]+int(window["days"]*0.7)*86400
        prereg=output/"experiment_ledger.json"
        if not prereg.exists():
            write_json(prereg,{"registered_at":datetime.now(UTC).isoformat(),"candidates":["A","B"],"development_start":window["start"],
                              "development_end":end,"unopened_end":window["end"],"exposure":"unknown_treated_as_exposed",
                              "selection":"all_numeric_development_targets_then_max_worst_calendar_segment_PF_tie_A; both_fail_default_A_no_holdout",
                              "maximum_candidates":2,"ablations":["UP_TREND","RANGE"]},immutable=True)
        with store.process_lock(run_id,lease_seconds=3600):
            records=replay(portfolio,dataset,start=window["start"],end=end)
            records["equity"]=[r for r in records["equity"] if r["time"]>=window["start"]]
            state=portfolio.snapshot(); state["status"]="completed"
            store.save(run_id,state,**records)
        summary=report_run(store,run_id,output)
        print(json.dumps({"run_id":run_id,"sample_count":summary["sample_count"],"payoff":summary["payoff"],"profit_factor":summary["profit_factor"],"expectancy_r":summary["expectancy_r"],"output":str(output/run_id)}))
    return 0


def compare(store,output,manifest):
    selection=output/"candidate_selection.json"
    if selection.exists():
        print(selection.read_text(encoding="utf-8")); return
    runs=store.list_runs()
    summaries={}
    for candidate in ("A","B"):
        bases=[r for r in runs if r["metadata"].get("candidate")==candidate and r["metadata"].get("command")=="replay" and r["metadata"].get("cost_multiplier")==1 and not r["metadata"].get("only_mode") and r["status"]=="completed"]
        stress=[r for r in runs if r["metadata"].get("candidate")==candidate and r["metadata"].get("command")=="replay" and r["metadata"].get("cost_multiplier")==2 and not r["metadata"].get("only_mode") and r["status"]=="completed"]
        if not bases or not stress:
            raise ValueError("Both candidates need completed BASE and full STRESS development replays")
        base=report_run(store,bases[-1]["run_id"],output)
        stress_summary=report_run(store,stress[-1]["run_id"],output)
        continuous=all(not manifest["quality"][symbol][tf]["coverage"]["gaps"] for symbol in manifest["symbols"] for tf in ("5m","1h"))
        evidence={"policy_frozen":True,"unexposed_test":False,"data_continuous":continuous,"equity_complete":base["equity_complete"],"full_stress_expectancy_r":stress_summary["expectancy_r"]}
        gate=evaluate_gates(base,evidence)
        base["gates"]=gate
        base["gate_evidence"]=evidence
        base["performance_status"]=gate["status"]
        base["full_stress_expectancy_r"]=stress_summary["expectancy_r"]
        write_json(output/bases[-1]["run_id"]/"metrics.json",base)
        relevant=[v for k,v in gate["checks"].items() if k not in {"unexposed_test","bootstrap_stable","bootstrap_lower_95","sample_count"} and not k.endswith(".sample_count")]
        passed=all(v["status"]=="PASS" for v in relevant)
        data=store.report_data(bases[-1]["run_id"])
        start=manifest["window"]["start"]; end=start+int(manifest["window"]["days"]*0.7)*86400
        segments=[]
        for n in range(3):
            lo=start+(end-start)*n//3; hi=start+(end-start)*(n+1)//3
            rows=[t for t in data["trades"] if lo<=t["entry_time"]<hi]
            wins=sum(max(0,t["net_pnl"]) for t in rows); losses=-sum(min(0,t["net_pnl"]) for t in rows)
            segments.append(wins/losses if losses else None)
        summaries[candidate]={"run_id":bases[-1]["run_id"],"development_targets_pass":passed,"segment_pf":segments,"worst_segment_pf":min(x if x is not None else -1 for x in segments),"gates":gate}
    qualified=[c for c in ("A","B") if summaries[c]["development_targets_pass"]]
    selected=max(qualified,key=lambda c:(summaries[c]["worst_segment_pf"],c=="A")) if qualified else "A"
    result={"selected":selected,"reason":"development_gate_selection" if qualified else "both_failed_default_A_for_engineering_only","candidates":summaries,"holdout_opened":False,"performance_status":"PERFORMANCE_UNPROVEN","frozen_at":datetime.now(UTC).isoformat()}
    write_json(selection,result,immutable=True)
    print(json.dumps(result))


if __name__=="__main__":
    raise SystemExit(main())
