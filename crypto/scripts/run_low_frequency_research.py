"""Immutable CLI for two registered low-frequency spot research candidates."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from kquant_crypto.low_frequency_research import (
    CANDIDATES, SYMBOLS, DAY, STEP, digest, stamp, load_contract, prepare_market,
    replay, metrics, recost, centered_block_test, protection, next_trailing_stop,
)


def write(path, value):
    serialized = json.dumps(value, indent=2, sort_keys=True, allow_nan=False)
    with path.open("x", encoding="utf-8") as f:
        f.write(serialized)


def csv_write(path, rows):
    keys = sorted({k for r in rows for k in r})
    with gzip.open(path, "xt", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def acquire(out, c):
    archives = out / "archives"
    archives.mkdir(exist_ok=True)
    def fetch(symbol, year, month):
        name = f"{symbol}-5m-{year}-{month:02d}.zip"
        target = archives / name
        url = f"https://data.binance.vision/data/spot/monthly/klines/{symbol}/5m/{name}"
        checksum = target.with_suffix(".zip.CHECKSUM")
        for attempt in range(3):
            try:
                if not checksum.exists():
                    with urlopen(url + ".CHECKSUM", timeout=30) as response:
                        content = response.read()
                    checksum.write_bytes(content)
                expected = checksum.read_text().split()[0]
                if not target.exists():
                    with urlopen(url, timeout=60) as response:
                        content = response.read()
                    if hashlib.sha256(content).hexdigest() != expected:
                        raise ValueError("Official checksum mismatch")
                    target.write_bytes(content)
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                if actual != expected:
                    raise ValueError("Cached checksum mismatch; quarantine, do not overwrite")
                return {"symbol": symbol, "year": year, "month": month, "file": name,
                        "sha256": actual, "url": url, "verified_at": datetime.now(timezone.utc).isoformat(),
                        "bytes": target.stat().st_size}
            except Exception:
                if attempt == 2: raise
                time.sleep(1 + attempt)
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = [pool.submit(fetch, s, y, m) for s in SYMBOLS for y in range(2021, 2025) for m in range(1, 13)]
        for future in as_completed(pending):
            results.append(future.result())
            if len(results) % 12 == 0: print(f"verified archives {len(results)}/144", flush=True)
    write(out / "archive_manifest.json", sorted(results, key=lambda x: x["file"]))


def build(out, c):
    sources = json.loads((out / "archive_manifest.json").read_text())
    result = {}
    for symbol in SYMBOLS:
        parts = []
        excluded = []
        for src in sources:
            if src["symbol"] != symbol: continue
            path = out / "archives" / src["file"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != src["sha256"]:
                raise ValueError("Source changed")
            with zipfile.ZipFile(path) as archive:
                with archive.open(archive.namelist()[0]) as stream:
                    df = pd.read_csv(stream, header=None)
            times = df[0].astype("int64").to_numpy()
            if np.any(times >= 10**14): raise ValueError("Unexpected timestamp units in 2021-2024 data")
            if np.any(times % 300000): raise ValueError("Unaligned source")
            frame = pd.DataFrame({"open": df[1].astype(float).to_numpy(), "high": df[2].astype(float).to_numpy(),
                                  "low": df[3].astype(float).to_numpy(), "close": df[4].astype(float).to_numpy(),
                                  "volume": df[5].astype(float).to_numpy()}, index=times // 1000)
            if not np.isfinite(frame.to_numpy()).all() or (frame[["open", "high", "low", "close"]] <= 0).any().any():
                raise ValueError("Invalid numeric OHLCV")
            if (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (frame.low > frame[["open", "close", "high"]].min(axis=1)).any():
                raise ValueError("Invalid OHLC geometry")
            close_times = df[6].astype("int64").to_numpy()
            invalid_close = close_times != times + 299999
            excluded.extend({"source": src["file"], "open_time_ms": int(t), "close_time_ms": int(cl),
                             "reason": "nonstandard_close_time_not_a_complete_5m_bar"}
                            for t, cl in zip(times[invalid_close], close_times[invalid_close]))
            frame = frame.loc[~invalid_close]
            parts.append(frame)
        joined = pd.concat(parts).sort_index()
        if not joined.index.is_unique: raise ValueError("Duplicate timestamp")
        start, end = stamp(c["data_start"]), stamp(c["data_end_exclusive"])
        if joined.index.min() < start or joined.index.max() >= end: raise ValueError("Out-of-authority data")
        missing = np.setdiff1d(np.arange(start, end, STEP), joined.index.to_numpy())
        path = out / f"{symbol}_5m.parquet"
        if path.exists(): raise FileExistsError(path)
        joined.to_parquet(path)
        result[symbol] = {"rows": len(joined), "missing_bars": len(missing), "missing_timestamps": missing.tolist(),
                          "excluded_rows": excluded,
                          "start": int(joined.index.min()), "end_exclusive": int(joined.index.max()) + STEP,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    write(out / "dataset_manifest.json", {"symbols": result, "hash": digest(result), "scope": c["exposure"],
          "source": "Binance official monthly archives with individual SHA256",
          "available_at": "historical_candle_close_proxy", "actual_receipt": "archive_manifest.verified_at",
          "independent_oos": False})


def load_market(out, c):
    manifest = json.loads((out / "dataset_manifest.json").read_text())
    frames = {}
    for symbol in SYMBOLS:
        path = out / f"{symbol}_5m.parquet"
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["symbols"][symbol]["sha256"]:
            raise ValueError("Dataset drift")
        frames[symbol] = pd.read_parquet(path)
    return prepare_market(frames, c)


def paired_labels(market, c, signals):
    """Each opportunity gets two independent one-unit paths, never portfolio trades."""
    output = []
    fee, slip = c["fee_bps_side"] / 10000, c["slippage_bps_side"] / 10000
    for t, plans in signals.items():
        for plan in plans:
            s = plan["symbol"]
            frame = market.frames[s]
            for candidate in CANDIDATES:
                base = {**plan, "candidate_id": candidate, "scope": "COUNTERFACTUAL_PAIRED_NOT_INDEPENDENT_TRADES"}
                if t not in frame.index:
                    output.append({**base, "label_status": "NOT_FILLED", "reason": "missing_entry"}); continue
                ref = float(frame.loc[t, "open"])
                if not plan["stop"] < ref < plan["target"]:
                    output.append({**base, "label_status": "NOT_FILLED", "reason": "outside_plan"}); continue
                en = ref * (1 + slip)
                stop_fill = plan["stop"] * (1 - slip)
                risk = en - stop_fill + fee * (en + stop_fill)
                p = {**plan, "initial_distance": plan["reference"] - plan["stop"]}
                end = t + c["max_holding_days"] * DAY
                path = frame.reindex(np.arange(t, end + STEP, STEP))
                reason, exit_ref, at = "path_gap", None, None
                for at0, row in path.iterrows():
                    at = int(at0)
                    if not np.isfinite(row.open): break
                    b = (row.open, row.high, row.low, row.close)
                    hit = protection(p, (b[0], b[0], b[0], b[0]), candidate)
                    if hit: exit_ref, reason, _ = hit; break
                    if at >= end: exit_ref, reason = float(row.open), "time_exit"; break
                    if market.regimes.get((s, at)) is False: exit_ref, reason = float(row.open), "regime_exit"; break
                    hit = protection(p, b, candidate)
                    if hit:
                        exit_ref, reason, opening = hit
                        at += 0 if opening else STEP
                        break
                    four_start = at + STEP - 14400
                    if candidate == "LF_TRAIL_V1" and four_start >= t and four_start in market.four[s].index:
                        p["stop"] = next_trailing_stop(p, float(market.four[s].loc[four_start, "close"]))
                if exit_ref is None:
                    output.append({**base, "label_status": "CENSORED", "reason": reason}); continue
                ex = exit_ref * (1 - slip)
                net = ex - en - fee * (en + ex)
                output.append({**base, "label_status": "MATURE", "reason": reason, "exit_time": at,
                               "entry_reference": ref, "exit_reference": exit_ref, "base_r_per_unit": risk,
                               "net_r": net / risk})
    return output


def benchmark(market, c, start, end):
    curve = np.full((end - start) // STEP, 0.0)
    fee, slip = c["fee_bps_side"] / 10000, c["slippage_bps_side"] / 10000
    unknown = False
    for s in SYMBOLS:
        f = market.frames[s].reindex(np.arange(start, end, STEP))
        if not np.isfinite(f.open.iloc[0]): return {"status": "MISSING_ENTRY"}
        unknown |= bool(f.close.isna().any())
        q = c["capital"] / 3 / (float(f.open.iloc[0]) * (1 + slip) * (1 + fee))
        curve += q * f.close.ffill().to_numpy() * (1 - slip) * (1 - fee)
    eq = np.r_[c["capital"], curve]
    return {"capital_return": float(eq[-1] / eq[0] - 1),
            "max_drawdown": float(np.max(1 - eq / np.maximum.accumulate(eq))),
            "equity_has_missing_marks": unknown, "cash_return": 0.0}


def run_replays(out, c):
    market = load_market(out, c)
    train_end = stamp("2022-01-01") - c["purge_days"] * DAY
    rates = {}
    for s in SYMBOLS:
        eligible = [(ss, t) for ss, t in market.plan_rows if ss == s and t < train_end and market.regimes[(ss, t)] is True]
        numerator = sum(p["symbol"] == s for t, plans in market.signals.items() if t < train_end for p in plans)
        rates[s] = {"opportunities": numerator, "eligible_days": len(eligible), "rate": numerator / len(eligible) if eligible else 0}
    write(out / "random_frequency_freeze.json", {"training_end_exclusive": train_end, "rates": rates, "seed": c["seed"]})
    report, all_pair_signals = {}, {}
    for candidate in CANDIDATES:
        annual = []
        for year in c["evaluation_years"]:
            start = stamp(f"{year}-01-01") + c["embargo_days"] * DAY
            end = stamp(f"{year + 1}-01-01")
            entry_end = end - c["max_holding_days"] * DAY - STEP
            signals = {t: p for t, p in market.signals.items() if start <= t < entry_end}
            all_pair_signals.update(signals)
            rng = np.random.default_rng(c["seed"] + year)
            random_signals = {}
            for (s, t), p in sorted(market.plan_rows.items(), key=lambda x: (x[0][1], x[0][0])):
                if start <= t < entry_end and market.regimes[(s, t)] is True and rng.random() < rates[s]["rate"]:
                    random_signals.setdefault(t, []).append(p)
            scenarios = {}
            for name, mult, sig in (("base", 1, signals), ("stress", 2, signals), ("random", 1, random_signals)):
                result = replay(market, c, candidate, start, end, mult, sig)
                prefix = f"{candidate}_{year}_{name}"
                csv_write(out / f"{prefix}_trades.csv.gz", result["trades"])
                csv_write(out / f"{prefix}_equity.csv.gz", result["equity"])
                csv_write(out / f"{prefix}_events.csv.gz", result["events"])
                scenarios[name] = result
            base = scenarios["base"]
            fixed_stress = recost(base["trades"], c, 2)
            zero = recost(base["trades"], c, 0)
            csv_write(out / f"{candidate}_{year}_fixed_double_cost.csv.gz", fixed_stress)
            sums = {s: sum(t["net_pnl"] for t in base["trades"] if t["symbol"] == s and t["label_status"] == "MATURE") for s in SYMBOLS}
            best = max(sums, key=sums.get)
            leave = replay(market, c, candidate, start, end, signals=signals, excluded=(best,))
            mature = [t for t in base["trades"] if t["label_status"] == "MATURE"]
            largest = max(mature, key=lambda t: t["net_pnl"], default=None)
            annual.append({"year": year, "start": start, "end": end, "entry_end_exclusive": entry_end,
                "base": base["metrics"], "stress": scenarios["stress"]["metrics"], "random": scenarios["random"]["metrics"],
                "fixed_double_cost": metrics(fixed_stress, []), "zero_cost_fixed_fills": metrics(zero, []),
                "by_symbol": {s: metrics([t for t in mature if t["symbol"] == s], []) for s in SYMBOLS},
                "leave_best_symbol": {"excluded": best, "metrics": leave["metrics"]},
                "remove_largest_trade": metrics([t for t in mature if t is not largest], []),
                "uncertainty": centered_block_test(base["trades"], start, end, c),
                "benchmark": benchmark(market, c, start, end),
                "data_uncertain": any(v["uncertain"] for v in scenarios.values())})
            print(candidate, year, "base", base["metrics"], flush=True)
        report[candidate] = annual
    pairs = paired_labels(market, c, all_pair_signals)
    csv_write(out / "paired_opportunity_exits.csv.gz", pairs)
    write(out / "annual_reports.json", report)
    write(out / "paired_summary.json", {candidate: {"count": sum(p["candidate_id"] == candidate for p in pairs),
        "mature": sum(p["candidate_id"] == candidate and p["label_status"] == "MATURE" for p in pairs),
        "mean_r": float(np.mean([p["net_r"] for p in pairs if p["candidate_id"] == candidate and p["label_status"] == "MATURE"]))}
        for candidate in CANDIDATES})


def summarize(out, c):
    annual = json.loads((out / "annual_reports.json").read_text())
    result, tests = {}, {}
    for candidate, years in annual.items():
        trades, stress, full_stress, curve = [], [], [], []
        carry = c["capital"]
        for year in years:
            y = year["year"]
            with gzip.open(out / f"{candidate}_{y}_base_trades.csv.gz", "rt") as f:
                rows = list(csv.DictReader(f))
            for t in rows:
                for key in ("net_pnl", "net_r", "fees", "quantity", "risk_amount", "base_r_per_unit", "entry_reference", "exit_reference"):
                    t[key] = float(t[key]) if t.get(key) else None
                for key in ("entry_time", "exit_time"): t[key] = int(t[key])
            trades += rows
            stress += recost(rows, c, 2)
            with gzip.open(out / f"{candidate}_{y}_stress_trades.csv.gz", "rt") as f:
                stressed = list(csv.DictReader(f))
            for t in stressed:
                for key in ("net_pnl", "net_r", "fees"):
                    t[key] = float(t[key]) if t.get(key) else None
                for key in ("entry_time", "exit_time"): t[key] = int(t[key])
            full_stress += stressed
            with gzip.open(out / f"{candidate}_{y}_base_equity.csv.gz", "rt") as f:
                eq = list(csv.DictReader(f))
            # Chain annual NAV returns without pretending annual accounts were continuously sized.
            curve.extend({"time": int(p["time"]), "equity": carry * float(p["equity"]) / c["capital"]} for p in eq)
            carry = curve[-1]["equity"]
        combined = metrics(trades, curve)
        combined["metrics_scope"] = "completed_trades_only_censored_outcomes_not_assumed"
        if combined["censored"]:
            combined["indicative_capital_return"] = combined["capital_return"]
            combined["indicative_max_drawdown"] = combined["max_drawdown"]
            combined["capital_return"] = combined["max_drawdown"] = None
        for y in years:
            for name in ("base", "stress", "random"):
                if y[name]["censored"]:
                    y[name]["indicative_capital_return"] = y[name]["capital_return"]
                    y[name]["indicative_max_drawdown"] = y[name]["max_drawdown"]
                    y[name]["capital_return"] = y[name]["max_drawdown"] = None
        uncertainty = centered_block_test(trades, stamp("2022-01-01"), stamp("2025-01-01"), c)
        tests[candidate] = uncertainty["p_value"]
        target = c["targets"]
        def at_least(value, minimum): return value is not None and value >= minimum
        checks = {"pf": at_least(combined["pf"], target["pf"]), "payoff": at_least(combined["payoff"], target["payoff"]),
            "mean_r": at_least(combined["mean_r"], 1e-15),
            "fixed_stress_pf": at_least(metrics(stress, [])["pf"], target["stress_pf"]),
            "full_stress_positive": at_least(metrics(full_stress, [])["mean_r"], 1e-15),
            "max_drawdown": combined["max_drawdown"] is not None and combined["max_drawdown"] <= target["max_drawdown"],
            "samples": combined["trades"] >= target["trades"],
            "per_symbol": all(sum(y["by_symbol"][s]["trades"] for y in years) >= target["per_symbol"] for s in SYMBOLS),
            "no_censored": combined["censored"] == 0 and not any(y["data_uncertain"] for y in years),
            "leave_best_positive": all(at_least(y["leave_best_symbol"]["metrics"]["mean_r"], 1e-15) for y in years),
            "remove_largest_positive": all(at_least(y["remove_largest_trade"]["mean_r"], 1e-15) for y in years),
            "legacy_10r_resolved": c["legacy_10r_resolved"]}
        result[candidate] = {"combined": combined, "fixed_double_cost": metrics(stress, []), "full_stress": metrics(full_stress, []), "uncertainty": uncertainty,
            "checks": checks, "annual": years, "accounting": "annual capital reset; linked NAV drawdown; pooled monetary trade metrics",
            "independent_oos": False}
    running = 0
    for rank, candidate in enumerate(sorted(tests, key=lambda k: tests[k] if tests[k] is not None else 1)):
        running = max(running, min(1, (2 - rank) * (tests[candidate] if tests[candidate] is not None else 1)))
        result[candidate]["holm_p"] = running
        result[candidate]["checks"]["holm_significance"] = running <= c["targets"]["alpha"]
        result[candidate]["research_gate_passed"] = all(result[candidate]["checks"].values())
    report_path = out / "report_final.json"
    if report_path.exists():
        # Preserve a failed serialization attempt; never overwrite prior evidence.
        report_path = out / "report_final_v2.json"
    write(report_path, {"scope": "DEV_ONLY", "candidates": result, "performance": "PERFORMANCE_UNPROVEN",
        "execution_enabled": False, "selected": None, "policy_hash": digest(c)})
    write(out / "report_index.json", {"path": report_path.name, "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest()})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze", "acquire", "build", "replay", "report", "all",
        "recovery-freeze", "recovery-acquire", "recovery-audit", "recovery-replay", "recovery-report",
        "start-freeze", "start-build", "start-replay", "start-controls", "start-report", "start-all", "start-status"])
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if Path(args.run_id).name != args.run_id: raise ValueError("run-id must be a name")
    if args.command.startswith("start-"):
        subprocess.run([sys.executable, str(ROOT / "scripts/run_start_pullback_research.py"),
                        args.command.removeprefix("start-"), "--run-id", args.run_id], check=True)
        return
    if args.command.startswith("recovery-"):
        subprocess.run([sys.executable, str(ROOT / "scripts/run_low_frequency_recovery.py"),
                        args.command.removeprefix("recovery-"), "--run-id", args.run_id], check=True)
        return
    out = ROOT / "outputs" / "low_frequency_research" / args.run_id
    if args.command in ("freeze", "all"):
        out.mkdir(parents=True, exist_ok=False)
        c = load_contract(ROOT / "config" / "low_frequency_research_v1.json")
        write(out / "contract.json", c)
        files = [Path(__file__), ROOT / "kquant_crypto" / "low_frequency_research.py",
                 ROOT / "scripts" / "audit_low_frequency_research.py"]
        snapshot = out / "source_snapshot"
        snapshot.mkdir()
        for p in files:
            shutil.copy2(p, snapshot / p.name)
        write(out / "preregistration.json", {"utc": datetime.now(timezone.utc).isoformat(), "policy_hash": digest(c),
            "python": sys.executable, "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "source_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            "authority": "User approved 2021-2024 DEV only; existing capsule cutoff 1776038400; no tail consumed"})
    c = load_contract(out / "contract.json")
    if digest(c) != json.loads((out / "preregistration.json").read_text())["policy_hash"]: raise ValueError("Policy drift")
    from audit_low_frequency_research import attribution, appendix, paired, concentration, verify, finalize
    stages = (("acquire", acquire), ("build", build), ("attribution", attribution),
              ("replay", run_replays), ("paired", paired), ("concentration", concentration),
              ("appendix", appendix), ("verify", verify), ("report", summarize), ("finalize", finalize))
    for name, function in stages:
        if args.command in (name, "all"):
            source_files = [Path(__file__), ROOT / "kquant_crypto" / "low_frequency_research.py",
                            ROOT / "scripts" / "audit_low_frequency_research.py"]
            attempt = len(list(out.glob(f"{name}_source_manifest*.json"))) + 1
            write(out / f"{name}_source_manifest_{attempt:03d}.json", {"policy_hash": digest(c),
                "source_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
                "started_at": datetime.now(timezone.utc).isoformat()})
            function(out, c)
    print(str(out), flush=True)


if __name__ == "__main__":
    main()
