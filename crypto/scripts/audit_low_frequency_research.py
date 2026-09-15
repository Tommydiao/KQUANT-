"""Read-only source audits and isolated appendix for the low-frequency study."""
from pathlib import Path
import argparse
import csv
import gzip
import hashlib
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.low_frequency_research import CANDIDATES, SYMBOLS, DAY, STEP, load_contract, prepare_market, replay, recost, metrics
from run_low_frequency_research import write, csv_write


def attribution(out, c):
    source = ROOT / "outputs/trend_evidence_research/dev_run_20260913_01"
    result = {}
    for p in sorted(source.glob("h*_trades.csv")):
        with p.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        converted = []
        for row in rows:
            t = dict(row)
            for k in ("quantity", "entry_price", "exit_price", "entry_fee", "exit_fee", "net_pnl", "net_r", "risk_amount"):
                t[k] = float(t[k])
            for k in ("entry_time", "exit_time"): t[k] = int(t[k])
            t["entry_reference"] = t["entry_price"] / (1 + c["slippage_bps_side"] / 10000)
            t["exit_reference"] = t["exit_price"] / (1 - c["slippage_bps_side"] / 10000)
            t["label_status"] = "MATURE"
            t["fees"] = t["entry_fee"] + t["exit_fee"]
            converted.append(t)
        scenarios = {str(mult): recost(converted, c, mult) for mult in (0, 1, 2)}
        base = scenarios["1"]
        mismatch = max((abs(a["net_pnl"] - b["net_pnl"]) for a, b in zip(base, converted)), default=0)
        if mismatch > 1e-7: raise ValueError("Legacy base cost reconstruction mismatch")
        result[p.stem] = {"source_sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "base_pnl_reproduction_max_error": mismatch,
            "cost_scenarios": {mult: metrics(rows, []) for mult, rows in scenarios.items()},
            "by_exit_reason": {reason: {mult: metrics([t for t in rows if t["exit_reason"] == reason], []) for mult, rows in scenarios.items()}
                               for reason in sorted({t["exit_reason"] for t in converted})},
            "gross_reference_pnl": sum(t["net_pnl"] for t in scenarios["0"]),
            "fees": sum(t["fees"] for t in base),
            "slippage_cash_cost": sum(t["net_pnl"] for t in scenarios["0"]) - sum(t["net_pnl"] + t["fees"] for t in base),
            "scope": "FIXED_OLD_FILL_SEQUENCE_NO_NEW_SELECTION"}
    write(out / "legacy_loss_attribution.json", result)


def appendix(out, c):
    source = ROOT / "outputs/hybrid_delivery/multifactor_dataset_capsule_20260909_01"
    capsule = json.loads((source / "capsule.json").read_text())
    frames, hashes = {}, {}
    for s in SYMBOLS:
        info = capsule["files"][s]["5m"]
        p = source / info["path"]
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != info["sha256"]: raise ValueError("Authorized capsule hash mismatch")
        rows = json.loads(gzip.decompress(p.read_bytes()))
        if any(r["start"] + STEP > capsule["cutoff"] or r["available_at"] > capsule["cutoff"] for r in rows):
            raise ValueError("Restricted tail in capsule")
        frames[s] = pd.DataFrame(rows).set_index("start")[["open", "high", "low", "close"]]
        hashes[s] = actual
    market = prepare_market(frames, c)
    start = max(int(f.index.min()) for f in frames.values()) + (c["momentum_days"] + 1) * DAY
    start = (start + DAY - 1) // DAY * DAY
    end = capsule["cutoff"]
    signals = {t: p for t, p in market.signals.items() if start <= t < end - c["max_holding_days"] * DAY - STEP}
    report = {}
    for candidate in CANDIDATES:
        r = replay(market, c, candidate, start, end, signals=signals)
        csv_write(out / f"appendix_{candidate}_trades.csv.gz", r["trades"])
        csv_write(out / f"appendix_{candidate}_equity.csv.gz", r["equity"])
        report[candidate] = r["metrics"]
    write(out / "appendix_report.json", {"scope": "EXPOSED_APPENDIX_NOT_POOLED_OR_SELECTION", "start": start, "end": end,
          "hashes": hashes, "results": report})


