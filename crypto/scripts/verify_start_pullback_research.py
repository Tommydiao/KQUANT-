"""Independent raw-bar arithmetic/path checks, not another strategy selection run."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd

from run_start_pullback_research import (read, phase_path, load_primary_trades, baseline_check, write, sha)

HOUR, FOUR, STEP, DAY = 3600, 14400, 300, 86400


def verify(out):
    c = read(out / "contract.json")
    dataset, replay_dir = phase_path(out, "build"), phase_path(out, "replay")
    results = read(replay_dir / "results.json")
    frames = {s: pd.read_parquet(dataset / f"{s}_5m.parquet") for s in c["symbols"]}
    halts = set(tuple(x) for x in read(dataset / "manifest.json")["confirmed_halts"])
    episodes = {e["episode_id"]: e for e in read(replay_dir / "episodes.json")}
    hours, fours = {}, {}
    for s, f in frames.items():
        h = f.groupby(f.index // HOUR).agg(close=("close", "last"), n=("close", "count"))
        h.index = (h.index + 1) * HOUR
        h = h.reindex(np.arange(h.index.min(), h.index.max()+HOUR, HOUR))
        h.loc[h.n != 12, "close"] = np.nan
        lr = np.log(h.close)
        h["sigma"] = lr.diff().rolling(168).std(ddof=0)*math.sqrt(24)
        h["ret"] = (lr-lr.shift(48)).where(lr.rolling(49).count() == 49)
        hours[s] = h
        four = f.groupby(f.index // FOUR).agg(close=("close", "last"), n=("close", "count"))
        four.index = (four.index + 1)*FOUR
        fours[s] = four[four.n == 48].close.to_dict()
    errors, totals = [], {}

    def block(s, at):
        rows = []
        for symbol in (s, "BTCUSDT"):
            row = hours[symbol].loc[at] if at in hours[symbol].index else None
            if row is None or not np.isfinite([row.sigma, row.ret]).all() or row.sigma <= 0:
                return None
            rows.append(row)
        return bool(any(row.ret < -row.sigma for row in rows))

    def subset(s, start, end):
        return frames[s].reindex(np.arange(start, end, STEP))

    for candidate in c["candidates"]:
        trades = load_primary_trades(replay_dir, candidate)
        cash_pnl, risk_values = [], []
        checked = 0
        for t in trades:
            s, at = t["symbol"], int(t["confirmation_time"])
            failures = []
            h = subset(s, at-HOUR, at)
            ep = episodes[t["episode_id"]]
            b = int(ep["bar_start"])
            prior = subset(s, b-12*FOUR, b)
            u, low = prior.high.max(), prior.low.min()
            if prior.close.isna().any() or not np.isclose(u, t["upper"]) or not np.isclose(low, t["lower"]):
                failures.append("frozen_box")
            prior61 = subset(s, b-61*FOUR, b)
            priorcloses = prior61.close.to_numpy()[47::48]
            returns = np.diff(np.log(priorcloses))
            if len(returns) != 60 or not np.isfinite(returns).all() or np.std(returns[-12:]) > np.std(returns):
                failures.append("compression")
            setup = subset(s, b, b+FOUR)
            priorq = subset(s, b-20*FOUR, b).quote_volume.to_numpy().reshape(20, 48).sum(axis=1)
            if setup.close.iloc[-1] <= u or setup.quote_volume.sum() <= np.median(priorq):
                failures.append("breakout")
            qm = subset(s, at-21*HOUR, at-HOUR).quote_volume.to_numpy().reshape(20, 12).sum(axis=1)
            if h.quote_volume.sum() <= np.median(qm) or h.taker_buy_quote_volume.sum() <= h.quote_volume.sum()/2:
                failures.append("confirmation_flow")
            if h.close.iloc[-1] <= u or (candidate == "START_V1" and h.close.iloc[-1] <= h.open.iloc[0]):
                failures.append("confirmation_price")
            if candidate == "PULLBACK_V1":
                reclaim = subset(s, int(t["setup_time"])-FOUR, int(t["setup_time"]))
                if not (reclaim.low.min() <= u and reclaim.close.iloc[-1] >= u and reclaim.low.min() > low
                        and h.close.iloc[-1] > reclaim.close.iloc[-1] and h.low.min() >= reclaim.low.min()):
                    failures.append("pullback_confirmation")
            sigma = hours[s].loc[at, "sigma"]
            if not np.isclose(sigma, t["sigma"]) or math.log(h.close.iloc[-1]/u) > sigma or block(s, at) is not False:
                failures.append("market_or_extension")
            if int(t["entry_time"]) != at + STEP or int(t["setup_time"]) + HOUR != at:
                failures.append("time_contract")
            stop = float(t["initial_stop"])
            distance = t["reference"] - stop
            observed = None
            # Reconstruct first executable exit without consulting the recorded outcome.
            for tm in range(int(t["entry_time"]), min(int(t["entry_time"])+30*DAY+STEP, int(frames[s].index.max())+STEP), STEP):
                if (s, tm) in halts:
                    continue
                if tm not in frames[s].index:
                    observed = (None, None, "CENSORED")
                    break
                row = frames[s].loc[tm]
                if row.open <= stop:
                    observed = (tm, float(row.open), "gap_stop")
                elif tm >= t["entry_time"]+30*DAY:
                    observed = (tm, float(row.open), "time_exit")
                elif tm % FOUR == STEP and block(s, tm-STEP) is True:
                    observed = (tm, float(row.open), "regime_exit")
                elif row.low <= stop:
                    observed = (tm+STEP, stop, "stop")
                if observed is not None:
                    break
                end = tm+STEP
                if end in fours[s] and end-FOUR >= t["entry_time"]:
                    stop = max(stop, float(fours[s][end])-distance)
            if t["label_status"] == "MATURE":
                if observed is None or observed[2] != t["exit_reason"] or observed[0] != int(t["exit_time"]) or not np.isclose(observed[1], t["exit_reference"], rtol=1e-10):
                    failures.append("first_exit_path")
                q, en, ex = t["quantity"], t["entry_reference"]*1.0005, t["exit_reference"]*.9995
                fees = (en+ex)*q*.001
                net = q*(ex-en)-fees
                denominator = q*(en-t["initial_stop"]*.9995+.001*(en+t["initial_stop"]*.9995))
                if not np.isclose(net, t["net_pnl"], atol=1e-8) or not np.isclose(net/denominator, t["net_r"], atol=1e-8):
                    failures.append("net_money_or_R")
                cash_pnl.append(net); risk_values.append(net/denominator)
            if failures:
                errors.append({"opportunity_id": t["opportunity_id"], "failures": failures, "reconstructed_exit": observed})
            checked += 1
        wins = [v for v in cash_pnl if v > 0]
        losses = [v for v in cash_pnl if v < 0]
        summary = {"checked": checked, "net_pnl": sum(cash_pnl),
                   "win_rate": len(wins)/len(cash_pnl) if cash_pnl else None,
                   "pf": sum(wins)/-sum(losses) if losses else None,
                   "payoff": (sum(wins)/len(wins))/(-sum(losses)/len(losses)) if wins and losses else None,
                   "mean_r": sum(risk_values)/len(risk_values) if risk_values else None}
        for k in ("net_pnl", "win_rate", "pf", "payoff", "mean_r"):
            expected = results["candidates"][candidate]["base"]["metrics"][k]
            if expected is not None and not np.isclose(expected, summary[k], atol=1e-8):
                errors.append({"candidate": candidate, "aggregate_mismatch": k})
        totals[candidate] = summary
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "candidates": totals,
        "scope": "all_primary_fills_raw_entry_and_independent_exit_path_arithmetic; not_proof_of_alpha",
        "baseline_guard": baseline_check(out), "verification_source_hash": sha(Path(__file__))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--compare-run")
    parser.add_argument("--regression", action="store_true")
    args = parser.parse_args()
    if Path(args.run_id).name != args.run_id or args.run_id in (".", ".."):
        raise ValueError("invalid run")
    out = ROOT / "outputs/start_pullback_research" / args.run_id
    started = time.monotonic()
    result = verify(out)
    attempt = len(list(out.glob("independent_verification_*.json")))+1
    if args.compare_run:
        if Path(args.compare_run).name != args.compare_run or args.compare_run in (".", ".."):
            raise ValueError("invalid comparison run")
        other = ROOT / "outputs/start_pullback_research" / args.compare_run
        if read(out / "contract.json") != read(other / "contract.json"):
            raise ValueError("Comparison policy changed")
        current_dir, prior_dir = phase_path(out, "replay"), phase_path(other, "replay")
        same = sha(current_dir / "results.json") == sha(prior_dir / "results.json")
        fields = ["opportunity_id", "entry_time", "entry_price", "quantity", "initial_stop", "stop", "exit_time",
                  "exit_reference", "exit_reason", "net_pnl", "net_r", "risk_amount", "label_status"]
        for candidate in ("START_V1", "PULLBACK_V1"):
            a = pd.DataFrame(load_primary_trades(current_dir, candidate))
            b = pd.DataFrame(load_primary_trades(prior_dir, candidate))
            if not a.empty or not b.empty:
                same &= a[fields].equals(b[fields])
        equity_files = sorted(current_dir.glob("*_equity.csv.gz"))
        for path in equity_files:
            same &= pd.read_csv(path).equals(pd.read_csv(prior_dir / path.name))
        result["reproducibility"] = {"same_policy_and_results": bool(same), "compared_run": args.compare_run,
            "compared_equity_files": len(equity_files), "results_sha256": sha(current_dir / "results.json"),
            "scope": "all_primary_fill_financial_fields_and_all_replay_equity_points; metadata_additions_not_ignored_in_policy"}
        if not same:
            result["errors"].append({"reproducibility": "mismatch"})
    if args.regression:
        junit = out / f"regression_{attempt:03d}.xml"
        command = [sys.executable, "-m", "pytest", "-q", "tests/test_start_pullback_research.py",
            "tests/test_low_frequency_research.py", "tests/test_low_frequency_recovery.py",
            "tests/test_hybrid_execution_boundary_v12.py", "--junitxml=" + str(junit)]
        before = time.monotonic()
        test = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        log = out / f"regression_{attempt:03d}.log"
        with log.open("x", encoding="utf-8") as f: f.write(test.stdout + test.stderr)
        result["regression"] = {"command": command, "exit_code": test.returncode,
            "elapsed_seconds": time.monotonic()-before, "junit": str(junit), "log": str(log)}
        print(test.stdout, flush=True)
        if test.returncode:
            result["errors"].append({"regression": "failed"})
    diff = subprocess.run(["git", "diff", "--check"], cwd=ROOT, text=True, capture_output=True)
    result["git_diff_check"] = {"exit_code": diff.returncode, "output": diff.stdout+diff.stderr}
    if diff.returncode:
        result["errors"].append({"git_diff_check": "failed"})
    result["elapsed_seconds"] = time.monotonic()-started
    result["status"] = "PASS" if not result["errors"] else "FAIL"
    write(out / f"independent_verification_{attempt:03d}.json", result)
    print(json.dumps(result, indent=2, allow_nan=False))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__": main()