def paired(out, c):
    with gzip.open(out / "paired_opportunity_exits.csv.gz", "rt") as f:
        rows = list(csv.DictReader(f))
    groups = {}
    for row in rows:
        groups.setdefault(row["opportunity_id"], {})[row["candidate_id"]] = row
    complete, excluded = [], []
    for key, pair in groups.items():
        if not all(k in pair and pair[k]["label_status"] == "MATURE" for k in CANDIDATES):
            excluded.append({"opportunity_id": key, "statuses": {k: v["label_status"] for k, v in pair.items()}})
            continue
        fixed, trail = pair[CANDIDATES[0]], pair[CANDIDATES[1]]
        complete.append({"opportunity_id": key, "symbol": fixed["symbol"], "entry_time": int(fixed["entry_time"]),
                         "fixed_r": float(fixed["net_r"]), "trail_r": float(trail["net_r"]),
                         "difference_r": float(trail["net_r"]) - float(fixed["net_r"])})
    csv_write(out / "matched_paired_exit_difference.csv.gz", complete)
    write(out / "paired_exit_difference.json", {"all_opportunities": len(groups), "matched_mature_pairs": len(complete),
        "excluded": excluded, "mean_difference_r": float(np.mean([p["difference_r"] for p in complete])) if complete else None,
        "by_symbol": {s: {"pairs": sum(p["symbol"] == s for p in complete),
                          "mean_difference_r": float(np.mean([p["difference_r"] for p in complete if p["symbol"] == s])) if any(p["symbol"] == s for p in complete) else None}
                      for s in SYMBOLS},
        "limitations": "Counterfactual paired comparison only; excludes unresolved pairs; not independent portfolio trades or admission evidence"})


def concentration(out, c):
    from run_low_frequency_research import load_market
    from kquant_crypto.low_frequency_research import stamp
    market = load_market(out, c)
    report = {}
    for candidate in CANDIDATES:
        trades = []
        for year in c["evaluation_years"]:
            with gzip.open(out / f"{candidate}_{year}_base_trades.csv.gz", "rt") as f:
                for r in csv.DictReader(f):
                    if r["label_status"] == "MATURE":
                        for k in ("net_pnl", "net_r", "fees"): r[k] = float(r[k])
                        for k in ("entry_time", "exit_time"): r[k] = int(r[k])
                        trades.append(r)
        totals = {s: sum(t["net_pnl"] for t in trades if t["symbol"] == s) for s in SYMBOLS}
        best = max(totals, key=totals.get)
        kept = []
        annual = {}
        for year in c["evaluation_years"]:
            start, end = stamp(f"{year}-01-01") + c["embargo_days"] * DAY, stamp(f"{year+1}-01-01")
            signals = {t:p for t,p in market.signals.items() if start <= t < end-c["max_holding_days"]*DAY-STEP}
            r = replay(market, c, candidate, start, end, signals=signals, excluded=(best,))
            kept += r["trades"]
            csv_write(out / f"global_leave_best_{candidate}_{year}_trades.csv.gz", r["trades"])
            annual[str(year)] = r["metrics"]
        largest = max(trades, key=lambda t:t["net_pnl"], default=None)
        report[candidate] = {"symbol_pnl": totals, "best_symbol": best, "leave_best_replay": metrics(kept, []), "annual": annual,
            "remove_largest_fixed_sequence": metrics([t for t in trades if t is not largest], []),
            "largest_trade_pnl": largest["net_pnl"] if largest else None,
            "selection_role": "ex_post_robustness_diagnostic_only"}
    write(out / "global_concentration.json", report)


def verify(out, c):
    with gzip.open(out / "paired_opportunity_exits.csv.gz", "rt") as f:
        pairs = {(r["candidate_id"], r["opportunity_id"]): r for r in csv.DictReader(f)}
    checked, errors = 0, []
    fee, slip = c["fee_bps_side"] / 10000, c["slippage_bps_side"] / 10000
    for candidate in CANDIDATES:
        for year in c["evaluation_years"]:
            with gzip.open(out / f"{candidate}_{year}_base_trades.csv.gz", "rt") as f:
                for t in csv.DictReader(f):
                    if t["label_status"] != "MATURE": continue
                    p = pairs[(candidate, t["opportunity_id"])]
                    if p["label_status"] != "MATURE" or int(p["exit_time"]) != int(t["exit_time"]) or abs(float(p["exit_reference"]) - float(t["exit_reference"])) > 1e-9:
                        errors.append({"id": t["opportunity_id"], "reason": "paired_portfolio_exit_mismatch"})
                    en, ex = float(t["entry_reference"])*(1+slip), float(t["exit_reference"])*(1-slip)
                    q = float(t["quantity"])
                    net = q*(ex-en-fee*(en+ex))
                    stop_fill = float(t["initial_stop"])*(1-slip)
                    risk = q*(en-stop_fill+fee*(en+stop_fill))
                    if abs(net-float(t["net_pnl"])) > 1e-7 or abs(risk-float(t["risk_amount"])) > 1e-7:
                        errors.append({"id": t["opportunity_id"], "reason": "money_reconstruction_mismatch"})
                    checked += 1
    write(out / "business_verification.json", {"checked_completed_trades": checked, "errors": errors,
          "status": "PASS" if not errors else "FAIL", "checks": ["independent_paired_path_vs_portfolio_exit", "net_cash_pnl", "BASE_initial_risk"]})
    if errors: raise ValueError(errors[:3])


def finalize(out, c):
    index = json.loads((out / "report_index.json").read_text())
    source = out / index["path"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != index["sha256"]: raise ValueError("Report changed")
    report = json.loads(source.read_text())
    concentration_report = json.loads((out / "global_concentration.json").read_text())
    for candidate, r in report["candidates"].items():
        item = concentration_report[candidate]
        r["concentration"] = item
        r["checks"]["leave_best_positive"] = item["leave_best_replay"]["mean_r"] is not None and item["leave_best_replay"]["mean_r"] > 0
        r["checks"]["remove_largest_positive"] = item["remove_largest_fixed_sequence"]["mean_r"] is not None and item["remove_largest_fixed_sequence"]["mean_r"] > 0
        r["research_gate_passed"] = all(r["checks"].values())
        r["failed_checks"] = [k for k, v in r["checks"].items() if not v]
    passed = [k for k,v in report["candidates"].items() if v["research_gate_passed"]]
    report["selected"] = max(passed, key=lambda k:(min(y["base"]["mean_r"] for y in report["candidates"][k]["annual"]), k=="LF_FIXED_V1")) if passed else None
    report["primary_report"] = index
    report["paired_comparison"] = json.loads((out / "paired_exit_difference.json").read_text())
    report["business_verification"] = json.loads((out / "business_verification.json").read_text())
    report["states"] = {"engineering": report["business_verification"]["status"],
        "data": "PARTIAL_HOLDING_PATH_GAPS", "model": "NOT_TRAINED_BY_DESIGN", "performance": "TARGET_NOT_MET_AND_INDEPENDENT_ADVANTAGE_UNPROVEN"}
    write(out / "delivery_summary.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["attribution", "appendix", "paired", "concentration", "verify", "finalize"])
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if Path(args.run_id).name != args.run_id: raise ValueError("Invalid run id")
    out = ROOT / "outputs/low_frequency_research" / args.run_id
    c = load_contract(out / "contract.json")
    {"attribution": attribution, "appendix": appendix, "paired": paired, "concentration": concentration,
     "verify": verify, "finalize": finalize}[args.command](out, c)
    print(args.command, "completed", flush=True)
